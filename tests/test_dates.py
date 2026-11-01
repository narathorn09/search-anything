"""Filter results by when they were last changed (date range)."""

import os
import time

from fastapi.testclient import TestClient

from cahon.app import Config, create_app
from cahon.db import Database
from cahon.indexer import Indexer, ScanSettings

DAY = 86400
NOW = time.time()


def make(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    # name -> age in days
    for name, age in {"รายงาน-วันนี้.pdf": 0, "รายงาน-สัปดาห์.docx": 5, "รายงาน-เดือน.pdf": 20, "รายงาน-เก่า.txt": 400}.items():
        (docs / name).write_text("รายงาน")
        t = NOW - age * DAY
        os.utime(docs / name, (t, t))
    db = Database(tmp_path / "s.db")
    Indexer(db, [str(docs)], ScanSettings(ocr=False)).run()
    db.add_item("note", "รายงาน โน้ตใหม่")  # changed now
    return db


def titles(page):
    return [r["title"] for r in page["results"]]


def test_date_range_without_and_with_a_query(tmp_path):
    db = make(tmp_path)
    week = NOW - 7 * DAY
    # Nothing typed: newest first, files and personal items together.
    p = db.page("", None, "relevance", 0, 50, since=week)
    assert set(titles(p)) == {"รายงาน-วันนี้.pdf", "รายงาน-สัปดาห์.docx", "รายงาน โน้ตใหม่"} and p["total"] == 3
    # A query, and an end date (exclusive).
    p = db.page("รายงาน", "file", "relevance", 0, 50, since=NOW - 30 * DAY, until=NOW - 2 * DAY)
    assert set(titles(p)) == {"รายงาน-สัปดาห์.docx", "รายงาน-เดือน.pdf"}
    assert db.count("รายงาน", "file", "relevance", since=NOW - 30 * DAY, until=NOW - 2 * DAY)["total"] == 2
    # Only an end date: everything older.
    assert titles(db.page("", "file", "newest", 0, 50, until=NOW - 100 * DAY)) == ["รายงาน-เก่า.txt"]
    # Personal items alone.
    assert titles(db.page("", "note", "relevance", 0, 50, since=week)) == ["รายงาน โน้ตใหม่"]
    assert db.page("", "note", "relevance", 0, 50, until=week)["total"] == 0


def test_dates_with_types_sort_and_facets(tmp_path):
    db = make(tmp_path)
    since = NOW - 30 * DAY
    p = db.page("รายงาน", None, "name", 0, 50, frozenset({"pdf"}), since=since)
    assert titles(p) == ["รายงาน-วันนี้.pdf", "รายงาน-เดือน.pdf"]
    # Paging over a date-filtered list.
    p1 = db.page("", None, "newest", 0, 2, since=since)
    p2 = db.page("", None, "newest", 2, 2, since=since)
    assert len(titles(p1) + titles(p2)) == 4 and p2["has_more"] is False
    # Type counts follow the date range, with and without words.
    assert db.facets("", None, since=NOW - 7 * DAY)["counts"] == {"pdf": 1, "word": 1}
    assert db.facets("รายงาน", None, since=since)["counts"] == {"pdf": 2, "word": 1}
    assert db.facets("", None)["counts"] == {"pdf": 2, "word": 1, "text": 1}


def test_api(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, age in {"รายงาน-x.pdf": 1, "รายงาน-y.docx": 3, "รายงาน-z.pdf": 60}.items():
        (docs / name).write_text("รายงาน")
        os.utime(docs / name, (NOW - age * DAY, NOW - age * DAY))
    c = TestClient(create_app(Config(data_dir=tmp_path / "data", folders=[str(docs)], allowed_hosts=["testserver"],
                                     background_indexing=False)))
    c.post("/api/scan/start")
    for _ in range(100):
        if not c.get("/api/status").json()["indexing"]["running"] and c.get("/api/status").json()["counts"]["file"] == 3:
            break
        time.sleep(0.1)
    since = NOW - 7 * DAY
    r = c.get("/api/search", params={"q": "รายงาน", "since": since}).json()
    assert sorted(x["title"] for x in r["results"]) == ["รายงาน-x.pdf", "รายงาน-y.docx"] and r["total"] == 2
    assert c.get("/api/search/count", params={"q": "", "since": since, "types": "pdf"}).json()["total"] == 1
    assert c.get("/api/search/facets", params={"since": since}).json()["counts"] == {"pdf": 1, "word": 1}
    assert c.get("/api/search", params={"until": since}).json()["total"] == 1
