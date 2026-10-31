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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .db import Database
from .extractors import EXTRACTOR_VERSION, extract_text  # noqa: F401 (re-exported)
from .resources import DEFAULT_PROFILE, PROFILES, Brake, lower_thread_priority

log = logging.getLogger(__name__)

BATCH_ROWS = 200  # rows per shard commit
BATCH_SECONDS = 1.0  # …or commit at least this often so results appear during a scan
BRAKE_MAX_WAIT = 5.0  # after this long paused, let one item through (never hang)
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
    errors: list[str] = field(default_factory=list)


@dataclass
class ScanSettings:
    profile: str = DEFAULT_PROFILE
    auto: bool = True  # rescan in the background
    interval_minutes: int = 5

    @classmethod
    def from_dict(cls, data: dict | None, default_interval: int = 5) -> "ScanSettings":
        s = cls(interval_minutes=default_interval)
        for key, value in (data or {}).items():
            if hasattr(s, key):
                setattr(s, key, value)
        if s.profile not in PROFILES:
            s.profile = DEFAULT_PROFILE
        s.interval_minutes = max(1, min(int(s.interval_minutes), 24 * 60))
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
        self._last_stop = 0.0
        self._wake = threading.Event()
        self._brake: Brake | None = None
        self.last_stats: IndexStats | None = None
        self.running = False
        self.progress: dict = {"phase": "idle"}

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
        try:
            known = self.db.file_index()
            seen: set[str] = set()
            todo: list[tuple[str, str, float, int]] = []
            for folder in self._folders:
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
                stats.removed = len(stale)
            stats.added_or_updated = self._index(todo, profile, brake)
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
        queues: list[queue.Queue] = [queue.Queue(maxsize=BATCH_ROWS) for _ in shards]
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
        try:
            pending: deque = deque()
            items = iter(todo)
            while not self._stop.is_set():
                brake.wait(max_wait=BRAKE_MAX_WAIT)
                while len(pending) < in_flight and not self._stop.is_set():
                    nxt = next(items, None)
                    if nxt is None:
                        break
                    pending.append(pool.submit(extract, nxt))
                if not pending:
                    break
                path, name, text, mtime, size = pending.popleft().result()
                queues[self.db.shard_for(path).index].put((path, name, text, mtime, size))
                done += 1
                elapsed = time.monotonic() - started
                rate = done / elapsed if elapsed > 0 else 0.0
                self.progress.update(done=done, current=name, rate=round(rate, 1),
                                     eta_seconds=round((len(todo) - done) / rate) if rate else None)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            for q in queues:
                q.put(None)
            for w in writers:
                w.join()
        if errors:
            raise errors[0]
        return done

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
