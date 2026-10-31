import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from search_anything import indexer as indexer_mod
from search_anything.app import Config, create_app
from search_anything.db import Database
from search_anything.indexer import Indexer, ScanSettings
from search_anything.resources import PROFILES, Brake


@pytest.fixture
def many(tmp_path: Path) -> Path:
    root = tmp_path / "many"
    for d in range(6):
        (root / f"d{d}").mkdir(parents=True)
        for i in range(50):
            (root / f"d{d}" / f"f{i}.txt").write_text(f"document {d}-{i} quokka")
    return root


@pytest.fixture
def slow_extract(monkeypatch):
    real = indexer_mod.extract_text

    def slow(path, size=None):
        time.sleep(0.004)
        return real(path, size)

    monkeypatch.setattr(indexer_mod, "extract_text", slow)


def wait_until(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_stop_keeps_partial_index_and_next_scan_finishes(tmp_path, many, slow_extract):
    db = Database(tmp_path / "t.db")
    ix = Indexer(db, [str(many)])
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("stats", ix.run()))
    t.start()
    assert wait_until(lambda: ix.progress.get("done", 0) >= 20)
    assert ix.status()["progress"]["phase"] == "indexing"
    assert ix.stop() is True
    t.join(10)
    stats = result["stats"]
    assert stats.stopped is True
    assert 20 <= stats.added_or_updated < 300
    assert ix.running is False and ix.status()["progress"]["phase"] == "idle"
    partial = db.counts()["file"]
    assert partial == stats.added_or_updated
    # The next scan only reads what is missing.
    again = ix.run()
    assert again.stopped is False
    assert again.added_or_updated == 300 - partial
    assert db.counts()["file"] == 300


def test_stop_during_walk_never_deletes_indexed_files(tmp_path, many, monkeypatch):
    db = Database(tmp_path / "t.db")
    ix = Indexer(db, [str(many)])
    ix.run()
    assert db.counts()["file"] == 300
    # Stop as soon as the walk starts.
    real_walk = Indexer._walk

    def walk_then_stop(root):
        for i, item in enumerate(real_walk(root)):
            if i == 10:
                ix._stop.set()
            yield item

    monkeypatch.setattr(Indexer, "_walk", staticmethod(walk_then_stop))
    stats = ix.run()
    assert stats.stopped is True and stats.removed == 0
    assert db.counts()["file"] == 300


def test_stop_cancels_queued_scan(tmp_path, many):
    db = Database(tmp_path / "t.db")
    ix = Indexer(db, [str(many)])
    with ix._run_lock:  # pretend a scan is running
        ix.running = True
        ix.trigger()
        ix.stop()
        ix.running = False
    time.sleep(0.3)
    assert db.counts()["file"] == 0  # the queued scan did not run


def test_brake_reasons_and_waiting():
    stop = threading.Event()
    values = {"cpu": 10.0, "sys": 20.0, "ram": 100.0, "free": 8000.0}
    brake = Brake(PROFILES["balanced"], stop, sampler=lambda: (values["cpu"], values["sys"], values["ram"], values["free"]))
    brake.sample(force=True)
    assert brake.over_limit() == ""
    values["cpu"] = 80
    brake.sample(force=True)
    assert "CPU 80%" in brake.over_limit()
    assert brake.over_limit(memory_only=True) == ""  # memory-only check ignores CPU
    values.update(cpu=10, sys=97)
    brake.sample(force=True)
    assert "ทำงานหนัก" in brake.over_limit()
    assert Brake(PROFILES["fast"], stop, sampler=lambda: (10, 97, 100, 8000)).over_limit() == ""  # fast doesn't yield
    values.update(sys=20, ram=5000)
    brake.sample(force=True)
    assert "RAM" in brake.over_limit(memory_only=True)
    # wait() gives up after max_wait (never hangs) and records the pause
    t = time.time()
    brake.wait(max_wait=0.3)
    assert 0.25 <= time.time() - t < 2 and brake.paused_seconds >= 0.25
    # … and returns at once when the scan is stopped
    stop.set()
    t = time.time()
    brake.wait()
    assert time.time() - t < 0.5


def test_brake_pauses_scan_until_resources_free(tmp_path, many, monkeypatch):
    calm_at = time.monotonic() + 1.0
    sampler = lambda: (95.0 if time.monotonic() < calm_at else 5.0, 10.0, 100.0, 8000.0)
    real_brake = indexer_mod.Brake
    monkeypatch.setattr(indexer_mod, "Brake", lambda profile, stop: real_brake(profile, stop, sampler=sampler))
    monkeypatch.setattr(real_brake, "SAMPLE_EVERY", 0.05)
    db = Database(tmp_path / "t.db")
    ix = Indexer(db, [str(many)], ScanSettings(profile="eco"))
    seen_reason = []
    t = threading.Thread(target=ix.run)
    t.start()
    wait_until(lambda: bool(ix.status()["progress"].get("throttled")) and not seen_reason.append(ix.status()["progress"]["throttled"]), 3)
    t.join(15)
    assert seen_reason and "CPU" in seen_reason[0]
    assert ix.last_stats.paused_seconds >= 0.5
    assert db.counts()["file"] == 300


def test_scan_settings_api(tmp_path):
    def client():
        return TestClient(create_app(Config(data_dir=tmp_path / "data", allowed_hosts=["testserver"],
                                            background_indexing=False)))
    c = client()
    st = c.get("/api/status").json()
    assert st["indexing"]["settings"] == {"profile": "balanced", "auto": True, "interval_minutes": 5}
    assert set(st["profiles"]) == {"eco", "balanced", "fast"}
    assert c.put("/api/scan/settings", json={"profile": "turbo", "auto": True, "interval_minutes": 5}).status_code == 422
    assert c.put("/api/scan/settings", json={"profile": "eco", "auto": False, "interval_minutes": 0}).status_code == 422
    r = c.put("/api/scan/settings", json={"profile": "eco", "auto": False, "interval_minutes": 30})
    assert r.json() == {"profile": "eco", "auto": False, "interval_minutes": 30}
    assert c.post("/api/scan/stop").json() == {"stopped": False}
    # Remembered across restarts.
    assert client().get("/api/status").json()["indexing"]["settings"]["profile"] == "eco"
