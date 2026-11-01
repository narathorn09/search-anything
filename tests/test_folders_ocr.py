"""Home screen folder panel, choosing folders, and OCR on request."""

import time

import pytest
from fastapi.testclient import TestClient

from cahon import ocr
from cahon.app import Config, create_app
from tests.test_ocr import needs_tesseract, scanned_pdf


def client_for(tmp_path, folders, **kw):
    c = TestClient(create_app(Config(data_dir=tmp_path / "data", folders=[str(f) for f in folders],
                                     allowed_hosts=["testserver"], background_indexing=False, **kw)))
    return c


def wait_scan(c, files: int):
    for _ in range(200):
        s = c.get("/api/status").json()
        if not s["indexing"]["running"] and s["counts"]["file"] >= files:
            return s
        time.sleep(0.1)
    raise AssertionError("scan did not finish")


def test_folder_list_counts_and_editing(tmp_path):
    a, b = tmp_path / "งาน", tmp_path / "ส่วนตัว"
    (a / "sub").mkdir(parents=True)
    b.mkdir()
    for p in (a / "1.txt", a / "sub" / "2.txt", b / "3.txt"):
        p.write_text("hello")
    (tmp_path / "งานอื่น").mkdir()  # same prefix, not inside "งาน"
    (tmp_path / "งานอื่น" / "x.txt").write_text("x")
    c = client_for(tmp_path, [a, b, tmp_path / "งานอื่น"])
    c.post("/api/scan/start")
    wait_scan(c, 4)
    r = c.get("/api/folders").json()
    assert [(f["name"], f["files"], f["scanning"]) for f in r["folders"]] == [
        ("งาน", 2, False), ("ส่วนตัว", 1, False), ("งานอื่น", 1, False)]
    assert r["can_edit"] is True and r["can_pick"] is False
    # Browser mode has no system folder window: the app shows its own.
    assert c.post("/api/folders/pick").status_code == 501
    # Removing a folder: its files leave the index at the next scan.
    c.put("/api/folders", json={"folders": [str(a)]})
    wait_scan(c, 0)
    for _ in range(100):
        if c.get("/api/status").json()["counts"]["file"] == 2:
            break
        time.sleep(0.1)
    assert [f["name"] for f in c.get("/api/folders").json()["folders"]] == ["งาน"]
    assert c.get("/api/status").json()["counts"]["file"] == 2


def test_browse_lists_folder_names_only(tmp_path):
    root = tmp_path / "root"
    for d in ("B", "a", ".hidden"):
        (root / d).mkdir(parents=True)
    (root / "file.txt").write_text("not listed")
    c = client_for(tmp_path, [])
    r = c.get("/api/folders/browse", params={"path": str(root)}).json()
    assert [d["name"] for d in r["dirs"]] == ["a", "B"]
    assert r["path"] == str(root) and r["parent"] == str(tmp_path) and r["roots"][0]["name"] == "Home"
    assert c.get("/api/folders/browse", params={"path": str(root / "nope")}).status_code == 400


def test_server_mode_cannot_browse_or_change_folders(tmp_path):
    c = client_for(tmp_path, [], mode="server", password="pw-123456")
    c.post("/api/login", json={"password": "pw-123456"})
    assert c.get("/api/folders").json()["can_edit"] is False
    assert c.get("/api/folders/browse").status_code == 403
    assert c.post("/api/folders/pick").status_code == 403


@needs_tesseract
def test_force_reads_pages_that_have_a_text_layer(tmp_path, monkeypatch):
    pdf = scanned_pdf(tmp_path / "s.pdf", ["INVOICE 4417 PAID"])
    monkeypatch.setattr(ocr, "TEXT_PAGE_CHARS", 0)  # every page now counts as "has text"
    reader = ocr.Reader(ocr.engine())
    assert reader.read(str(pdf)) == ("", 0)
    text, pages = reader.read(str(pdf), force=True)
    assert pages == 1 and "4417" in text


@needs_tesseract
def test_ocr_on_request(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    scanned_pdf(docs / "scan.pdf", ["INVOICE 4417 PAID"])
    (docs / "note.txt").write_text("plain")
    c = client_for(tmp_path, [docs])
    settings = c.get("/api/status").json()["indexing"]["settings"]
    c.put("/api/scan/settings", json={**settings, "ocr": False, "auto": False})
    c.post("/api/scan/start")
    wait_scan(c, 2)
    assert c.get("/api/search", params={"q": "4417"}).json()["results"] == []
    item = c.get("/api/search", params={"q": "scan"}).json()["results"][0]
    note = c.get("/api/search", params={"q": "note"}).json()["results"][0]
    assert c.post(f"/api/files/{note['id']}/ocr").status_code == 400  # not a PDF or picture
    assert c.post(f"/api/files/{item['id']}/ocr").json()["state"] == "running"
    for _ in range(300):
        job = c.get(f"/api/files/{item['id']}/ocr").json()
        if job["state"] != "running":
            break
        time.sleep(0.1)
    assert job["state"] == "done" and job["chars"] > 0 and job["pages"] == 1
    hits = c.get("/api/search", params={"q": "4417"}).json()["results"]
    assert [h["id"] for h in hits] == [item["id"]]
