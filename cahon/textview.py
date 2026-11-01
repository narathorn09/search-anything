"""Read big text files for the viewer without loading them into memory.

A ``LineIndex`` remembers where every line starts (8 bytes per line), so the
viewer can ask for any range of lines and only those bytes are read. Finding
a word streams through the file once. Indexes are cached (LRU) and rebuilt
when the file changes.

Works for UTF-8 and single-byte encodings (Thai cp874, latin-1): in all of
them a newline is the byte 0x0A, so byte offsets can be found without
decoding. UTF-16 files are decoded in memory (rare, and size-capped).
"""

from __future__ import annotations

import codecs
import re
import threading
import time
from array import array
from collections import OrderedDict
from pathlib import Path

CHUNK = 1 << 20  # 1 MB reads while indexing / searching
MAX_FILE_BYTES = 2 * 1024 ** 3  # refuse to index anything bigger (2 GB)
MAX_UTF16_BYTES = 50 * 1024 ** 2
MAX_LINE_CHARS = 5000  # very long lines are cut when shown (the file is untouched)
FIND_DEADLINE = 6.0  # seconds a search inside one file may take
CACHE_SIZE = 8


def _detect_encoding(path: Path) -> str:
    """utf-16 / utf-8 / cp874 / latin-1 — checked over the whole file, streaming."""
    with path.open("rb") as f:
        head = f.read(4)
        if head.startswith((b"\xff\xfe", b"\xfe\xff")):
            return "utf-16"
        f.seek(0)
        for encoding in ("utf-8", "cp874"):
            decoder = codecs.getincrementaldecoder(encoding)()
            try:
                while chunk := f.read(CHUNK):
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
                return "utf-8-sig" if encoding == "utf-8" and head.startswith(b"\xef\xbb\xbf") else encoding
            except UnicodeDecodeError:
                f.seek(0)
    return "latin-1"


class LineIndex:
    """Random access to the lines of one text (a file on disk, or a string)."""

    def __init__(self, path: Path | None = None, text: str | None = None):
        self.path = path
        self.encoding = "utf-8"
        self._lines: list[str] | None = None  # in-memory texts
        self.offsets = array("Q")
        if text is not None:
            self._lines = text.split("\n")
        else:
            self._build()

    def _build(self) -> None:
        size = self.path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError("file too large to view")
        self.encoding = _detect_encoding(self.path)
        if self.encoding == "utf-16":
            if size > MAX_UTF16_BYTES:
                raise ValueError("UTF-16 file too large to view")
            self._lines = self.path.read_text(encoding="utf-16").split("\n")
            return
        offsets = array("Q", [0])
        pos = 0
        with self.path.open("rb") as f:
            while chunk := f.read(CHUNK):
                start = 0
                while (i := chunk.find(b"\n", start)) != -1:
                    offsets.append(pos + i + 1)
                    start = i + 1
                pos += len(chunk)
        if offsets[-1] != pos:
            offsets.append(pos)  # last line without a trailing newline
        elif len(offsets) == 1:
            offsets.append(0)  # empty file: one empty line
        self.offsets = offsets
        self.end = pos

    @property
    def total_lines(self) -> int:
        return len(self._lines) if self._lines is not None else max(1, len(self.offsets) - 1)

    def _clean(self, line: str) -> str:
        line = line.rstrip("\r")
        return line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + " …"

    def lines(self, start: int, count: int) -> list[str]:
        """Lines [start, start+count) (0-based)."""
        start = max(0, start)
        end = min(self.total_lines, start + max(0, count))
        if start >= end:
            return []
        if self._lines is not None:
            return [self._clean(x) for x in self._lines[start:end]]
        with self.path.open("rb") as f:
            f.seek(self.offsets[start])
            raw = f.read(self.offsets[end] - self.offsets[start])
        text = raw.decode(self.encoding, errors="replace")
        if text.endswith("\n"):
            text = text[:-1]
        return [self._clean(x) for x in text.split("\n")][: end - start]

    def _iter_lines(self):
        if self._lines is not None:
            yield from self._lines
            return
        with self.path.open("rb") as f:
            for raw in f:
                yield raw.decode(self.encoding, errors="replace").rstrip("\n").rstrip("\r")

    def find(self, words: list[str], max_hits: int = 2000) -> dict:
        """Lines containing any of the words (case-insensitive), streaming.

        Returns {"total_matches", "total_lines", "hits": [{"line", "count", "preview"}], "partial"}
        — ``hits`` stops at ``max_hits`` lines, totals keep counting until the deadline."""
        words = [w for w in words if w]
        if not words:
            return {"total_matches": 0, "total_lines": 0, "hits": [], "partial": False}
        pattern = re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE)
        deadline = time.monotonic() + FIND_DEADLINE
        hits, total, lines_hit, partial = [], 0, 0, False
        for n, line in enumerate(self._iter_lines()):
            if n % 4096 == 0 and time.monotonic() > deadline:
                partial = True
                break
            found = pattern.findall(line)
            if not found:
                continue
            total += len(found)
            lines_hit += 1
            if len(hits) < max_hits:
                m = pattern.search(line)
                start = max(0, m.start() - 30)
                hits.append({"line": n + 1, "count": len(found), "col": m.start(),
                             "preview": ("…" if start else "") + line[start:start + 160]})
        return {"total_matches": total, "total_lines": lines_hit, "hits": hits, "partial": partial}


class LineIndexCache:
    """A few recent indexes, keyed by (path, size, mtime) so edits rebuild them."""

    def __init__(self, size: int = CACHE_SIZE):
        self.size = size
        self._items: OrderedDict[tuple, LineIndex] = OrderedDict()
        self._lock = threading.Lock()

    def for_file(self, path: Path) -> LineIndex:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime)
        with self._lock:
            idx = self._items.get(key)
            if idx is not None:
                self._items.move_to_end(key)
                return idx
        idx = LineIndex(path)  # built outside the lock
        with self._lock:
            self._items[key] = idx
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return idx
