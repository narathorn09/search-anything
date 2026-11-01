"""FastAPI application: one search API over files, notes, bookmarks and passwords."""

from __future__ import annotations

import hmac
import re
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .db import Database
from .extractors import MAX_TEXT_CHARS, SUPPORTED, is_plain_text_type
from .textview import LineIndex, LineIndexCache
from . import ocr
from .indexer import Indexer, ScanSettings
from .worker import ProcessIndexer
from .resources import CONTAINER, CPU_COUNT, PROFILES, ram_limits_mb
from .vault import Vault, VaultError, VaultLocked

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = ["localhost", "127.0.0.1"]


@dataclass
class Config:
    mode: Literal["local", "server"] = "local"
    data_dir: Path = Path("data")
    folders: list[str] = field(default_factory=list)
    password: str | None = None  # login password, required in server mode
    reindex_interval: int = 300
    auto_lock_seconds: int = 900
    allowed_hosts: list[str] | None = None
    https_only_cookie: bool = False
    scrypt_n: int = 2**15
    background_indexing: bool = True
    max_upload_mb: int = 200
    worker_process: bool = True  # scan in a separate low-priority process
    # Docker: map container paths back to the host paths the user knows,
    # e.g. [("/host/Documents", "/Users/me/Documents")].
    path_map: list[tuple[str, str]] = field(default_factory=list)
    can_open_files: bool = True  # False inside a container (no desktop to open files with)


# ----------------------------------------------------------------- schemas
class LoginIn(BaseModel):
    password: str


class MasterIn(BaseModel):
    master_password: str


class ItemIn(BaseModel):
    kind: Literal["note", "bookmark", "password"]
    title: str = Field(min_length=1, max_length=500)
    content: str = ""  # note text / bookmark description / password notes
    url: str = ""
    username: str = ""
    password: str | None = None  # plaintext secret; only for kind=password
    tags: list[str] = []


class FoldersIn(BaseModel):
    folders: list[str]


class ScanSettingsIn(BaseModel):
    profile: Literal["eco", "balanced", "fast"]
    auto: bool
    interval_minutes: int = Field(ge=1, le=24 * 60)
    ocr: bool = True
    ocr_images: bool = False
    ocr_max_pages: int = Field(default=100, ge=1, le=2000)


# ----------------------------------------------------------------- helpers
def build_body(kind: str, content: str, url: str, username: str, tags: list[str]) -> str:
    """Searchable text for an item. Never includes secrets."""
    parts = {
        "note": [content],
        "bookmark": [url, content],
        "password": [username, url, content],
    }[kind]
    if tags:
        parts.append(" ".join(f"#{t}" for t in tags))
    return "\n".join(p for p in parts if p)


