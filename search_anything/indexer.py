"""Scan folders and index file names + text content."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .db import Database

log = logging.getLogger(__name__)

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".env.example", ".xml", ".html", ".htm", ".css",
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


def extract_text(path: Path) -> str:
    """Return the searchable text content of a file ('' if unsupported)."""
    suffix = path.suffix.lower()
    try:
        if path.stat().st_size > MAX_CONTENT_BYTES:
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
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) > MAX_TEXT_CHARS:
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
        self.last_stats: IndexStats | None = None
        self.running = False

    @property
    def folders(self) -> list[str]:
        return list(self._folders)

    def set_folders(self, folders: list[str]) -> None:
        self._folders = [str(Path(f).expanduser().resolve()) for f in folders]

    def _walk(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                yield Path(dirpath) / name

    def run(self) -> IndexStats:
        """Incrementally index all folders. Only changed files are re-read."""
        if not self._run_lock.acquire(blocking=False):
            return self.last_stats or IndexStats()
        self.running = True
        stats = IndexStats()
        start = time.time()
        try:
            known = self.db.file_index()
            seen: set[str] = set()
            for folder in self._folders:
                root = Path(folder)
                if not root.is_dir():
                    stats.errors.append(f"not a folder: {folder}")
                    continue
                for path in self._walk(root):
                    try:
                        st = path.stat()
                    except OSError:
                        continue
                    key = str(path)
                    seen.add(key)
                    stats.scanned += 1
                    previous = known.get(key)
                    if previous and previous[1] == st.st_mtime and previous[2] == st.st_size:
                        continue
                    content = extract_text(path)
                    # Body holds the path too so folder names are searchable.
                    body = f"{key}\n{content}" if content else key
                    self.db.upsert_file(key, path.name, body, st.st_mtime, st.st_size)
                    stats.added_or_updated += 1
            stale = [p for p in known if p not in seen]
            if stale:
                self.db.delete_paths(stale)
                stats.removed = len(stale)
        finally:
            stats.seconds = round(time.time() - start, 2)
            self.last_stats = stats
            self.running = False
            self._run_lock.release()
        log.info("indexed: %s", stats)
        return stats

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
