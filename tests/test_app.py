import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from search_anything.app import Config, create_app
from search_anything.db import Database
from search_anything.indexer import Indexer

FAST_SCRYPT = 2**10  # keep tests fast; production uses 2**15


def make_client(tmp_path: Path, **kw) -> TestClient:
    config = Config(
        data_dir=tmp_path / "data",
        allowed_hosts=["testserver"],
        scrypt_n=FAST_SCRYPT,
        background_indexing=False,
        **kw,
    )
    return TestClient(create_app(config))


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    (root / "sub").mkdir(parents=True)
    (root / "สัญญาเช่าบ้าน.txt").write_text("ค่าเช่าเดือนละ 8000 บาท จ่ายทุกวันที่ 5", encoding="utf-8")
    (root / "sub" / "invoice-2026.md").write_text("Invoice for ACME Corp\nTotal: 1200 USD")
    (root / "photo.jpg").write_bytes(b"\xff\xd8\xff\x00binary")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "skip.txt").write_text("ACME should not be indexed here")
    return root


def ids(resp) -> list[str]:
    return [r["title"] for r in resp.json()["results"]]


# ------------------------------------------------------------------ indexer
def test_indexer_names_content_thai_and_incremental(tmp_path, docs):
    db = Database(tmp_path / "t.db")
    indexer = Indexer(db, [str(docs)])
    stats = indexer.run()
    assert stats.added_or_updated == 3  # node_modules skipped

    assert [r["title"] for r in db.search("ACME")] == ["invoice-2026.md"]
    assert [r["title"] for r in db.search("ค่าเช่า")] == ["สัญญาเช่าบ้าน.txt"]  # Thai content
    assert [r["title"] for r in db.search("สัญญา")] == ["สัญญาเช่าบ้าน.txt"]  # Thai file name
    assert [r["title"] for r in db.search("photo")] == ["photo.jpg"]  # name-only file
    assert [r["title"] for r in db.search("sub")] == ["invoice-2026.md"]  # folder in path

    # Nothing changed -> nothing re-read.
    assert indexer.run().added_or_updated == 0

    # Edit, delete.
    (docs / "sub" / "invoice-2026.md").write_text("Paid in full by Globex")
    (docs / "photo.jpg").unlink()
    stats = indexer.run()
    assert stats.added_or_updated == 1 and stats.removed == 1
    assert db.search("ACME") == []
    assert [r["title"] for r in db.search("Globex")] == ["invoice-2026.md"]


def test_search_short_terms_and_special_chars(tmp_path):
    db = Database(":memory:")
    db.add_item("note", "Wi-Fi บ้าน", "ssid: home_5g")
    db.add_item("note", "C++ notes", 'quote " and * stars')
    assert [r["title"] for r in db.search("wi")] == ["Wi-Fi บ้าน"]  # < 3 chars uses LIKE
    assert [r["title"] for r in db.search("C++")] == ["C++ notes"]
    assert [r["title"] for r in db.search('" and *')] == ["C++ notes"]
    assert [r["title"] for r in db.search("home_5g บ้")] == ["Wi-Fi บ้าน"]  # mixed long + short
    assert db.search("%") == []


# ---------------------------------------------------------------- local mode
def test_notes_bookmarks_crud_and_search(tmp_path):
    c = make_client(tmp_path)
    note = c.post("/api/items", json={"kind": "note", "title": "เลขบัญชี", "content": "กสิกร 123-4-56789", "tags": ["bank"]}).json()
    c.post("/api/items", json={"kind": "bookmark", "title": "Docs", "url": "https://fastapi.tiangolo.com", "content": "python web"})

    assert ids(c.get("/api/search", params={"q": "กสิกร"})) == ["เลขบัญชี"]
    assert ids(c.get("/api/search", params={"q": "#bank"})) == ["เลขบัญชี"]
    assert ids(c.get("/api/search", params={"q": "tiangolo"})) == ["Docs"]
    assert ids(c.get("/api/search", params={"q": "python", "kind": "note"})) == []

    c.put(f"/api/items/{note['id']}", json={"kind": "note", "title": "เลขบัญชี", "content": "SCB 999"})
    assert ids(c.get("/api/search", params={"q": "กสิกร"})) == []
    assert c.get(f"/api/items/{note['id']}").json()["content"] == "SCB 999"

    assert c.delete(f"/api/items/{note['id']}").json() == {"ok": True}
    assert c.get(f"/api/items/{note['id']}").status_code == 404


