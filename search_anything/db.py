"""SQLite storage with an FTS5 trigram index.

The trigram tokenizer matches any substring of 3+ characters, which works for
Thai (no spaces between words) as well as English, file names and URLs.
Shorter query terms fall back to LIKE.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

KINDS = ("file", "note", "bookmark", "password")

SCHEMA = """
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


class Database:
    """Thread-safe wrapper around a single SQLite connection."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

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

    # ----------------------------------------------------------------- items
    def add_item(
        self,
        kind: str,
        title: str,
        body: str = "",
        extra: dict | None = None,
        secret: bytes | None = None,
        path: str | None = None,
        mtime: float | None = None,
        size: int | None = None,
    ) -> int:
        if kind not in KINDS:
            raise ValueError(f"unknown kind: {kind}")
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO items(kind, title, body, extra, secret, path, mtime, size,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (kind, title, body, json.dumps(extra or {}), secret, path, mtime, size, now, now),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def update_item(self, item_id: int, **fields: Any) -> None:
        allowed = {"title", "body", "extra", "secret", "mtime", "size"}
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

    def get_item(self, item_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()

    def file_index(self) -> dict[str, tuple[int, float, int]]:
        """Return {path: (id, mtime, size)} for every indexed file."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, path, mtime, size FROM items WHERE kind='file'"
            ).fetchall()
        return {r["path"]: (r["id"], r["mtime"], r["size"]) for r in rows}

    def upsert_file(self, path: str, title: str, body: str, mtime: float, size: int) -> int:
        with self._lock:
            row = self.conn.execute("SELECT id FROM items WHERE path=?", (path,)).fetchone()
            if row:
                self.update_item(row["id"], title=title, body=body, mtime=mtime, size=size)
                return int(row["id"])
            return self.add_item("file", title, body, path=path, mtime=mtime, size=size)

    def delete_paths(self, paths: list[str]) -> None:
        with self._lock:
            self.conn.executemany("DELETE FROM items WHERE path=?", [(p,) for p in paths])
            self.conn.commit()

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self.conn.execute("SELECT kind, COUNT(*) AS n FROM items GROUP BY kind").fetchall()
        result = {k: 0 for k in KINDS}
        result.update({r["kind"]: r["n"] for r in rows})
        return result

    # ---------------------------------------------------------------- search
    def search(self, query: str, kind: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        terms = [t for t in query.split() if t]
        if not terms:
            return self.recent(kind, limit)

        long_terms = [t for t in terms if len(t) >= 3]
        short_terms = [t for t in terms if len(t) < 3]

        where, params = [], []
        if kind:
            where.append("items.kind = ?")
            params.append(kind)
        for term in short_terms:
            esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("(items.title LIKE ? ESCAPE '\\' OR items.body LIKE ? ESCAPE '\\')")
            params.extend([f"%{esc}%", f"%{esc}%"])

        if long_terms:
            # Quote each term so FTS syntax characters are treated literally.
            match = " AND ".join('"' + t.replace('"', '""') + '"' for t in long_terms)
            sql = (
                "SELECT items.*, bm25(items_fts, 10.0, 1.0) AS rank FROM items_fts "
                "JOIN items ON items.id = items_fts.rowid WHERE items_fts MATCH ?"
            )
            params.insert(0, match)
            if where:
                sql += " AND " + " AND ".join(where)
            sql += " ORDER BY rank LIMIT ?"
        else:
            sql = "SELECT items.*, 0 AS rank FROM items"
            if where:
                sql += " WHERE " + " AND ".join(where)
            # Prefer title matches, then most recently updated.
            sql += " ORDER BY (items.title LIKE ? ESCAPE '\\') DESC, items.updated_at DESC LIMIT ?"
            esc = short_terms[0].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{esc}%")
        params.append(limit)

        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def recent(self, kind: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        sql = "SELECT items.*, 0 AS rank FROM items"
        params: list[Any] = []
        if kind:
            sql += " WHERE kind=?"
            params.append(kind)
        else:
            # Files can number in the thousands; show personal items first.
            sql += " WHERE kind != 'file'"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return self.conn.execute(sql, params).fetchall()
