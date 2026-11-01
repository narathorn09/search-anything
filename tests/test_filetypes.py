"""Filter results by file type (PDF, Word, Excel …)."""

import time

from fastapi.testclient import TestClient

from cahon import filetypes
from cahon.app import Config, create_app
from cahon.db import Database
from cahon.indexer import Indexer, ScanSettings


def test_groups():
    t = filetypes.type_of
    assert [t(n) for n in ("a.PDF", "b.docx", "c.doc", "d.xls", "e.csv", "f.pptx", "g.jpeg", "h.py",
                           "Makefile", "i.eml", "j.zip", "k.mp4", "l.dwg", "noext")] == [
        "pdf", "word", "word", "excel", "excel", "slides", "image", "text", "text", "email", "archive", "media",
        "other", "other"]
    assert filetypes.parse("pdf,word,nonsense") == {"pdf", "word"}


def make(tmp_path, names):
    docs = tmp_path / "docs"
    docs.mkdir()
    for i, name in enumerate(names):
        (docs / name).write_text(f"สัญญา ฉบับที่ {i}")
        t = 1_700_000_000 + i
        import os
        os.utime(docs / name, (t, t))
    db = Database(tmp_path / "s.db")
    Indexer(db, [str(docs)], ScanSettings(ocr=False)).run()
    db.add_item("note", "โน้ต สัญญา")
    return db


NAMES = ["สัญญา-a.pdf", "สัญญา-b.pdf", "สัญญา-c.pdf", "สัญญา-d.docx", "สัญญา-e.xlsx", "สัญญา-f.csv", "สัญญา-g.txt",
         "สัญญา-h.dwg", "สัญญา-i.jpg"]


def test_filter_with_and_without_a_query(tmp_path):
    db = make(tmp_path, NAMES)
    titles = lambda page: [r["title"] for r in page["results"]]
    # Nothing typed: newest files of the chosen types.
    p = db.page("", None, "relevance", 0, 50, frozenset({"pdf"}))
    assert titles(p) == ["สัญญา-c.pdf", "สัญญา-b.pdf", "สัญญา-a.pdf"] and p["total"] == 3
    # A query: matches, files only (the note also matches "สัญญา" but has no type).
    p = db.page("สัญญา", None, "relevance", 0, 50, frozenset({"excel", "word"}))
    assert sorted(titles(p)) == ["สัญญา-d.docx", "สัญญา-e.xlsx", "สัญญา-f.csv"] and p["total"] == 3
    assert db.count("สัญญา", None, "relevance", frozenset({"excel", "word"})) == {"total": 3, "approx": False}
    # Other kinds have no files.
    assert db.page("สัญญา", "note", "relevance", 0, 50, frozenset({"pdf"}))["total"] == 0
    # Sorting and paging still work with the filter.
    p1 = db.page("", "file", "name_desc", 0, 2, frozenset({"pdf", "other"}))
    p2 = db.page("", "file", "name_desc", 2, 2, frozenset({"pdf", "other"}))
    assert titles(p1) == ["สัญญา-h.dwg", "สัญญา-c.pdf"] and titles(p2) == ["สัญญา-b.pdf", "สัญญา-a.pdf"]
    assert p2["has_more"] is False


def test_facets(tmp_path):
    db = make(tmp_path, NAMES)
    assert db.facets("")["counts"] == {"pdf": 3, "word": 1, "excel": 2, "image": 1, "text": 1, "other": 1}
    assert db.facets("สัญญา")["counts"]["pdf"] == 3
    assert db.facets("", "note")["counts"] == {}


def test_api(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for n in ("รายงาน-x.pdf", "รายงาน-y.docx", "รายงาน-z.txt"):
        (docs / n).write_text("รายงาน")
    c = TestClient(create_app(Config(data_dir=tmp_path / "data", folders=[str(docs)], allowed_hosts=["testserver"],
                                     background_indexing=False)))
    c.post("/api/scan/start")
    for _ in range(100):
        if not c.get("/api/status").json()["indexing"]["running"] and c.get("/api/status").json()["counts"]["file"] == 3:
            break
        time.sleep(0.1)
    r = c.get("/api/search", params={"q": "รายงาน", "types": "pdf,word"}).json()
    assert sorted(x["title"] for x in r["results"]) == ["รายงาน-x.pdf", "รายงาน-y.docx"] and r["total"] == 2
    f = c.get("/api/search/facets", params={"q": "รายงาน"}).json()
    assert f["counts"] == {"pdf": 1, "word": 1, "text": 1} and f["order"][0] == "pdf" and f["labels"]["word"] == "Word"
    assert c.get("/api/search/count", params={"q": "", "types": "text"}).json()["total"] == 1
