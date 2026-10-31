"""Scan folders and index file names + text content.

Pipeline for a scan:
  1. walk folders with os.scandir (cheap stat info, esp. on Windows),
  2. compare (mtime, size) with the index → only new/changed files continue,
  3. extract text on a thread pool (bounded, so memory stays flat),
  4. one writer thread per index shard commits in batches, so SQLite's FTS
     indexing — the expensive part — runs on several cores at once.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .db import Database

log = logging.getLogger(__name__)

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp",
    ".hpp", ".cs", ".php", ".rb", ".swift", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".vue",
    ".svelte", ".dart", ".lua", ".r", ".tex",
}
SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", ".cache",
    ".idea", ".vscode", "dist", "build", ".next", ".tox", ".mypy_cache", ".pytest_cache",
}
MAX_CONTENT_BYTES = 20 * 1024 * 1024  # don't read content of files bigger than this
MAX_TEXT_CHARS = 500_000  # cap stored text per file
BATCH_ROWS = 200  # rows per shard commit
BATCH_SECONDS = 1.0  # …or commit at least this often so results appear during a scan
EXTRACT_WORKERS = min(8, (os.cpu_count() or 2) * 2)
MAX_IN_FLIGHT = EXTRACT_WORKERS * 4


def extract_text(path: Path, size: int | None = None) -> str:
    """Return the searchable text content of a file ('' if unsupported)."""
    suffix = path.suffix.lower()
    try:
        if (size if size is not None else path.stat().st_size) > MAX_CONTENT_BYTES:
            return ""
        if suffix in TEXT_EXTENSIONS:
            raw = path.read_bytes()
            if b"\x00" in raw[:4096]:
                return ""
            for encoding in ("utf-8", "cp874", "latin-1"):
                try:
                    return raw.decode(encoding)[:MAX_TEXT_CHARS]
                except UnicodeDecodeError:
                    continue
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            parts, total = [], 0
            for page in reader.pages:
                text = page.extract_text() or ""
                parts.append(text)
                total += len(text)
                if total > MAX_TEXT_CHARS:
                    break
            return "\n".join(parts)[:MAX_TEXT_CHARS]
        if suffix == ".docx":
            import docx

            document = docx.Document(str(path))
            return "\n".join(p.text for p in document.paragraphs)[:MAX_TEXT_CHARS]
    except Exception as exc:  # corrupt / locked / unreadable files
        log.debug("could not extract %s: %s", path, exc)
    return ""


@dataclass
class IndexStats:
    scanned: int = 0
    added_or_updated: int = 0
    removed: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class Indexer:
    def __init__(self, db: Database, folders: list[str] | None = None):
        self.db = db
        self._folders = [str(Path(f).expanduser().resolve()) for f in (folders or [])]
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._queued = False
        self.last_stats: IndexStats | None = None
        self.running = False
        self.progress = {"phase": "idle", "done": 0, "total": 0}

    @property
    def folders(self) -> list[str]:
        return list(self._folders)

    def set_folders(self, folders: list[str]) -> None:
        self._folders = [str(Path(f).expanduser().resolve()) for f in folders]

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

    def trigger(self) -> None:
        """Scan in the background. If a scan is already running, one more scan
        is queued so changes made during the current scan are not missed."""
        with self._state_lock:
            if self._queued:
                return
            self._queued = True
        threading.Thread(target=self.run, daemon=True).start()

    def run(self) -> IndexStats:
        """Incrementally index all folders (blocks while another scan runs).
        Only changed files are re-read."""
        with self._run_lock:
            with self._state_lock:
                self._queued = False
            return self._scan()

    def _scan(self) -> IndexStats:
        self.running = True
        stats = IndexStats()
        start = time.time()
        self.progress = {"phase": "walking", "done": 0, "total": 0}
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
                    previous = known.get(path)
                    if previous and previous[1] == st.st_mtime and previous[2] == st.st_size:
                        continue
                    todo.append((path, name, st.st_mtime, st.st_size))
            stale = [p for p in known if p not in seen]
            if stale:
                self.db.delete_paths(stale)
                stats.removed = len(stale)
            stats.added_or_updated = self._index(todo)
        finally:
            stats.seconds = round(time.time() - start, 2)
            self.last_stats = stats
            self.running = False
            self.progress = {"phase": "idle", "done": 0, "total": 0}
        log.info("indexed: %s", stats)
        return stats

    def _index(self, todo: list[tuple[str, str, float, int]]) -> int:
        """Extract and store files. Returns how many were written."""
        if not todo:
            return 0
        self.progress = {"phase": "indexing", "done": 0, "total": len(todo)}
        shards = self.db.shards
        queues: list[queue.Queue] = [queue.Queue(maxsize=BATCH_ROWS * 2) for _ in shards]
        errors: list[BaseException] = []

        def writer(shard, q: queue.Queue) -> None:
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
                    try:
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
            return path, name, extract_text(Path(path), size), mtime, size

        done = 0
        try:
            with ThreadPoolExecutor(EXTRACT_WORKERS, thread_name_prefix="extract") as pool:
                pending: deque = deque()
                items = iter(todo)
                while True:
                    while len(pending) < MAX_IN_FLIGHT:
                        nxt = next(items, None)
                        if nxt is None:
                            break
                        pending.append(pool.submit(extract, nxt))
                    if not pending:
                        break
                    path, name, text, mtime, size = pending.popleft().result()
                    queues[self.db.shard_for(path).index].put((path, name, text, mtime, size))
                    done += 1
                    self.progress["done"] = done
        finally:
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

    def start_background(self, interval_seconds: int) -> threading.Thread:
        def loop():
            while True:
                try:
                    self.run()
                except Exception:
                    log.exception("indexing failed")
                time.sleep(interval_seconds)

        thread = threading.Thread(target=loop, name="indexer", daemon=True)
        thread.start()
        return thread
