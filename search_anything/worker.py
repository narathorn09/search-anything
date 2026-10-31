"""Run scans in one separate, low-priority worker process.

Why a process (not just threads):
  * the OS lowers the priority of the *whole* scan process (CPU and disk),
    on Linux, macOS and Windows alike;
  * the web app is never slowed by the scan (no shared Python GIL);
  * a hard RAM ceiling can be enforced: the supervisor kills the worker if it
    grows past it, the web app keeps running, and the scan restarts;
  * if a file crashes the reader (corrupt PDF, out of memory…), the worker
    restarts in "careful" mode (one file at a time, reporting each file before
    reading it), finds the culprit, indexes it by name only and carries on.

The worker writes straight into the SQLite index (WAL mode allows the web
process to keep reading). Progress and the current file come back over a pipe;
stopping uses a shared Event.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

from .db import Database
from .indexer import IndexStats, Indexer, ScanSettings
from .resources import PROFILES, psutil

log = logging.getLogger(__name__)

HARD_RAM_FACTOR = 1.5  # the brake pauses at max_ram_mb; the supervisor kills at 1.5x
MAX_RESTARTS = 8  # per scan
STOP_GRACE_SECONDS = 10  # after Stop, wait this long for a clean exit before terminating
PROGRESS_EVERY = 0.25
SKIPPED_META = "skipped_files"
_CTX = mp.get_context("spawn")  # safe with threads, same behaviour on every OS


def lower_process_priority() -> None:
    """Best effort: background priority for the whole worker process."""
    try:
        if sys.platform.startswith("win"):
            if psutil is not None:
                p = psutil.Process()
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                p.ionice(psutil.IOPRIO_LOW)
        else:
            os.nice(10)  # Linux and macOS
            if sys.platform.startswith("linux") and psutil is not None:
                psutil.Process().ionice(psutil.IOPRIO_CLASS_IDLE)  # disk: only when idle
    except Exception as exc:
        log.debug("could not lower process priority: %s", exc)


# ------------------------------------------------------------------ worker
def worker_main(args: dict, conn, stop_event) -> None:
    """Entry point of the worker process."""
    logging.basicConfig(level=logging.WARNING)
    lower_process_priority()
    send_lock = threading.Lock()

    def send(kind: str, payload) -> None:
        with send_lock:
            conn.send((kind, payload))

    db = Database(args["db_path"])
    ix = Indexer(db, args["folders"], ScanSettings.from_dict(args["settings"]), stop_event=stop_event)
    ix.skip = {path: (v["mtime"], v["size"]) for path, v in args["skip"].items()}
    ix.careful = args["careful"]
    crash_on = os.environ.get("SA_TEST_WORKER_CRASH_ON")  # used by the test-suite only

    def before_extract(path: str) -> None:
        if ix.careful:
            send("file", path)  # so the supervisor knows which file to blame
        if crash_on and Path(path).name == crash_on:
            os._exit(3)

    ix.before_extract = before_extract
    done = threading.Event()

    def report() -> None:
        while not done.wait(PROGRESS_EVERY):
            if ix.running:
                send("progress", ix.status()["progress"])

    threading.Thread(target=report, daemon=True).start()
    ix.running = True
    stats = ix._scan()
    done.set()
    send("done", asdict(stats))
    conn.close()
    db.close()


# -------------------------------------------------------------- supervisor
class ProcessIndexer(Indexer):
    """Same interface as Indexer; each scan runs in a worker process."""

    def __init__(self, db: Database, folders=None, settings=None, hard_ram_mb: int | None = None,
                 max_restarts: int = MAX_RESTARTS):
        super().__init__(db, folders, settings, stop_event=_CTX.Event())
        self.hard_ram_mb = hard_ram_mb  # None = profile.max_ram_mb * HARD_RAM_FACTOR
        self.max_restarts = max_restarts
        self.worker_pid: int | None = None

    def skipped_files(self) -> dict:
        return self.db.get_meta(SKIPPED_META, {})

    def clear_skipped(self) -> int:
        """Forget skipped files and drop their name-only rows, so the next scan
        reads them again (they look unchanged on disk otherwise)."""
        skipped = list(self.skipped_files())
        self.db.delete_paths(skipped)
        self.db.set_meta(SKIPPED_META, {})
        return len(skipped)

    def status(self) -> dict:
        data = super().status()
        data["skipped"] = [{"path": p, **v} for p, v in list(self.skipped_files().items())[:100]]
        data["worker"] = "process"
        return data

    def _scan(self) -> IndexStats:  # runs in a thread of the web process
        profile = PROFILES[self.settings.profile]
        hard_ram = self.hard_ram_mb or int(profile.max_ram_mb * HARD_RAM_FACTOR)
        self.running = True
        start = time.time()
        restarts, careful, errors = 0, False, []
        final: dict | None = None
        self.progress = {"phase": "starting", "started_at": start, "profile": profile.key}
        try:
            while True:
                skip = self.skipped_files()
                args = {"db_path": self.db.path, "folders": self.folders, "settings": asdict(self.settings),
                        "skip": skip, "careful": careful}
                outcome = self._run_worker(args, hard_ram, restarts, careful)
                if outcome["final"] is not None:
                    final = outcome["final"]
                    break
                if self._stop.is_set():
                    break  # stopped; the worker was ended before it could report
                restarts += 1
                reason = outcome["reason"]
                culprit = outcome["last_file"] if careful else None
                if culprit:
                    try:
                        st = os.stat(culprit)
                        skip[culprit] = {"mtime": st.st_mtime, "size": st.st_size, "reason": reason, "at": time.time()}
                        self.db.set_meta(SKIPPED_META, skip)
                        errors.append(f"ข้ามเนื้อหาไฟล์ {culprit} ({reason}) — ยังค้นจากชื่อได้")
                    except OSError:
                        pass
                else:
                    errors.append(f"ตัวสแกนหยุดทำงาน: {reason} — เริ่มใหม่แบบทีละไฟล์")
                log.warning("scan worker failed (%s); restart %d", reason, restarts)
                if restarts > self.max_restarts:
                    errors.append("ยกเลิกการสแกน: ตัวสแกนล่มซ้ำหลายครั้ง")
                    break
                careful = True  # find the file that causes it
        finally:
            stats = IndexStats(**final) if final else IndexStats(profile=profile.key, stopped=self._stop.is_set())
            stats.restarts = restarts
            stats.errors = [*stats.errors, *errors]
            stats.seconds = round(time.time() - start, 2)
            stats.finished_at = time.time()
            self.last_stats = stats
            self.running = False
            self.worker_pid = None
            self.progress = {"phase": "idle"}
        log.info("indexed (worker): %s", stats)
        return stats

    def _run_worker(self, args: dict, hard_ram: int, restarts: int, careful: bool) -> dict:
        parent, child = _CTX.Pipe(duplex=False)
        proc = _CTX.Process(target=worker_main, args=(args, child, self._stop), daemon=True,
                            name="search-anything-scan")
        proc.start()
        child.close()
        self.worker_pid = proc.pid
        watch = None
        if psutil is not None:
            try:
                watch = psutil.Process(proc.pid)
            except psutil.Error:
                pass
        final, last_file, reason, stop_at = None, None, None, None

        def handle(msg) -> None:
            nonlocal final, last_file
            kind, payload = msg
            if kind == "progress":
                self.progress = {**payload, "worker_pid": proc.pid, "restarts": restarts, "careful": careful,
                                 "ram_limit_mb": hard_ram, "worker_ram_mb": self.progress.get("worker_ram_mb")}
            elif kind == "file":
                last_file = payload
                self.progress["current"] = Path(payload).name
            elif kind == "done":
                final = payload

        try:
            next_check = 0.0
            while True:
                # Handle messages, but never let a busy pipe starve the checks below.
                try:
                    deadline = time.monotonic() + 0.25
                    while parent.poll(max(0.0, deadline - time.monotonic())):
                        handle(parent.recv())
                        if time.monotonic() >= deadline:
                            break
                except (EOFError, OSError):
                    break
                if not proc.is_alive():
                    break
                now = time.monotonic()
                if watch is not None and now >= next_check:
                    next_check = now + 0.25
                    try:
                        ram = watch.memory_info().rss / 1e6
                        self.progress["worker_ram_mb"] = round(ram)
                        if ram > hard_ram:
                            reason = f"RAM {ram:.0f} MB เกินเพดาน {hard_ram} MB"
                            proc.kill()
                            break
                    except psutil.Error:
                        pass
                if self._stop.is_set():
                    stop_at = stop_at or now
                    if now - stop_at > STOP_GRACE_SECONDS:
                        proc.terminate()
                        break
            proc.join(10)
            try:
                while parent.poll():
                    handle(parent.recv())
            except (EOFError, OSError):
                pass
        finally:
            if proc.is_alive():
                proc.kill()
                proc.join(5)
            parent.close()
        if final is None and reason is None:
            reason = f"ปิดตัวเองโดยไม่คาดคิด (exit code {proc.exitcode})"
        return {"final": final, "last_file": last_file, "reason": reason}
