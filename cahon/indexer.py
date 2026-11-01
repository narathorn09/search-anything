"""Scan folders and index file names + text content.

Pipeline for a scan:
  1. walk folders with os.scandir (cheap stat info, esp. on Windows),
  2. compare (mtime, size) with the index → only new/changed files continue,
  3. extract text on a small thread pool (bounded, so memory stays flat),
  4. one writer thread per index shard commits in batches.

A scan can be stopped at any time; what was written stays, and the next scan
continues from there (unchanged files are skipped). The performance profile
and the ``Brake`` (see resources.py) keep CPU and RAM use within limits.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections import deque
import multiprocessing as mp
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import ocr
from .db import Database
from .extractors import EXTRACTOR_VERSION, extract_text, is_heavy  # noqa: F401 (re-exported)
from .resources import CPU_COUNT, DEFAULT_PROFILE, PROFILES, Brake, lower_thread_priority

log = logging.getLogger(__name__)

BATCH_ROWS = 200  # rows per shard commit
WRITE_BUDGET_CHARS = 24_000_000  # text waiting to be written, all shards together (~50 MB)
BATCH_SECONDS = 1.0  # …or commit at least this often so results appear during a scan
MAX_OCR_CHARS = 500_000  # OCR text kept per file
OCR_DEFAULT_MAX_PAGES = ocr.DEFAULT_MAX_PAGES
BRAKE_MAX_WAIT = 5.0  # after this long paused, let one item through (never hang)
_SPAWN = mp.get_context("spawn")


class _Budget:
    """Counts characters in flight; acquire() waits while over the limit
    (one oversized item may always pass, so nothing can deadlock)."""

    def __init__(self, limit: int):
        self.limit, self.used = limit, 0
        self._cv = threading.Condition()

    def acquire(self, n: int) -> None:
        with self._cv:
            while self.used and self.used + n > self.limit:
                self._cv.wait(0.5)
            self.used += n

    def release(self, n: int) -> None:
        with self._cv:
            self.used = max(0, self.used - n)
            self._cv.notify_all()


def _helper_init() -> None:
    """Helper processes (PDF readers): background priority, like the scan."""
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    lower_thread_priority()


def _helper_extract(path: str, size: int) -> str:
    if os.environ.get("CAHON_TEST_HELPER_CRASH_ON") == os.path.basename(path):  # test-suite only
        os._exit(3)
    return extract_text(Path(path), size)


SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", ".cache",
    ".idea", ".vscode", "dist", "build", ".next", ".tox", ".mypy_cache", ".pytest_cache",
}


@dataclass
class IndexStats:
    scanned: int = 0
    added_or_updated: int = 0
    removed: int = 0
    seconds: float = 0.0
    stopped: bool = False
    finished_at: float = 0.0
    paused_seconds: float = 0.0
    profile: str = DEFAULT_PROFILE
    restarts: int = 0  # worker process restarts during this scan (process mode)
    ocr_files: int = 0  # files read with OCR during this scan
    ocr_pages: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ScanSettings:
    profile: str = DEFAULT_PROFILE
    auto: bool = True  # rescan in the background
    interval_minutes: int = 5
    ocr: bool = True  # read scanned PDFs with OCR (when Tesseract is installed)
    ocr_images: bool = True  # also read images (jpg, png, tiff …) with OCR
    ocr_max_pages: int = OCR_DEFAULT_MAX_PAGES  # per file

    @classmethod
    def from_dict(cls, data: dict | None, default_interval: int = 5) -> "ScanSettings":
        s = cls(interval_minutes=default_interval)
        for key, value in (data or {}).items():
            if hasattr(s, key):
                setattr(s, key, value)
        if s.profile not in PROFILES:
            s.profile = DEFAULT_PROFILE
        s.interval_minutes = max(1, min(int(s.interval_minutes), 24 * 60))
        s.ocr, s.ocr_images = bool(s.ocr), bool(s.ocr_images)
        s.ocr_max_pages = max(1, min(int(s.ocr_max_pages), 2000))
        return s


class Indexer:
    def __init__(self, db: Database, folders: list[str] | None = None, settings: ScanSettings | None = None,
                 stop_event=None):
        self.db = db
        self._folders = [str(Path(f).expanduser().resolve()) for f in (folders or [])]
        self.settings = settings or ScanSettings()
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._queued = False
        self._stop = stop_event if stop_event is not None else threading.Event()
        # Set by the worker process: files to index by name only (they crashed
        # a previous scan), and a hook called right before each file is read.
        self.skip: dict[str, tuple[float, int]] = {}
        self.before_extract = None
        self.careful = False  # one file at a time (used after a crash)
        self.exit_on_helper_crash = False  # set in the worker process
        self._last_stop = 0.0
        self._wake = threading.Event()
        self._brake: Brake | None = None
        self.last_stats: IndexStats | None = None
        self.running = False
        self.progress: dict = {"phase": "idle"}
        self._ocr_known: dict[str, tuple[float, int, str]] = {}

    @property
    def folders(self) -> list[str]:
        return list(self._folders)

    def set_folders(self, folders: list[str]) -> None:
        self._folders = [str(Path(f).expanduser().resolve()) for f in folders]

    def update_settings(self, settings: ScanSettings) -> None:
        self.settings = settings
        self._wake.set()  # re-plan the background schedule

    # -------------------------------------------------------------- control
    def trigger(self) -> None:
        """Scan in the background. If a scan is already running, one more scan
        is queued so changes made during the current scan are not missed."""
        with self._state_lock:
            if self._queued:
                return
            self._queued = True
        requested = time.monotonic()
        threading.Thread(target=self.run, args=(requested,), daemon=True).start()

    def stop(self) -> bool:
        """Stop the running scan (and any queued one). Returns True if one was running."""
        with self._state_lock:
            self._last_stop = time.monotonic()
            self._queued = False
        if self.running:
            self._stop.set()
            self.progress["phase"] = "stopping"
            return True
        return False

    def run(self, requested_at: float | None = None) -> IndexStats:
        """Incrementally index all folders (blocks while another scan runs).
        Only changed files are re-read."""
        with self._run_lock:
            with self._state_lock:
                self._queued = False
                if requested_at is not None and self._last_stop > requested_at:
                    return self.last_stats or IndexStats()  # cancelled by stop()
            self._stop.clear()
            return self._scan()

    def status(self) -> dict:
        info = dict(self.progress)
        if self.running and self._brake is not None:
            info.update(self._brake.snapshot())
        return {
            "running": self.running,
            "progress": info,
            "last": asdict(self.last_stats) if self.last_stats else None,
            "settings": asdict(self.settings),
            "ocr": {**ocr.engine().info(), **self.db.ocr_summary()},
        }

    # ----------------------------------------------------------------- scan
    @staticmethod
    def _walk(root: str):
        """Yield (path, name, stat) for every file under root, skipping junk dirs."""
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        name = entry.name
                        if name.startswith("."):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if name not in SKIP_DIRS:
                                    stack.append(entry.path)
                            elif entry.is_file():
                                yield entry.path, name, entry.stat()
                        except OSError:
                            continue
            except OSError:
                continue

    def _scan(self) -> IndexStats:
        profile = PROFILES[self.settings.profile]
        brake = self._brake = Brake(profile, self._stop)
        self.running = True
        stats = IndexStats(profile=profile.key)
        start = time.time()
        self.progress = {"phase": "walking", "scanned": 0, "done": 0, "total": 0, "started_at": start,
                         "current": "", "rate": 0.0, "eta_seconds": None, "profile": profile.key}
        # A newer extractor reads more formats: read every file again once.
        reextract = self.db.get_meta("extractor_version", 1) < EXTRACTOR_VERSION
        self._ocr_known = self.db.ocr_states()
        try:
            known = self.db.file_index()
            seen: set[str] = set()
            todo: list[tuple[str, str, float, int]] = []
            for folder in self._folders:
                self.progress["path"] = folder  # which folder is being walked (home screen panel)
                if not os.path.isdir(folder):
                    stats.errors.append(f"not a folder: {folder}")
                    continue
                for path, name, st in self._walk(folder):
                    seen.add(path)
                    stats.scanned += 1
                    if stats.scanned % 500 == 0:
                        self.progress["scanned"] = stats.scanned
                        if self._stop.is_set():
                            break
                        brake.wait(memory_only=True, max_wait=BRAKE_MAX_WAIT)
                    previous = known.get(path)
                    if not reextract and previous and previous[1] == st.st_mtime and previous[2] == st.st_size:
                        continue
                    todo.append((path, name, st.st_mtime, st.st_size))
                if self._stop.is_set():
                    break
            self.progress["scanned"] = stats.scanned
            if self._stop.is_set():
                # The walk is incomplete, so "missing" files may just be unvisited:
                # don't delete anything.
                stats.stopped = True
                return stats
            stale = [p for p in known if p not in seen]
            if stale:
                self.db.delete_paths(stale)
                self.db.ocr_forget([p for p in stale if p in self._ocr_known])
                stats.removed = len(stale)
            stats.added_or_updated = self._index(todo, profile, brake)
            if not self._stop.is_set():
                self._ocr_phase(profile, brake, stats)
            stats.stopped = self._stop.is_set()
            if reextract and not stats.stopped:
                self.db.set_meta("extractor_version", EXTRACTOR_VERSION)
        finally:
            stats.seconds = round(time.time() - start, 2)
            stats.finished_at = time.time()
            stats.paused_seconds = round(brake.paused_seconds, 1)
            self.last_stats = stats
            self.running = False
            self._brake = None
            self.db.invalidate()  # cached result lists are out of date now
            self.progress = {"phase": "idle"}
        log.info("indexed: %s", stats)
        return stats

    def _index(self, todo, profile, brake: Brake) -> int:
        """Extract and store files. Returns how many were written."""
        if not todo:
            return 0
        self.progress.update(phase="indexing", total=len(todo), done=0)
        shards = self.db.shards
        # Unbounded per-shard queues share one memory budget: a shard that is busy
        # committing never stalls the others (with a small fixed queue per shard,
        # one full queue blocked the whole pipeline and writes ran one at a time).
        queues: list[queue.Queue] = [queue.Queue() for _ in shards]
        budget = _Budget(WRITE_BUDGET_CHARS)
        write_slots = threading.Semaphore(profile.write_parallel)
        errors: list[BaseException] = []

        def writer(shard, q: queue.Queue) -> None:
            lower_thread_priority()
            batch, last = [], time.monotonic()
            while True:
                try:
                    row = q.get(timeout=BATCH_SECONDS)
                except queue.Empty:
                    row = ...
                if row is not None and row is not ...:
                    batch.append(row)
                due = len(batch) >= BATCH_ROWS or time.monotonic() - last >= BATCH_SECONDS
                if batch and (row is None or due):
                    # Writing is the CPU-heavy part: respect the CPU limit here too.
                    # (Writers never wait on memory — writing frees memory.)
                    if row is not None:
                        brake.wait(max_wait=BRAKE_MAX_WAIT)
                    try:
                        with write_slots:
                            shard.upsert_many(batch)
                    except BaseException as exc:  # keep draining so producers never block
                        errors.append(exc)
                    finally:
                        budget.release(sum(len(r[2]) + 1 for r in batch))
                    batch, last = [], time.monotonic()
                if row is None:
                    return

        writers = [threading.Thread(target=writer, args=(s, q), daemon=True) for s, q in zip(shards, queues)]
        for w in writers:
            w.start()

        def extract(item):
            path, name, mtime, size = item
            if self.skip.get(path) == (mtime, size):
                return path, name, "", mtime, size  # crashed before: name only
            if self.before_extract:
                self.before_extract(path)
            return path, name, extract_text(Path(path), size), mtime, size

        done = 0
        started = time.monotonic()
        workers = 1 if self.careful else profile.extract_workers
        in_flight = 1 if self.careful else workers * 4
        pool = ThreadPoolExecutor(workers, thread_name_prefix="extract",
                                  initializer=lower_thread_priority)
        # Readers that hold Python's GIL or may not run twice in one process
        # (pdfium) get helper processes, so they too use several CPU cores.
        helpers = None
        n_helpers = 0 if self.careful else min(profile.extract_workers, CPU_COUNT)
        if n_helpers > 1 and any(is_heavy(t[0]) for t in todo):
            helpers = ProcessPoolExecutor(n_helpers, mp_context=_SPAWN, initializer=_helper_init)
            in_flight += n_helpers * 2
        try:
            pending: set = set()
            items = iter(todo)
            while not self._stop.is_set():
                brake.wait(max_wait=BRAKE_MAX_WAIT)
                while len(pending) < in_flight and not self._stop.is_set():
                    nxt = next(items, None)
                    if nxt is None:
                        break
                    path, name, mtime, size = nxt
                    if helpers is not None and is_heavy(path) and self.skip.get(path) != (mtime, size):
                        if self.before_extract:
                            self.before_extract(path)
                        fut = helpers.submit(_helper_extract, path, size)
                        fut.item = nxt
                    else:
                        fut = pool.submit(extract, nxt)
                    pending.add(fut)
                if not pending:
                    break
                finished, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                for fut in finished:
                    item = getattr(fut, "item", None)
                    if item is None:
                        path, name, text, mtime, size = fut.result()
                    else:
                        path, name, mtime, size = item
                        try:
                            text = fut.result()
                        except BrokenProcessPool:
                            # A helper died on some file (corrupt PDF…). In the worker
                            # process: exit, so the supervisor restarts in careful mode
                            # and finds the culprit. Otherwise read it here.
                            if self.exit_on_helper_crash:
                                os._exit(4)
                            text = extract_text(Path(path), size)
                    text = self._with_ocr(path, text, mtime, size)
                    budget.acquire(len(text) + 1)
                    queues[self.db.shard_for(path).index].put((path, name, text, mtime, size))
                    done += 1
                    elapsed = time.monotonic() - started
                    rate = done / elapsed if elapsed > 0 else 0.0
                    self.progress.update(done=done, current=name, path=path, rate=round(rate, 1),
                                         eta_seconds=round((len(todo) - done) / rate) if rate else None)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            if helpers is not None:
                helpers.shutdown(wait=True, cancel_futures=True)
            for q in queues:
                q.put(None)
            for w in writers:
                w.join()
        if errors:
            raise errors[0]
        return done

    # ------------------------------------------------------------------ ocr
    def _with_ocr(self, path: str, text: str, mtime: float, size: int) -> str:
        """Re-reading a file that was already read with OCR: keep that text."""
        known = self._ocr_known.get(path)
        if known and known[2] == "done" and known[:2] == (mtime, size):
            saved = self.db.ocr_text(path, mtime, size)
            if saved:
                return ocr.merge(text, saved)
        return text

    def ocr_pending(self) -> list[tuple[str, int, float, int]]:
        """Indexed files that should be read with OCR: (path, id, mtime, size), newest first."""
        if not self.settings.ocr:
            return []
        states = self.db.ocr_states()
        todo = [(path, item_id, mtime, size) for path, (item_id, mtime, size) in self.db.file_index().items()
                if ocr.is_candidate(path, self.settings.ocr_images)
                and states.get(path, (None, None))[:2] != (mtime, size)]
        todo.sort(key=lambda t: t[2], reverse=True)
        return todo

    def _ocr_phase(self, profile, brake: Brake, stats: IndexStats) -> None:
        """Read scanned PDFs (and images, if enabled) with OCR, newest first.
        Runs after the normal scan, so plain search results are never delayed."""
        eng = ocr.engine()
        if not self.settings.ocr or not eng.available:
            return
        todo = self.ocr_pending()
        if not todo:
            return
        self.progress.update(phase="ocr", total=len(todo), done=0, current="", page=0, pages=0,
                             rate=0.0, eta_seconds=None)
        reader = ocr.Reader(eng, threads=min(4, profile.extract_workers) if profile.key == "fast" else 1,
                            should_stop=self._stop.is_set)

        def on_page(n: int, total: int) -> None:
            self.progress.update(page=n, pages=total)
            brake.wait(max_wait=BRAKE_MAX_WAIT)

        reader.on_page = on_page
        started = time.monotonic()
        for done, (path, item_id, mtime, size) in enumerate(todo):
            if self._stop.is_set():
                return
            brake.wait(max_wait=BRAKE_MAX_WAIT)
            self.progress.update(current=os.path.basename(path), path=path, page=0, pages=0)
            try:
                st = os.stat(path)
            except OSError:
                continue  # gone: the next scan removes it
            if (st.st_mtime, st.st_size) != (mtime, size):
                continue  # changed since it was indexed: the next scan reads it again
            if self.skip.get(path) == (mtime, size):
                self.db.set_ocr(path, mtime, size, "failed", 0, "")  # crashed the scanner before
                continue
            if self.before_extract:
                self.before_extract(path)
            t0 = time.monotonic()
            try:
                text, pages = reader.read(path, self.settings.ocr_max_pages)
                status = "done" if text else "none"
            except ocr.Stopped:
                return
            except Exception as exc:  # encrypted / corrupt / unsupported
                log.debug("OCR failed for %s: %s", path, exc)
                text, pages, status = "", 0, "failed"
            text = text[:MAX_OCR_CHARS]
            if text:
                item = self.db.get_item(item_id, max_chars=MAX_OCR_CHARS * 2)
                if item is not None:
                    body = ocr.merge(item.get("body") or "", text)
                    self.db.shard_for(path).upsert_many([(path, item["title"], body, mtime, size)])
            self.db.set_ocr(path, mtime, size, status, pages, text, round(time.monotonic() - t0, 2))
            stats.ocr_files += 1
            stats.ocr_pages += pages
            elapsed = time.monotonic() - started
            rate = (done + 1) / elapsed if elapsed > 0 else 0.0
            # No time estimate: files differ too much in page count.
            self.progress.update(done=done + 1, rate=round(rate, 2), eta_seconds=None)

    def index_paths(self, paths: list[str]) -> list[int]:
        """Index specific files right away (used after an upload). Returns item ids."""
        ids = []
        for p in paths:
            path = Path(p)
            st = path.stat()
            text = extract_text(path, st.st_size)
            ids.append(self.db.upsert_file(str(path), path.name, text, st.st_mtime, st.st_size))
        return ids

    def start_background(self) -> threading.Thread:
        """Scan now and then every ``settings.interval_minutes`` while ``settings.auto``."""
        def loop():
            while True:
                last = self.last_stats.finished_at if self.last_stats else 0.0
                due = last + self.settings.interval_minutes * 60
                if self.settings.auto and time.time() >= due:
                    try:
                        self.run()
                    except Exception:
                        log.exception("indexing failed")
                    continue
                # Sleep until the next scan is due; settings changes wake us early
                # to re-plan (they never start a scan by themselves).
                timeout = max(1.0, due - time.time()) if self.settings.auto else None
                self._wake.wait(timeout)
                self._wake.clear()

        thread = threading.Thread(target=loop, name="indexer", daemon=True)
        thread.start()
        return thread
