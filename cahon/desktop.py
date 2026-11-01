"""Desktop app entry point (the Windows / macOS installers run this).

* Opens the app in its own window (pywebview: Edge WebView2 on Windows,
  WebKit on macOS). If that is not possible it opens the default browser.
* Data lives in the user's app-data folder, not next to the program:
  Windows %LOCALAPPDATA%\\CAHON, macOS ~/Library/Application Support/CAHON,
  Linux ~/.local/share/cahon.
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

APP_NAME = "CAHON"
PREFERRED_PORT = 8765
log = logging.getLogger("cahon.desktop")


def data_dir() -> Path:
    if os.environ.get("CAHON_DATA_DIR"):
        return Path(os.environ["CAHON_DATA_DIR"]).expanduser()
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "CAHON"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CAHON"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "cahon"


def bundle_dir() -> Path | None:
    """Where PyInstaller unpacked the app's files (None when not frozen)."""
    return Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else None


def use_bundled_tesseract() -> None:
    """Point OCR at the Tesseract inside the installed app, if it is there."""
    base = bundle_dir()
    if base is None or os.environ.get("CAHON_TESSERACT"):
        return
    exe = base / "tesseract" / ("tesseract.exe" if sys.platform.startswith("win") else "tesseract")
    if exe.is_file():
        os.environ["CAHON_TESSERACT"] = str(exe)
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
    app = create_app(Config(mode="local", data_dir=folder, folders=folders, updates=True, desktop=True))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           log_config=None))
    thread = threading.Thread(target=server.run, name="web", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    return server, thread, app


def copy_to_clipboard(text: str) -> None:
    """Put text on the system clipboard (the window's own clipboard access can be
    refused by WebView2/WebKit; this always works)."""
    if sys.platform.startswith("win"):
        _win_clipboard(text)
    elif sys.platform == "darwin":
        import subprocess

        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True,
                       env={**os.environ, "LANG": "en_US.UTF-8"})  # pbcopy reads the locale's encoding
    else:
        import shutil
        import subprocess

        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return
        raise OSError("no clipboard tool (wl-copy, xclip or xsel)")


def _win_clipboard(text: str) -> None:
    import ctypes
    from ctypes import wintypes

    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.argtypes, k32.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
    k32.GlobalLock.argtypes, k32.GlobalLock.restype = [wintypes.HGLOBAL], wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.SetClipboardData.argtypes, u32.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
    data = text.encode("utf-16-le") + b"\0\0"
    for _ in range(20):  # another program may hold the clipboard for a moment
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("the clipboard is busy")
    try:
        u32.EmptyClipboard()
        handle = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ptr = k32.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(handle)
        if not u32.SetClipboardData(13, handle):  # CF_UNICODETEXT; the clipboard owns it now
            k32.GlobalFree(handle)
            raise OSError("could not set the clipboard")
    finally:
        u32.CloseClipboard()


def _quit(server) -> None:
    """Close the app (an update is about to replace it)."""
    try:
        import webview

        for window in list(webview.windows):
            window.destroy()
    except Exception:
        pass
    server.should_exit = True


def choose_folder() -> str | None:
    """The system's "choose folder" window, over the app window. None when cancelled."""
    import webview

    if not webview.windows:
        raise RuntimeError("no app window")
    kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
    if kind is None:  # pywebview < 5
        kind = webview.FOLDER_DIALOG
    result = webview.windows[0].create_file_dialog(kind)
    if not result:
        return None
    return result[0] if isinstance(result, (list, tuple)) else str(result)


def show_window(url: str) -> bool:
    """Run the app window until it is closed. False if no window could be shown."""
    if os.environ.get("CAHON_NO_WINDOW") == "1":  # tests / CI: browser mode
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
        # text_select: pywebview turns text selection off unless asked (it adds
        # "user-select: none" to the page), so nothing could be selected or copied.
        webview.create_window(APP_NAME, url, width=1280, height=860, min_size=(720, 520), text_select=True)
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
    from . import __version__
    from .extractors import NATIVE
    from .ocr import engine
    from .updater import cleanup_downloads

    cleanup_downloads(folder)  # installers of versions already installed

    log.info("CAHON %s (desktop) at %s, data in %s; Rust readers: %s; OCR: %s",
             __version__, url, folder, NATIVE, engine().info())
    updater = app.state.updater
    updater.on_quit = lambda: _quit(server)
    if updater.enabled:
        updater.start_background()
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
