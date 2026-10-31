"""SQLite storage with FTS5 trigram indexes.

Layout
------
* ``search.db``            notes, bookmarks, passwords and settings (small).
* ``search-files-N.db``    indexed files, split into ``FILE_SHARDS`` shards by a
                           hash of the path. Each shard is written by its own
                           thread, so scanning uses several CPU cores (the FTS
                           trigram indexing inside SQLite is the expensive part).

The trigram tokenizer matches any substring of 3+ characters, which works for
Thai (no spaces between words) as well as English, file names and URLs.
Shorter query terms fall back to LIKE on names / paths / titles.

Ranking
-------
FTS5's bm25() must visit *every* matching document to compute its statistics,
which is slow for common words. Instead we rank:
  1. title / file-name / path matches first,
  2. then content matches,
each by most recently modified. Candidates are read in rowid order with a
LIMIT, which FTS5 can stop early on — so common words stay fast.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Iterable

KINDS = ("file", "note", "bookmark", "password")
FILE_SHARDS = 4
FILE_ID_BASE = 10**12  # file ids are (shard + 1) * FILE_ID_BASE + rowid
CANDIDATES = 400  # content matches considered per shard before sorting
EXCERPT_CHARS = 260
EXCERPT_LEAD = 60

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA cache_size=-16384",  # 16 MB per connection
    "PRAGMA mmap_size=0",  # keep memory use predictable (the scan brake watches RSS)
)

ITEMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    extra       TEXT NOT NULL DEFAULT '{}',
    secret      BLOB,
    path        TEXT UNIQUE,
    mtime       REAL,
    size        INTEGER,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS items_kind ON items(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, body, content='items', content_rowid='id', tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE OF title, body ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO items_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# File metadata is kept apart from the text so LIKE scans over names/paths
# never touch file contents. The text lives only in the FTS table.
SHARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    path        TEXT NOT NULL UNIQUE,
    mtime       REAL NOT NULL,
    size        INTEGER NOT NULL,
    indexed_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS files_mtime ON files(mtime);
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(title, path, body, tokenize='trigram');
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        if path == ":memory:" and "journal_mode" in pragma:
            continue
        conn.execute(pragma)
    return conn


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _match(terms: list[str]) -> str:
    """FTS5 query: every term must appear; quoting makes syntax characters literal."""
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)


def split_terms(query: str) -> tuple[list[str], list[str]]:
    terms = [t for t in query.split() if t]
    return [t for t in terms if len(t) >= 3], [t for t in terms if len(t) < 3]


class FileShard:
    """One shard of the file index: a write connection and a read connection."""

    def __init__(self, path: str, index: int):
        self.index = index
        self.memory = path == ":memory:"
        self._wlock = threading.Lock()
        self._rlock = threading.Lock()
        self.wconn = _connect(path)
        self.wconn.executescript(SHARD_SCHEMA)
        self.wconn.commit()
        # WAL lets the reader see committed data while a scan is writing.
        self.rconn = self.wconn if self.memory else _connect(path)
        if self.memory:
            self._rlock = self._wlock

    def to_id(self, rowid: int) -> int:
        return (self.index + 1) * FILE_ID_BASE + rowid

    # ------------------------------------------------------------- writes
    def upsert_many(self, rows: Iterable[tuple[str, str, str, float, int]]) -> None:
        """rows: (path, title, body, mtime, size)."""
        now = time.time()
        with self._wlock, self.wconn:
            c = self.wconn
            for path, title, body, mtime, size in rows:
                old = c.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
                if old:
                    rowid = old[0]
                    c.execute("UPDATE files SET title=?, mtime=?, size=?, indexed_at=? WHERE id=?",
                              (title, mtime, size, now, rowid))
                    c.execute("DELETE FROM files_fts WHERE rowid=?", (rowid,))
                else:
                    rowid = c.execute(
                        "INSERT INTO files(title, path, mtime, size, indexed_at) VALUES (?,?,?,?,?)",
                        (title, path, mtime, size, now),
                    ).lastrowid
                c.execute("INSERT INTO files_fts(rowid, title, path, body) VALUES (?,?,?,?)",
                          (rowid, title, path, body))

    def delete_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        with self._wlock, self.wconn:
            for path in paths:
                row = self.wconn.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
                if row:
                    self.wconn.execute("DELETE FROM files_fts WHERE rowid=?", (row[0],))
                    self.wconn.execute("DELETE FROM files WHERE id=?", (row[0],))

    # -------------------------------------------------------------- reads
    def known(self) -> dict[str, tuple[int, float, int]]:
        with self._rlock:
            rows = self.rconn.execute("SELECT id, path, mtime, size FROM files").fetchall()
        return {r["path"]: (self.to_id(r["id"]), r["mtime"], r["size"]) for r in rows}

    def count(self) -> int:
        with self._rlock:
            return self.rconn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    def get(self, rowid: int, max_chars: int = 20000) -> dict | None:
        with self._rlock:
            row = self.rconn.execute(
                "SELECT f.*, substr(t.body, 1, ?) AS body FROM files f "
                "JOIN files_fts t ON t.rowid = f.id WHERE f.id=?", (max_chars, rowid)
            ).fetchone()
        return self._as_item(row, body=row["body"]) if row else None

    def _as_item(self, row, body: str = "", rank: tuple = (1, 0)) -> dict:
        return {
            "id": self.to_id(row["id"]), "kind": "file", "title": row["title"], "path": row["path"],
            "mtime": row["mtime"], "size": row["size"], "updated_at": row["mtime"],
            "created_at": row["indexed_at"], "extra": "{}", "secret": None, "body": body, "rank": rank,
        }

    def search(self, long_terms: list[str], short_terms: list[str], limit: int) -> list[dict]:
        short_sql = " AND ".join("(f.title LIKE ? ESCAPE '\\' OR f.path LIKE ? ESCAPE '\\')" for _ in short_terms)
        short_params = [p for t in short_terms for p in (_like(t), _like(t))]
        with self._rlock:
            c = self.rconn
            if not long_terms:
                rows = c.execute(
                    f"SELECT f.* FROM files f WHERE {short_sql} ORDER BY f.mtime DESC LIMIT ?",
                    (*short_params, limit),
                ).fetchall()
                hits = [(r, 0) for r in rows]
            else:
                match = _match(long_terms)
                extra = f" AND {short_sql}" if short_sql else ""
                sql = ("SELECT f.* FROM files_fts JOIN files f ON f.id = files_fts.rowid "
                       f"WHERE files_fts MATCH ?{extra} ORDER BY files_fts.rowid DESC LIMIT ?")
                name_rows = c.execute(sql, (f"{{title path}} : ({match})", *short_params, limit)).fetchall()
                body_rows = c.execute(sql, (match, *short_params, CANDIDATES)).fetchall()
                seen = {r["id"] for r in name_rows}
                hits = [(r, 0) for r in name_rows] + [(r, 1) for r in body_rows if r["id"] not in seen]
            hits.sort(key=lambda h: (h[1], -h[0]["mtime"]))
        return [self._as_item(r, rank=(tier, -r["mtime"])) for r, tier in hits[:limit]]

    def excerpts(self, rowids: list[int], term: str) -> dict[int, str]:
        """A short window of text around the first match, cut inside SQLite."""
        # One lookup per row: FTS5 can't use "rowid IN (...)" and would scan every document.
        sql = (f"SELECT max(1, instr(lower(body), ?) - {EXCERPT_LEAD}) AS start, "
               f"substr(body, max(1, instr(lower(body), ?) - {EXCERPT_LEAD}), {EXCERPT_CHARS}) AS ex "
               "FROM files_fts WHERE rowid = ?")
        out = {}
        with self._rlock:
            for rowid in rowids:
                r = self.rconn.execute(sql, (term, term, rowid)).fetchone()
                if r:
                    out[rowid] = ("…" if r["start"] > 1 else "") + r["ex"]
        return out


class Database:
    """Personal items in one SQLite file, files spread over shard files."""

    def __init__(self, path: Path | str, shards: int = FILE_SHARDS):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = _connect(self.path)
        self.conn.executescript(ITEMS_SCHEMA)
        self.conn.commit()
        if self.path == ":memory:":
            shard_paths = [":memory:"] * shards
        else:
            p = Path(self.path)
            shard_paths = [str(p.with_name(f"{p.stem}-files-{i}{p.suffix}")) for i in range(shards)]
        self.shards = [FileShard(sp, i) for i, sp in enumerate(shard_paths)]
        self._migrate()

    def _migrate(self) -> None:
        # v1 kept files in the items table; they now live in shards and are
        # simply rescanned.
        if self.get_meta("schema", 1) < 2:
            with self._lock:
                self.conn.execute("DELETE FROM items WHERE kind='file'")
                self.conn.commit()
            self.set_meta("schema", 2)

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
            self.conn.commit()

    # ----------------------------------------------------------- file index
    def shard_for(self, path: str) -> FileShard:
        return self.shards[zlib.crc32(path.encode("utf-8", "surrogatepass")) % len(self.shards)]

    def _split_file_id(self, item_id: int) -> tuple[FileShard, int] | None:
        shard_no, rowid = divmod(item_id, FILE_ID_BASE)
        if 1 <= shard_no <= len(self.shards):
            return self.shards[shard_no - 1], rowid
        return None

    def file_index(self) -> dict[str, tuple[int, float, int]]:
        """{path: (id, mtime, size)} for every indexed file."""
        result: dict[str, tuple[int, float, int]] = {}
        for shard in self.shards:
            result.update(shard.known())
        return result

    def upsert_file(self, path: str, title: str, body: str, mtime: float, size: int) -> int:
        shard = self.shard_for(path)
        shard.upsert_many([(path, title, body, mtime, size)])
        return shard.known()[path][0]

    def delete_paths(self, paths: list[str]) -> None:
        groups: dict[int, list[str]] = {}
        for p in paths:
            groups.setdefault(self.shard_for(p).index, []).append(p)
        for idx, group in groups.items():
            self.shards[idx].delete_paths(group)

    # ----------------------------------------------------------------- items
    def add_item(self, kind: str, title: str, body: str = "", extra: dict | None = None,
                 secret: bytes | None = None) -> int:
        if kind not in KINDS or kind == "file":
            raise ValueError(f"unknown kind: {kind}")
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO items(kind, title, body, extra, secret, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (kind, title, body, json.dumps(extra or {}), secret, now, now),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def update_item(self, item_id: int, **fields: Any) -> None:
        allowed = {"title", "body", "extra", "secret"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"cannot update field: {key}")
            if key == "extra":
                value = json.dumps(value or {})
            sets.append(f"{key}=?")
            values.append(value)
        if not sets:
            return
        sets.append("updated_at=?")
        values.extend([time.time(), item_id])
        with self._lock:
            self.conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", values)
            self.conn.commit()

    def delete_item(self, item_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM items WHERE id=?", (item_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def get_item(self, item_id: int) -> dict | None:
        loc = self._split_file_id(item_id)
        if loc:
            return loc[0].get(loc[1])
        with self._lock:
            row = self.conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else None

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self.conn.execute("SELECT kind, COUNT(*) AS n FROM items GROUP BY kind").fetchall()
        result = {k: 0 for k in KINDS}
        result.update({r["kind"]: r["n"] for r in rows if r["kind"] != "file"})
        result["file"] = sum(shard.count() for shard in self.shards)
        return result

    # ---------------------------------------------------------------- search
    def search(self, query: str, kind: str | None = None, limit: int = 50) -> list[dict]:
        long_terms, short_terms = split_terms(query)
        if not long_terms and not short_terms:
            return self.recent(kind, limit)
        # Shards are queried one after another: each query is a few ms, and
        # threads would only fight over the GIL (measured ~3x slower).
        results: list[dict] = []
        if kind in (None, "file"):
            for shard in self.shards:
                results += shard.search(long_terms, short_terms, limit)
        if kind != "file":
            results += self._search_items(long_terms, short_terms, kind, limit)
        results.sort(key=lambda r: r["rank"])
        results = results[:limit]
        # Cut excerpts only for the rows we return.
        term = (long_terms or short_terms)[0].lower()
        wanted: dict[int, list[dict]] = {}
        for r in results:
            if r["kind"] == "file":
                shard, rowid = self._split_file_id(r["id"])
                wanted.setdefault(shard.index, []).append(r)
        for idx, rows in wanted.items():
            shard = self.shards[idx]
            ex = shard.excerpts([r["id"] % FILE_ID_BASE for r in rows], term)
            for r in rows:
                r["body"] = ex.get(r["id"] % FILE_ID_BASE, "")
        return results

    def _search_items(self, long_terms, short_terms, kind, limit) -> list[dict]:
        where, params = [], []
        if kind:
            where.append("items.kind = ?")
            params.append(kind)
        for term in short_terms:
            where.append("(items.title LIKE ? ESCAPE '\\' OR items.body LIKE ? ESCAPE '\\')")
            params.extend([_like(term), _like(term)])
        cond = (" AND " + " AND ".join(where)) if where else ""
        with self._lock:
            if long_terms:
                match = _match(long_terms)
                sql = ("SELECT items.* FROM items_fts JOIN items ON items.id = items_fts.rowid "
                       f"WHERE items_fts MATCH ?{cond} ORDER BY items.updated_at DESC LIMIT ?")
                title_rows = self.conn.execute(sql, (f"title : ({match})", *params, limit)).fetchall()
                all_rows = self.conn.execute(sql, (match, *params, limit)).fetchall()
                title_ids = {r["id"] for r in title_rows}
                hits = [(r, 0) for r in title_rows] + [(r, 1) for r in all_rows if r["id"] not in title_ids]
            else:
                rows = self.conn.execute(
                    f"SELECT * FROM items WHERE 1=1{cond} ORDER BY updated_at DESC LIMIT ?", (*params, limit)
                ).fetchall()
                first = short_terms[0].lower()
                hits = [(r, 0 if first in r["title"].lower() else 1) for r in rows]
        out = []
        for r, tier in hits:
            item = dict(r)
            item["rank"] = (tier, -r["updated_at"])
            out.append(item)
        return out

    def recent(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        if kind == "file":
            rows = []
            for shard in self.shards:
                with shard._rlock:
                    part = shard.rconn.execute(
                        "SELECT * FROM files ORDER BY mtime DESC LIMIT ?", (limit,)).fetchall()
                rows += [shard._as_item(r, rank=(0, -r["mtime"])) for r in part]
            rows.sort(key=lambda r: r["rank"])
            return rows[:limit]
        sql = "SELECT * FROM items"
        params: list[Any] = []
        if kind:
            sql += " WHERE kind=?"
            params.append(kind)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        for shard in self.shards:
            shard.wconn.close()
            if shard.rconn is not shard.wconn:
                shard.rconn.close()
        self.conn.close()
