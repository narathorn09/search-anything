"""In-app updates: version check against GitHub releases, download checks."""

import hashlib
import io
import urllib.request

import pytest
from fastapi.testclient import TestClient

from cahon import __version__, updater
from cahon.app import Config, create_app


def release(tag, assets=()):
    return {"tag_name": tag, "body": "แก้บั๊ก", "html_url": "https://github.com/x/releases/tag/" + tag,
            "published_at": "2026-11-01T00:00:00Z", "assets": list(assets)}


def asset(name, data):
    return {"name": name, "browser_download_url": "https://example.invalid/" + name, "size": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest()}


def test_versions():
    assert updater.parse_version("v1.2.10") == (1, 2, 10)
    assert updater.parse_version("1.0.0") == (1, 0, 0)
    assert updater.parse_version("nightly") is None
    assert updater.parse_version("v1.2.10") > updater.parse_version("v1.2.9")


def test_check_finds_newer_release_for_this_computer(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "asset_suffix", lambda: ".exe")
    u = updater.Updater(tmp_path, enabled=True, fetch=lambda url: release("v99.0.0", [
        asset("CAHON-99.0.0-macos-arm64.dmg", b"m"), asset("CAHON-Setup-99.0.0.exe", b"w")]))
    st = u.check()
    assert st["newer"] and st["latest"] == "99.0.0" and st["current"] == __version__
    assert u.latest["asset"]["name"] == "CAHON-Setup-99.0.0.exe"
    same = updater.Updater(tmp_path, enabled=True, fetch=lambda url: release("v" + __version__))
    assert same.check()["newer"] is False


def test_check_failure_is_reported_not_raised(tmp_path):
    def offline(url):
        raise OSError("network unreachable")

    st = updater.Updater(tmp_path, enabled=True, fetch=offline).check()
    assert st["state"] == "error" and "network unreachable" in st["error"]


def test_disabled_updater_never_fetches(tmp_path, monkeypatch):
    def boom(url):
        raise AssertionError("must not contact GitHub")

    assert updater.Updater(tmp_path, enabled=False, fetch=boom).check()["enabled"] is False
    monkeypatch.setenv("CAHON_UPDATES", "0")
    assert updater.Updater(tmp_path, enabled=True, fetch=boom).check()["enabled"] is False


def test_download_checks_sha256(tmp_path, monkeypatch):
    data = b"installer bytes" * 1000

    class Resp(io.BytesIO):
        headers = {"Content-Length": str(len(data))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: Resp(data))
    u = updater.Updater(tmp_path, enabled=True)
    raw = asset("Setup.exe", data)
    good = {"name": raw["name"], "url": raw["browser_download_url"], "size": raw["size"], "digest": raw["digest"]}
    assert u.download(good).read_bytes() == data and u.progress == 1.0
    bad = {**good, "digest": "sha256:" + "0" * 64}
    with pytest.raises(ValueError, match="SHA-256"):
        u.download(bad)


def test_auto_check_setting_is_remembered(tmp_path):
    u = updater.Updater(tmp_path, enabled=True)
    assert u.auto is True
    u.set_auto(False)
    assert updater.Updater(tmp_path, enabled=True).auto is False


def test_update_api_only_in_the_desktop_app(tmp_path):
    plain = TestClient(create_app(Config(data_dir=tmp_path / "a", allowed_hosts=["testserver"], background_indexing=False)))
    assert plain.get("/api/status").json()["update"] is None
    assert plain.post("/api/update/check").status_code == 400
    assert plain.get("/api/status").json()["version"] == __version__
    desktop = TestClient(create_app(Config(data_dir=tmp_path / "b", allowed_hosts=["testserver"],
                                           background_indexing=False, updates=True)))
    st = desktop.get("/api/status").json()["update"]
    assert st["enabled"] and st["current"] == __version__ and st["can_install"] is False  # not frozen
    assert desktop.put("/api/update/settings", json={"auto": False}).json()["auto"] is False


def test_no_release_yet_is_not_an_error(tmp_path):
    import urllib.error

    def not_found(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    st = updater.Updater(tmp_path, enabled=True, fetch=not_found).check()
    assert st["state"] == "idle" and st["newer"] is False and "ยังไม่มีเวอร์ชัน" in st["error"]


def test_new_repository_name_first_then_the_old_one(tmp_path):
    import urllib.error

    asked = []

    def fetch(url):
        asked.append(url)
        if "/cahon/" in url:  # not renamed yet
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return release("v99.0.0")

    st = updater.Updater(tmp_path, enabled=True, fetch=fetch).check()
    assert st["latest"] == "99.0.0"
    assert [u.split("/repos/")[1].split("/releases")[0] for u in asked] == ["narathorn09/cahon", "narathorn09/search-anything"]
