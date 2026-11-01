import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cahon.app import Config, create_app
from cahon.db import Database
from cahon.indexer import ScanSettings
from cahon.worker import ProcessIndexer


@pytest.fixture
def files(tmp_path: Path) -> Path:
    root = tmp_path / "files"
    for d in range(10):
        (root / f"d{d}").mkdir(parents=True)
        for i in range(300):
            (root / f"d{d}" / f"f{i}.txt").write_text(f"row {d}-{i} wombat " * 20)
    (root / "poison.txt").write_text("this file crashes the reader capybara")
    return root


def wait_until(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_scan_runs_in_a_separate_process(tmp_path, files):
    db = Database(tmp_path / "t.db")
    ix = ProcessIndexer(db, [str(files)])
    pids = []
    t = threading.Thread(target=ix.run)
    t.start()
    wait_until(lambda: ix.worker_pid is not None and not pids.append(ix.worker_pid))
    t.join(60)
    assert pids and pids[0] != os.getpid()
    stats = ix.last_stats
    assert stats.stopped is False and stats.restarts == 0 and stats.added_or_updated == 3001
    # The web process sees what the worker wrote.
    assert db.counts()["file"] == 3001
    assert [r["title"] for r in db.search("capybara")] == ["poison.txt"]
    assert ix.status()["progress"] == {"phase": "idle"} and ix.running is False


def test_stop_ends_the_worker_and_keeps_partial_index(tmp_path, files):
    db = Database(tmp_path / "t.db")
    ix = ProcessIndexer(db, [str(files)], ScanSettings(profile="eco"))
    t = threading.Thread(target=ix.run)
    t.start()
    assert wait_until(lambda: ix.progress.get("done", 0) >= 100)
    assert ix.status()["progress"]["worker_pid"] == ix.worker_pid
    ix.stop()
    t.join(30)
    assert ix.last_stats.stopped is True
    partial = db.counts()["file"]
    assert 0 < partial < 3001
    assert ix.run().added_or_updated == 3001 - partial  # continues where it stopped


def test_worker_crash_restarts_and_skips_the_bad_file(tmp_path, files, monkeypatch):
    monkeypatch.setenv("CAHON_TEST_WORKER_CRASH_ON", "poison.txt")
    db = Database(tmp_path / "t.db")
    ix = ProcessIndexer(db, [str(files)])
    stats = ix.run()
    assert stats.restarts >= 1 and stats.stopped is False
    assert any("poison.txt" in e for e in stats.errors)
    assert str(files / "poison.txt") in ix.skipped_files()
    assert db.counts()["file"] == 3001  # everything indexed …
    assert db.search("capybara") == []  # … the bad file by name only
    assert [r["title"] for r in db.search("poison")] == ["poison.txt"]
    # Next scans don't trip over it again.
    assert ix.run().restarts == 0
    # Clearing the list makes the next scan try it again (and crash again here).
    assert ix.clear_skipped() == 1
    assert ix.run().restarts >= 1


def test_ram_ceiling_kills_worker_and_gives_up_cleanly(tmp_path, files):
    db = Database(tmp_path / "t.db")
    ix = ProcessIndexer(db, [str(files)], hard_ram_mb=1, max_restarts=2)
    t0 = time.time()
    stats = ix.run()
    assert time.time() - t0 < 60
    assert stats.restarts == 3
    assert any("RAM" in e for e in stats.errors) and any("ล่มซ้ำ" in e for e in stats.errors)
    assert ix.running is False


def test_app_uses_worker_process_and_clear_endpoint(tmp_path):
    c = TestClient(create_app(Config(data_dir=tmp_path / "data", allowed_hosts=["testserver"], background_indexing=False)))
    assert isinstance(c.app.state.indexer, ProcessIndexer)
    st = c.get("/api/status").json()["indexing"]
    assert st["worker"] == "process" and st["skipped"] == []
    assert c.delete("/api/scan/skipped").json() == {"cleared": 0}


def test_pdf_helper_crash_restarts_carefully_and_keeps_every_file(tmp_path, files, monkeypatch):
    import pypdfium2 as pdfium

    for name in ("a.pdf", "boom.pdf", "c.pdf"):
        pdf = pdfium.PdfDocument.new()
        pdf.new_page(595, 842).close()
        pdf.save(str(files / name))
        pdf.close()
    monkeypatch.setenv("CAHON_TEST_HELPER_CRASH_ON", "boom.pdf")
    db = Database(tmp_path / "t.db")
    ix = ProcessIndexer(db, [str(files)], ScanSettings(profile="fast", ocr=False))
    stats = ix.run()
    # A PDF helper process died: the worker restarted one file at a time
    # (in-process, where this file reads fine) and nothing was lost.
    assert stats.restarts >= 1 and stats.stopped is False
    assert db.counts()["file"] == 3004
    assert [r["title"] for r in db.search("boom")] == ["boom.pdf"]
    assert ix.skipped_files() == {}