def make_snippet(text: str, terms: list[str], width: int = 160) -> str:
    if not text:
        return ""
    lower = text.lower()
    positions = [lower.find(t.lower()) for t in terms]
    positions = [p for p in positions if p >= 0]
    if not positions:
        return text[:width].replace("\n", " ")
    pos = min(positions)
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    snippet = text[start:end].replace("\n", " ")
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def open_with_os(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def load_secret_key(data_dir: Path) -> str:
    key_file = data_dir / "session.key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return key


# --------------------------------------------------------------------- app
def create_app(config: Config) -> FastAPI:
    if config.mode == "server" and not config.password:
        raise ValueError("server mode requires a login password (SA_PASSWORD)")

    config.data_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = (config.data_dir / "uploads").resolve()
    upload_dir.mkdir(exist_ok=True)
    db = Database(config.data_dir / "search.db")

    user_folders = [str(Path(f).expanduser().resolve()) for f in config.folders]
    if config.mode == "local" and config.can_open_files:
        # Folders chosen in the UI are remembered; CLI folders are added on top.
        # (In a container the start script decides which folders are mounted.)
        user_folders = list(dict.fromkeys([*db.get_meta("folders", []), *user_folders]))
        db.set_meta("folders", user_folders)
    # The uploads folder is always indexed, in both modes.
    scan_settings = ScanSettings.from_dict(db.get_meta("scan_settings"), max(1, config.reindex_interval // 60))
    indexer_cls = ProcessIndexer if config.worker_process else Indexer
    indexer = indexer_cls(db, [*user_folders, str(upload_dir)], scan_settings)
    max_upload = config.max_upload_mb * 1024 * 1024

    def display_path(path: str | None) -> str | None:
        """Path as the user knows it (see Config.path_map, used in Docker)."""
        if not path:
            return path
        for inner, outer in config.path_map:
            inner = inner.rstrip("/")
            if path == inner or path.startswith(inner + "/"):
                rest = path[len(inner):]
                if re.match(r"^[A-Za-z]:\\", outer):  # Windows host path
                    rest = rest.replace("/", "\\")
                return outer.rstrip("/\\") + rest
        return path

    def is_upload(path: str | None) -> bool:
        return bool(path) and Path(path).parent == upload_dir
    vault = Vault(db, config.auto_lock_seconds, config.scrypt_n)

    app = FastAPI(title="Search Anything", docs_url=None, redoc_url=None)
    app.state.db, app.state.indexer, app.state.vault, app.state.config = db, indexer, vault, config

    app.add_middleware(
        SessionMiddleware,
        secret_key=load_secret_key(config.data_dir),
        session_cookie="sa_session",
        max_age=7 * 24 * 3600,
        same_site="strict",
        https_only=config.https_only_cookie,
    )
    allowed_hosts = config.allowed_hosts or (LOCAL_HOSTS if config.mode == "local" else ["*"])
    # In local mode this blocks DNS-rebinding attacks from malicious websites.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    if config.background_indexing:
        indexer.start_background()

    failed_logins: dict[str, list[float]] = {}

    def require_auth(request: Request) -> None:
        if config.mode == "server" and not request.session.get("auth"):
            raise HTTPException(401, "login required")

    def require_local() -> None:
        if config.mode != "local":
            raise HTTPException(403, "only available in local mode")

    def get_or_404(item_id: int):
        row = db.get_item(item_id)
        if row is None:
            raise HTTPException(404, "not found")
        return row

    def serialize(row: dict, terms: list[str] | None = None, full: bool = False) -> dict:
        extra = json.loads(row["extra"] or "{}")
        data = {
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "updated_at": row["updated_at"],
            "url": extra.get("url", ""),
            "username": extra.get("username", ""),
            "tags": extra.get("tags", []),
        }
        body = row.get("body") or ""
        if row["kind"] == "file":
            data["path"] = display_path(row["path"])
            data["size"] = row["size"]
            data["mtime"] = row["mtime"]
            data["uploaded"] = is_upload(row["path"])
        if terms is not None:
            data["snippet"] = make_snippet(body, terms)
        if full:
            data["content"] = extra.get("content", body) if row["kind"] != "file" else body[:20000]
        return data

    # ------------------------------------------------------------- auth
    @app.post("/api/login")
    def login(data: LoginIn, request: Request):
        if config.mode != "server":
            return {"ok": True}
        ip = request.client.host if request.client else "?"
        now = time.time()
        recent = [t for t in failed_logins.get(ip, []) if now - t < 300]
        if len(recent) >= 10:
            raise HTTPException(429, "too many attempts, try again later")
        if not hmac.compare_digest(data.password.encode(), (config.password or "").encode()):
            failed_logins[ip] = [*recent, now]
            time.sleep(0.5)
            raise HTTPException(401, "wrong password")
        failed_logins.pop(ip, None)
        request.session["auth"] = True
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request):
        request.session.clear()
        return {"ok": True}

    @app.get("/api/status")
    def status(request: Request):
        authed = config.mode == "local" or bool(request.session.get("auth"))
        result = {"mode": config.mode, "authenticated": authed}
        if authed:
            result.update(
                {
                    "vault": {"set_up": vault.is_set_up, "unlocked": vault.is_unlocked},
                    "counts": db.counts(),
                    "folders": [display_path(f) for f in indexer.folders if f != str(upload_dir)],
                    "can_edit_folders": config.mode == "local" and config.can_open_files,
                    "can_open_files": config.mode == "local" and config.can_open_files,
                    "in_container": not config.can_open_files,
                    "can_upload": True,
                    "max_upload_mb": config.max_upload_mb,
                    "indexing": indexer.status(),
                    "profiles": {
                        k: {"label": p.label, "max_cpu": p.max_cpu, "max_ram_mb": ram_limits_mb(p)[0],
                            "threads": p.extract_workers, "parallel_writes": p.write_parallel}
                        for k, p in PROFILES.items()
                    },
                    "cpu_count": CPU_COUNT,
                    "container": {"cpus": CONTAINER.cpus,
                                  "memory_mb": round(CONTAINER.memory_bytes / 1e6) if CONTAINER.memory_bytes else None},
                    "supported_formats": SUPPORTED,
                }
            )
        return result

    # ----------------------------------------------------------- search
    @app.get("/api/search", dependencies=[Depends(require_auth)])
    def search(q: str = "", kind: Literal["", "all", "file", "note", "bookmark", "password"] | None = None,
               limit: int = 50, offset: int = 0,
               sort: Literal["relevance", "newest", "oldest", "name", "name_desc", "largest", "type"] = "relevance"):
        """One page of results. ``total`` is None when not counted yet (ask /api/search/count)."""
        kind = kind or None if kind != "all" else None
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        terms = q.split()
        page = db.page(q, kind, sort, offset, limit)
        return {"query": q, "offset": offset, "total": page["total"], "approx": page["approx"],
                "has_more": page["has_more"], "results": [serialize(r, terms) for r in page["results"]]}

    @app.get("/api/search/count", dependencies=[Depends(require_auth)])
    def search_count(q: str = "", kind: Literal["", "all", "file", "note", "bookmark", "password"] | None = None,
                     sort: Literal["relevance", "newest", "oldest", "name", "name_desc", "largest", "type"] = "relevance"):
        """Total number of results. Bounded in time: ``approx`` means "at least"."""
        kind = kind or None if kind != "all" else None
        return db.count(q, kind, sort)

    # ------------------------------------------------------------ items
    @app.get("/api/items/{item_id}", dependencies=[Depends(require_auth)])
    def get_item(item_id: int):
        return serialize(get_or_404(item_id), full=True)

    def save_fields(data: ItemIn) -> dict:
        tags = [t.strip().lstrip("#") for t in data.tags if t.strip()]
        extra = {"content": data.content, "tags": tags}
        if data.kind in ("bookmark", "password"):
            extra["url"] = data.url
        if data.kind == "password":
            extra["username"] = data.username
        return {
            "title": data.title.strip(),
            "body": build_body(data.kind, data.content, data.url, data.username, tags),
            "extra": extra,
        }

    @app.post("/api/items", dependencies=[Depends(require_auth)])
    def create_item(data: ItemIn):
        secret = None
        if data.kind == "password":
            try:
                secret = vault.encrypt(data.password or "")
            except VaultLocked:
                raise HTTPException(423, "vault is locked")
        fields = save_fields(data)
        item_id = db.add_item(data.kind, fields["title"], fields["body"], fields["extra"], secret)
        db.invalidate()
        return serialize(db.get_item(item_id), full=True)

    @app.put("/api/items/{item_id}", dependencies=[Depends(require_auth)])
    def update_item(item_id: int, data: ItemIn):
        row = get_or_404(item_id)
        if row["kind"] != data.kind or row["kind"] == "file":
            raise HTTPException(400, "cannot change this item")
        fields = save_fields(data)
        if data.kind == "password" and data.password is not None:
            try:
                fields["secret"] = vault.encrypt(data.password)
            except VaultLocked:
                raise HTTPException(423, "vault is locked")
        db.update_item(item_id, **fields)
        db.invalidate()
        return serialize(db.get_item(item_id), full=True)

    @app.delete("/api/items/{item_id}", dependencies=[Depends(require_auth)])
    def delete_item(item_id: int):
        row = get_or_404(item_id)
        if row["kind"] == "file":
            # Only files uploaded through the app can be deleted from here.
            if not is_upload(row["path"]):
                raise HTTPException(400, "only uploaded files can be deleted here")
            Path(row["path"]).unlink(missing_ok=True)
            db.delete_paths([row["path"]])
            db.invalidate()
            return {"ok": True}
        db.delete_item(item_id)
        db.invalidate()
        return {"ok": True}

    text_cache = LineIndexCache()

    def open_text(item_id: int) -> tuple[dict, LineIndex, str]:
        """The text behind the viewer, without loading big files into memory.

        Plain-text/code files are read from disk (line numbers match the real
        file, any size). Other formats (PDF, Office …) use the text extracted
        into the index."""
        row = get_or_404(item_id)
        if row["kind"] not in ("file", "note"):
            raise HTTPException(400, "nothing to show for this item")
        if row["kind"] == "note":
            return row, LineIndex(text=json.loads(row["extra"] or "{}").get("content", "")), "note"
        path = Path(row["path"])
        try:
            if is_plain_text_type(path) and path.is_file():
                return row, text_cache.for_file(path), "disk"
        except (OSError, ValueError):
            pass
        full = db.get_item(item_id, max_chars=MAX_TEXT_CHARS) or {}
        return row, LineIndex(text=full.get("body") or ""), "index"

    @app.get("/api/items/{item_id}/text", dependencies=[Depends(require_auth)])
    def text_info(item_id: int):
        row, idx, source = open_text(item_id)
        return {"id": row["id"], "kind": row["kind"], "title": row["title"], "path": display_path(row.get("path")),
                "source": source, "total_lines": idx.total_lines, "size": row.get("size"), "encoding": idx.encoding}

    @app.get("/api/items/{item_id}/text/lines", dependencies=[Depends(require_auth)])
    def text_lines(item_id: int, start: int = 0, count: int = Query(200, ge=1, le=2000)):
        """Lines [start, start+count) — the viewer asks only for what is on screen."""
        _, idx, _ = open_text(item_id)
        return {"start": start, "lines": idx.lines(start, count)}

    @app.get("/api/items/{item_id}/text/find", dependencies=[Depends(require_auth)])
    def text_find(item_id: int, q: str = "", max: int = Query(2000, ge=1, le=10000)):
        """Lines that contain the words; streams through the file once."""
        _, idx, _ = open_text(item_id)
        return idx.find(q.split(), max)

    @app.post("/api/items/{item_id}/reveal", dependencies=[Depends(require_auth)])
    def reveal(item_id: int):
        row = get_or_404(item_id)
        if row["kind"] != "password" or row["secret"] is None:
            raise HTTPException(400, "not a password item")
        try:
            return {"password": vault.decrypt(row["secret"])}
        except VaultLocked:
            raise HTTPException(423, "vault is locked")
        except VaultError as exc:
            raise HTTPException(500, str(exc))

    # ------------------------------------------------------------ vault
    @app.post("/api/vault/setup", dependencies=[Depends(require_auth)])
    def vault_setup(data: MasterIn):
        try:
            vault.setup(data.master_password)
        except VaultError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True}

    @app.post("/api/vault/unlock", dependencies=[Depends(require_auth)])
    def vault_unlock(data: MasterIn):
        try:
            ok = vault.unlock(data.master_password)
        except VaultError as exc:
            raise HTTPException(400, str(exc))
        if not ok:
            time.sleep(0.5)
            raise HTTPException(401, "wrong master password")
        return {"ok": True}

    @app.post("/api/vault/lock", dependencies=[Depends(require_auth)])
    def vault_lock():
        vault.lock()
        return {"ok": True}

    # ------------------------------------------------------------ files
    @app.post("/api/scan/start", dependencies=[Depends(require_auth)])
    @app.post("/api/reindex", dependencies=[Depends(require_auth)])  # old name
    def scan_start():
        indexer.trigger()
        return {"ok": True}

    @app.post("/api/scan/stop", dependencies=[Depends(require_auth)])
    def scan_stop():
        return {"stopped": indexer.stop()}

    @app.delete("/api/scan/skipped", dependencies=[Depends(require_auth)])
    def scan_clear_skipped():
        """Forget files that crashed the scanner, so the next scan tries them again."""
        cleared = indexer.clear_skipped() if isinstance(indexer, ProcessIndexer) else 0
        return {"cleared": cleared}

    @app.put("/api/scan/settings", dependencies=[Depends(require_auth)])
    def scan_settings_update(data: ScanSettingsIn):
        settings = ScanSettings.from_dict(data.model_dump())
        before = indexer.settings
        db.set_meta("scan_settings", data.model_dump())
        indexer.update_settings(settings)
        more_ocr = settings.ocr and (not before.ocr or (settings.ocr_images and not before.ocr_images)
                                     or settings.ocr_max_pages > before.ocr_max_pages)
        if more_ocr and ocr.engine().available and not indexer.running:
            indexer.trigger()  # read the newly included files now (unchanged files are skipped)
        return indexer.status()["settings"]

    @app.put("/api/folders", dependencies=[Depends(require_auth), Depends(require_local)])
    def set_folders(data: FoldersIn):
        cleaned = [f.strip() for f in data.folders if f.strip()]
        missing = [f for f in cleaned if not Path(f).expanduser().is_dir()]
        if missing:
            raise HTTPException(400, f"folder not found: {', '.join(missing)}")
        resolved = [str(Path(f).expanduser().resolve()) for f in cleaned]
        indexer.set_folders([*resolved, str(upload_dir)])
        db.set_meta("folders", resolved)
        indexer.trigger()
        return {"folders": resolved}

    def file_row(item_id: int):
        row = get_or_404(item_id)
        if row["kind"] != "file" or not Path(row["path"]).is_file():
            raise HTTPException(404, "file not found")
        return row

    @app.post(
        "/api/files/{item_id}/open", dependencies=[Depends(require_auth), Depends(require_local)]
    )
    def open_file(item_id: int):
        if not config.can_open_files:
            raise HTTPException(403, "running in a container: download the file instead")
        open_with_os(file_row(item_id)["path"])
        return {"ok": True}

    @app.get("/api/files/{item_id}/download", dependencies=[Depends(require_auth)])
    def download_file(item_id: int):
        row = file_row(item_id)
        return FileResponse(row["path"], filename=row["title"])

    @app.post("/api/upload", dependencies=[Depends(require_auth)])
    async def upload(files: list[UploadFile]):
        saved: list[Path] = []
        try:
            for f in files:
                # Keep only the base name (handles both / and \\), drop leading dots.
                raw = (f.filename or "upload").replace("\\", "/").split("/")[-1]
                name = raw.lstrip(".").strip() or "upload"
                target = upload_dir / name
                stem, suffix, n = target.stem, target.suffix, 1
                while target.exists():
                    target = upload_dir / f"{stem} ({n}){suffix}"
                    n += 1
                written = 0
                with target.open("wb") as out:
                    saved.append(target)
                    while chunk := await f.read(1024 * 1024):
                        written += len(chunk)
                        if written > max_upload:
                            raise HTTPException(413, f"{name}: larger than {config.max_upload_mb} MB")
                        out.write(chunk)
        except BaseException:
            for path in saved:  # don't leave half-written files behind
                path.unlink(missing_ok=True)
            raise
        # Index right away so the files are searchable when the request returns.
        ids = await run_in_threadpool(indexer.index_paths, [str(p) for p in saved])
        db.invalidate()
        if indexer.settings.ocr and any(ocr.is_candidate(str(p), indexer.settings.ocr_images) for p in saved):
            indexer.trigger()  # scanned uploads are read with OCR in the background
        return {"saved": [p.name for p in saved], "items": [serialize(db.get_item(i)) for i in ids]}

    # ------------------------------------------------------------- ui
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
