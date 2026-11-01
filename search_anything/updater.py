"""In-app updates for the desktop app (Windows installer / macOS .app).

Versions are released by tagging a commit on main as vX.Y.Z; CI builds the
installers and publishes them as a GitHub release (.github/workflows/
desktop.yml). This module:

* asks GitHub which release is the latest (one HTTPS GET to
  api.github.com; nothing about the user, their files or searches is sent),
* downloads the installer for this computer and checks its SHA-256 against
  the digest GitHub publishes for the asset,
* installs it: Windows runs the installer silently (it reopens the app),
  macOS swaps the .app bundle and reopens it. If the .app cannot be
  replaced (no write access), the disk image is opened for a manual drag.

This is the only part of the app that uses the internet, only in the
desktop app, and it can be switched off in Settings (or SA_UPDATES=0).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__

log = logging.getLogger(__name__)

REPO = "narathorn09/search-anything"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 24 * 3600
TIMEOUT = 15
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = _VERSION.match(text.strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def asset_suffix() -> str | None:
    """File name ending of the installer for this computer."""
    if sys.platform.startswith("win"):
        return ".exe"
    if sys.platform == "darwin":
        return "-macos-arm64.dmg" if platform.machine() == "arm64" else "-macos-x86_64.dmg"
    return None


def can_install() -> bool:
    """Self-install only from the installed (frozen) desktop app."""
    return getattr(sys, "frozen", False) and asset_suffix() is not None


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"SearchAnything/{__version__}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


class Updater:
    def __init__(self, data_dir: Path, enabled: bool, fetch=_get_json):
        self.dir = data_dir / "updates"
        self.enabled = enabled and os.environ.get("SA_UPDATES", "1") != "0"
        self.fetch = fetch
        self.settings_file = data_dir / "update-settings.json"
        self.auto = self._load().get("auto", True)
        self.latest: dict | None = None
        self.last_check = 0.0
        self.error = ""
        self.state = "idle"  # idle | checking | downloading | ready | installing | error
        self.progress = 0.0
        self.on_quit = None  # set by the desktop app: close the window so the update can replace it
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- settings
    def _load(self) -> dict:
        try:
            return json.loads(self.settings_file.read_text())
        except (OSError, ValueError):
            return {}

    def set_auto(self, auto: bool) -> None:
        self.auto = bool(auto)
        self.settings_file.write_text(json.dumps({"auto": self.auto}))

    def status(self) -> dict:
        latest = self.latest or {}
        return {
            "enabled": self.enabled, "can_install": can_install(), "current": __version__, "auto": self.auto,
            "last_check": self.last_check, "state": self.state, "progress": round(self.progress, 3),
            "error": self.error, "newer": bool(latest.get("newer")), "latest": latest.get("version"),
            "notes": latest.get("notes", ""), "page": latest.get("page"), "size": latest.get("size"),
            "published": latest.get("published"),
        }

    # ------------------------------------------------------------------- check
    def check(self) -> dict:
        if not self.enabled:
            return self.status()
        self.state, self.error = "checking", ""
        try:
            rel = self.fetch(LATEST_URL)
            version = parse_version(rel.get("tag_name", ""))
            if version is None:
                raise ValueError(f"unexpected release tag {rel.get('tag_name')!r}")
            suffix = asset_suffix()
            asset = next((a for a in rel.get("assets", []) if suffix and a.get("name", "").endswith(suffix)), None)
            self.latest = {
                "version": ".".join(map(str, version)),
                "newer": version > (parse_version(__version__) or (0, 0, 0)),
                "notes": (rel.get("body") or "")[:5000],
                "page": rel.get("html_url"),
                "published": rel.get("published_at"),
                "asset": asset and {"name": asset["name"], "url": asset["browser_download_url"],
                                    "size": asset.get("size"), "digest": asset.get("digest") or ""},
                "size": asset and asset.get("size"),
            }
            self.state = "idle"
        except Exception as exc:  # offline, rate-limited, no release yet …
            self.state, self.error = "error", f"ตรวจหาเวอร์ชันใหม่ไม่ได้: {exc}"
            log.info("update check failed: %s", exc)
        self.last_check = time.time()
        return self.status()

    def start_background(self) -> None:
        """Check at start and then once a day, while auto-check is on."""
        def loop():
            time.sleep(20)  # let the first scan start first
            while True:
                if self.enabled and self.auto and time.time() - self.last_check >= CHECK_EVERY:
                    self.check()
                time.sleep(600)

        threading.Thread(target=loop, name="update-check", daemon=True).start()

    # ---------------------------------------------------------------- install
    def install(self) -> dict:
        """Download, verify and install the newer version (in the background)."""
        with self._lock:
            if self.state in ("downloading", "installing"):
                return self.status()
            asset = (self.latest or {}).get("asset")
            if not (self.latest and self.latest.get("newer") and asset):
                self.state, self.error = "error", "ไม่มีเวอร์ชันใหม่สำหรับเครื่องนี้"
                return self.status()
            if not can_install():
                self.state, self.error = "error", "อัปเดตในแอปได้เฉพาะแอปที่ติดตั้งจากตัวติดตั้ง"
                return self.status()
            self.state, self.progress, self.error = "downloading", 0.0, ""
        threading.Thread(target=self._download_and_install, args=(asset,), name="update", daemon=True).start()
        return self.status()

    def _download_and_install(self, asset: dict) -> None:
        try:
            path = self.download(asset)
            self.state = "installing"
            launch_installer(path)
            if self.on_quit:
                threading.Timer(1.0, self.on_quit).start()
        except Exception as exc:
            log.exception("update failed")
            self.state, self.error = "error", f"อัปเดตไม่สำเร็จ: {exc}"

    def download(self, asset: dict) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / asset["name"]
        partial = target.with_suffix(target.suffix + ".part")
        digest = hashlib.sha256()
        req = urllib.request.Request(asset["url"], headers={"User-Agent": f"SearchAnything/{__version__}"})
        with urllib.request.urlopen(req, timeout=60) as r, partial.open("wb") as out:
            total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                self.progress = done / total if total else 0.0
        if asset.get("size") and done != asset["size"]:
            raise ValueError("ดาวน์โหลดไม่ครบ")
        expected = asset.get("digest", "")
        if expected.startswith("sha256:") and expected[7:].lower() != digest.hexdigest():
            partial.unlink(missing_ok=True)
            raise ValueError("ไฟล์ที่ดาวน์โหลดไม่ตรงกับ SHA-256 ที่ GitHub ประกาศ")
        partial.replace(target)
        self.progress = 1.0
        return target


# ------------------------------------------------------------------ install
def launch_installer(path: Path) -> None:
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # Inno Setup: silent, closes the running app, reopens it when done.
        subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         creationflags=flags, close_fds=True)
        return
    if sys.platform == "darwin":
        _install_macos(path)
        return
    raise RuntimeError("unsupported platform")


def current_app_bundle() -> Path | None:
    """…/Search Anything.app of the running app (sys.executable is in Contents/MacOS)."""
    exe = Path(sys.executable).resolve()
    for parent in exe.parents:
        if parent.suffix == ".app":
            return parent
    return None


def _install_macos(dmg: Path) -> None:
    app = current_app_bundle()
    if app is None or not os.access(app.parent, os.W_OK):
        subprocess.Popen(["open", str(dmg)])  # no write access: let the user drag it in
        return
    script = Path(tempfile.mkdtemp(prefix="sa-update-")) / "update.sh"
    script.write_text(f"""#!/bin/sh
# Wait for the app to quit, swap in the new version, reopen it.
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done
MNT=$(mktemp -d)
hdiutil attach -nobrowse -readonly -mountpoint "$MNT" {shlex_quote(dmg)} >/dev/null || exit 1
NEW=$(ls -d "$MNT"/*.app | head -1)
rm -rf {shlex_quote(app)}.old
mv {shlex_quote(app)} {shlex_quote(app)}.old && ditto "$NEW" {shlex_quote(app)} || mv {shlex_quote(app)}.old {shlex_quote(app)}
hdiutil detach "$MNT" >/dev/null
rm -rf {shlex_quote(app)}.old
open {shlex_quote(app)}
""")
    script.chmod(0o755)
    subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True)


def shlex_quote(p) -> str:
    import shlex

    return shlex.quote(str(p))


def cleanup_downloads(data_dir: Path) -> None:
    """Remove installers of versions already installed."""
    shutil.rmtree(data_dir / "updates", ignore_errors=True)
