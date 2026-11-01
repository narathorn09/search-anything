"""Command line entry point.

    python -m search_anything --mode local --folder ~/Documents
    SA_PASSWORD=... python -m search_anything --mode server --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from .app import Config, create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="search_anything", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["local", "server"],
                        default=os.environ.get("SA_MODE", "local"))
    parser.add_argument("--host", default=os.environ.get("SA_HOST"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SA_PORT", "8765")))
    parser.add_argument("--data-dir", default=os.environ.get("SA_DATA_DIR", "data"))
    parser.add_argument("--folder", action="append", default=[],
                        help="folder to index (repeatable). Also SA_FOLDERS, separated by os.pathsep")
    parser.add_argument("--reindex-interval", type=int,
                        default=int(os.environ.get("SA_REINDEX_INTERVAL", "300")),
                        help="seconds between automatic re-scans")
    parser.add_argument("--auto-lock", type=int, default=int(os.environ.get("SA_AUTO_LOCK", "900")),
                        help="seconds of inactivity before the password vault locks")
    parser.add_argument("--allowed-host", action="append", default=None,
                        help="hostname allowed in the Host header (server mode; repeatable)")
    parser.add_argument("--max-upload-mb", type=int, default=int(os.environ.get("SA_MAX_UPLOAD_MB", "200")),
                        help="largest file accepted by the upload button")
    parser.add_argument("--open-browser", action="store_true",
                        help="open the app in the default browser once it is ready")
    parser.add_argument("--default-folders", action="store_true",
                        help="local mode, first run only: index Documents, Desktop and Downloads")
    parser.add_argument("--https-cookie", action="store_true",
                        default=os.environ.get("SA_HTTPS_COOKIE") == "1",
                        help="mark the login cookie Secure (use behind HTTPS)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    folders = list(args.folder)
    if os.environ.get("SA_FOLDERS"):
        folders += [f for f in os.environ["SA_FOLDERS"].split(os.pathsep) if f]

    host = args.host or ("127.0.0.1" if args.mode == "local" else "0.0.0.0")
    in_container = os.environ.get("SA_IN_CONTAINER") == "1"
    if args.mode == "local" and host not in ("127.0.0.1", "localhost") and not in_container:
        sys.exit("local mode has no login, so it only listens on 127.0.0.1. Use --mode server.")
    # SA_IN_CONTAINER=1 (set by the start scripts): local mode inside Docker must
    # listen on the container's network; the scripts publish the port on the
    # host's 127.0.0.1 only, so it is still reachable from this computer only.

    password = os.environ.get("SA_PASSWORD")
    if args.mode == "server" and not password:
        sys.exit("server mode needs a login password: set the SA_PASSWORD environment variable.")

    allowed_hosts = args.allowed_host
    if allowed_hosts is None and os.environ.get("SA_ALLOWED_HOSTS"):
        allowed_hosts = os.environ["SA_ALLOWED_HOSTS"].split(",")

    data_dir = Path(args.data_dir).expanduser()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        sys.exit(
            f"cannot write to the data folder {data_dir} ({exc.strerror}).\n"
            "Docker/Kubernetes: mount a volume there that user 10001 can write "
            "(Kubernetes/Rancher: set the pod's fsGroup / Filesystem Group to 10001)."
        )

    if args.default_folders and args.mode == "local" and not folders and not (data_dir / "search.db").exists():
        home = Path.home()
        folders = [str(home / name) for name in ("Documents", "Desktop", "Downloads") if (home / name).is_dir()]
        if folders:
            print("First run: searching", ", ".join(folders), "(change in Settings > การสแกนไฟล์)")

    config = Config(
        mode=args.mode,
        data_dir=data_dir,
        folders=folders,
        password=password,
        reindex_interval=args.reindex_interval,
        auto_lock_seconds=args.auto_lock,
        allowed_hosts=allowed_hosts,
        https_only_cookie=args.https_cookie,
        max_upload_mb=args.max_upload_mb,
        path_map=_parse_path_map(os.environ.get("SA_PATH_MAP", "")),
        can_open_files=not in_container,
    )
    # Background work (counting, scanning supervision) shares the GIL with the
    # web handlers; shorter switch intervals keep searches snappy meanwhile
    # (measured: concurrent page-1 searches ~85 ms -> ~55 ms).
    sys.setswitchinterval(0.001)
    app = create_app(config)
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{args.port}"
    print(f"CAHON ({args.mode} mode) -> {url}   (Ctrl+C to stop)", flush=True)
    if args.open_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(app, host=host, port=args.port, log_level="warning")


def _parse_path_map(text: str) -> list[tuple[str, str]]:
    """"/host/Documents=/Users/me/Documents;/host/Work=D:\\Work" -> pairs."""
    pairs = []
    for part in text.split(";"):
        inner, sep, outer = part.partition("=")
        if sep and inner.strip() and outer.strip():
            pairs.append((inner.strip(), outer.strip()))
    return pairs


def _open_when_ready(url: str) -> None:
    """Wait until the server answers, then open the browser."""
    for _ in range(100):
        try:
            with urllib.request.urlopen(url + "/api/status", timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    webbrowser.open(url)


if __name__ == "__main__":
    main()
