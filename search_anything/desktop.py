"""Desktop app entry point (the Windows / macOS installers run this).

* Opens the app in its own window (pywebview: Edge WebView2 on Windows,
  WebKit on macOS). If that is not possible it opens the default browser.
* Data lives in the user's app-data folder, not next to the program:
  Windows %LOCALAPPDATA%\\SearchAnything, macOS ~/Library/Application
  Support/Search Anything, Linux ~/.local/share/search-anything.
* Only one copy runs: starting it again just shows the running one.
* Local mode only (no login), listening on 127.0.0.1.
* In the installed app, Tesseract (OCR) ships inside the bundle.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "Search Anything"
PREFERRED_PORT = 8765
log = logging.getLogger("search_anything.desktop")


def data_dir() -> Path:
    if os.environ.get("SA_DATA_DIR"):
        return Path(os.environ["SA_DATA_DIR"]).expanduser()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "SearchAnything"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "search-anything"


def bundle_dir() -> Path | None:
    """Where PyInstaller unpacked the app's files (None when not frozen)."""
    return Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else None


def use_bundled_tesseract() -> None:
    """Point OCR at the Tesseract inside the installed app, if it is there."""
    base = bundle_dir()
    if base is None or os.environ.get("SA_TESSERACT"):
        return
    exe = base / "tesseract" / ("tesseract.exe" if sys.platform.startswith("win") else "tesseract")
    if exe.is_file():
        os.environ["SA_TESSERACT"] = str(exe)
        os.environ["TESSDATA_PREFIX"] = str(base / "tesseract" / "tessdata")


def _answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1) as r:
            return "mode" in json.loads(r.read() or b"{}")
    except (OSError, ValueError):
        return False


def running_instance(state_file: Path) -> int | None:
    """Port of a copy that is already running, if any."""
    try:
        port = int(json.loads(state_file.read_text())["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return port if _answers(port) else None


def free_port(preferred: int = PREFERRED_PORT) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


def _log_to_file(folder: Path) -> None:
    """A windowed app has no console: keep a log file (and never crash on print)."""
    handler = logging.FileHandler(folder / "app.log", encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout is None or sys.stderr is None:  # pythonw / windowed PyInstaller
        stream = open(folder / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


def start_server(folder: Path, port: int):
    """Start the app in a background thread; returns (uvicorn server, thread, app)."""
    import uvicorn

    from .app import Config, create_app

    first_run = not (folder / "search.db").exists()
    folders: list[str] = []
    if first_run:
        home = Path.home()
        folders = [str(home / n) for n in ("Documents", "Desktop", "Downloads") if (home / n).is_dir()]
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    app = create_app(Config(mode="local", data_dir=folder, folders=folders))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           log_config=None))
    thread = threading.Thread(target=server.run, name="web", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    return server, thread, app


def show_window(url: str) -> bool:
    """Run the app window until it is closed. False if no window could be shown."""
    if os.environ.get("SA_NO_WINDOW") == "1":  # tests / CI: browser mode
        return False
    try:
        import webview
    except Exception as exc:  # not installed / no GUI toolkit
        log.info("no app window (%s); using the browser", exc)
        return False
    try:
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:  # older pywebview
        pass
    try:
        webview.create_window(APP_NAME, url, width=1280, height=860, min_size=(720, 520))
        webview.start(private_mode=False)
        return True
    except Exception as exc:  # e.g. Windows without the WebView2 runtime
        log.warning("app window failed (%s); using the browser", exc)
        return False


def main() -> None:
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    _log_to_file(folder)
    use_bundled_tesseract()
    state_file = folder / "running.json"

    port = running_instance(state_file)
    if port is not None:  # already open: show it again
        url = f"http://127.0.0.1:{port}/"
        if not show_window(url):
            webbrowser.open(url)
        return

    sys.setswitchinterval(0.001)  # same as the command-line app: snappy searches during scans
    port = free_port()
    server, thread, app = start_server(folder, port)
    state_file.write_text(json.dumps({"port": port, "pid": os.getpid()}))
    url = f"http://127.0.0.1:{port}/"
    from .extractors import NATIVE
    from .ocr import engine

    log.info("Search Anything (desktop) at %s, data in %s; Rust readers: %s; OCR: %s",
             url, folder, NATIVE, engine().info())
    try:
        if not show_window(url):
            webbrowser.open(url)
            while thread.is_alive():  # browser mode: run until the computer logs off / is killed
                thread.join(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            app.state.indexer.stop()
        except Exception:
            pass
        server.should_exit = True
        thread.join(10)
        try:
            state_file.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