def test_password_vault(tmp_path):
    c = make_client(tmp_path)
    item = {"kind": "password", "title": "Gmail", "username": "me@example.com", "url": "mail.google.com", "password": "s3cret-pass!"}
    assert c.post("/api/items", json=item).status_code == 423  # no vault yet

    assert c.post("/api/vault/setup", json={"master_password": "short"}).status_code == 400
    assert c.post("/api/vault/setup", json={"master_password": "correct horse"}).status_code == 200
    created = c.post("/api/items", json=item).json()
    pid = created["id"]

    # Searchable by metadata, never by the secret, and the secret is not in any response.
    assert ids(c.get("/api/search", params={"q": "gmail"})) == ["Gmail"]
    assert ids(c.get("/api/search", params={"q": "example.com"})) == ["Gmail"]
    assert ids(c.get("/api/search", params={"q": "s3cret"})) == []
    assert "s3cret" not in c.get(f"/api/items/{pid}").text
    assert "s3cret" not in c.get("/api/search", params={"q": "gmail"}).text

    # Not stored in plaintext on disk.
    raw = (tmp_path / "data" / "search.db").read_bytes() + (tmp_path / "data" / "search.db-wal").read_bytes()
    assert b"s3cret-pass!" not in raw

    assert c.post(f"/api/items/{pid}/reveal").json() == {"password": "s3cret-pass!"}
    c.post("/api/vault/lock")
    assert c.post(f"/api/items/{pid}/reveal").status_code == 423
    assert c.post("/api/vault/unlock", json={"master_password": "wrong one"}).status_code == 401
    assert c.post("/api/vault/unlock", json={"master_password": "correct horse"}).status_code == 200

    # Update without a new password keeps the old one.
    c.put(f"/api/items/{pid}", json={**item, "password": None, "title": "Gmail personal"})
    assert c.post(f"/api/items/{pid}/reveal").json() == {"password": "s3cret-pass!"}


def test_local_mode_folders_and_host_check(tmp_path, docs):
    c = make_client(tmp_path)
    assert c.put("/api/folders", json={"folders": [str(tmp_path / "nope")]}).status_code == 400
    assert c.put("/api/folders", json={"folders": [str(docs)]}).status_code == 200
    c.app.state.indexer.run()
    assert ids(c.get("/api/search", params={"q": "ACME"})) == ["invoice-2026.md"]
    assert c.post("/api/upload", files={"files": ("a.txt", b"x")}).status_code == 403

    # Folders are remembered across restarts.
    c2 = make_client(tmp_path)
    assert c2.get("/api/status").json()["folders"] == [str(docs.resolve())]

    # Requests with a foreign Host header (DNS rebinding) are rejected.
    assert c.get("/api/status", headers={"host": "evil.example"}).status_code == 400


# --------------------------------------------------------------- server mode
def test_server_mode_requires_login_and_supports_upload(tmp_path):
    with pytest.raises(ValueError):
        make_client(tmp_path, mode="server")

    c = make_client(tmp_path, mode="server", password="hunter22")
    assert c.get("/api/status").json() == {"mode": "server", "authenticated": False}
    assert c.get("/api/search", params={"q": "x"}).status_code == 401
    assert c.post("/api/items", json={"kind": "note", "title": "x"}).status_code == 401
    assert c.put("/api/folders", json={"folders": []}).status_code in (401, 403)

    assert c.post("/api/login", json={"password": "nope"}).status_code == 401
    assert c.post("/api/login", json={"password": "hunter22"}).status_code == 200
    assert c.get("/api/status").json()["authenticated"] is True

    r = c.post("/api/upload", files=[("files", ("../../ไฟล์ทดสอบ.txt", "รายงานประจำปี".encode())), ("files", ("ไฟล์ทดสอบ.txt", b"dup"))])
    assert r.json()["saved"] == ["ไฟล์ทดสอบ.txt", "ไฟล์ทดสอบ (1).txt"]  # no path traversal, no overwrite
    c.app.state.indexer.run()
    results = c.get("/api/search", params={"q": "รายงาน"}).json()["results"]
    assert [r["title"] for r in results] == ["ไฟล์ทดสอบ.txt"]
    dl = c.get(f"/api/files/{results[0]['id']}/download")
    assert dl.content == "รายงานประจำปี".encode()
    assert c.post(f"/api/files/{results[0]['id']}/open").status_code == 403

    c.post("/api/logout")
    assert c.get("/api/search").status_code == 401


def test_ui_served(tmp_path):
    c = make_client(tmp_path)
    assert "Search Anything" in c.get("/").text
    assert c.get("/static/app.js").status_code == 200


def test_trigger_during_scan_is_not_dropped(tmp_path, docs):
    db = Database(tmp_path / "t.db")
    indexer = Indexer(db, [str(docs)])
    with indexer._run_lock:  # simulate a scan in progress
        indexer.trigger()
        indexer.trigger()  # coalesced with the queued one
        (docs / "late.txt").write_text("zebracorn")
    # The queued background scan must run after the current one finishes.
    deadline = time.time() + 5
    while not db.search("zebracorn") and time.time() < deadline:
        time.sleep(0.05)
    assert [r["title"] for r in db.search("zebracorn")] == ["late.txt"]
