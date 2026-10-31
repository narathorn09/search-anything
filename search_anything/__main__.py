"""Command line entry point.

    python -m search_anything --mode local --folder ~/Documents
    SA_PASSWORD=... python -m search_anything --mode server --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
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
    parser.add_argument("--https-cookie", action="store_true",
                        default=os.environ.get("SA_HTTPS_COOKIE") == "1",
                        help="mark the login cookie Secure (use behind HTTPS)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    folders = list(args.folder)
    if os.environ.get("SA_FOLDERS"):
        folders += [f for f in os.environ["SA_FOLDERS"].split(os.pathsep) if f]

    host = args.host or ("127.0.0.1" if args.mode == "local" else "0.0.0.0")
    if args.mode == "local" and host not in ("127.0.0.1", "localhost"):
        sys.exit("local mode has no login, so it only listens on 127.0.0.1. Use --mode server.")

    password = os.environ.get("SA_PASSWORD")
    if args.mode == "server" and not password:
        sys.exit("server mode needs a login password: set the SA_PASSWORD environment variable.")

    allowed_hosts = args.allowed_host
    if allowed_hosts is None and os.environ.get("SA_ALLOWED_HOSTS"):
        allowed_hosts = os.environ["SA_ALLOWED_HOSTS"].split(",")

    config = Config(
        mode=args.mode,
        data_dir=Path(args.data_dir).expanduser(),
        folders=folders,
        password=password,
        reindex_interval=args.reindex_interval,
        auto_lock_seconds=args.auto_lock,
        allowed_hosts=allowed_hosts,
        https_only_cookie=args.https_cookie,
    )
    app = create_app(config)
    print(f"Search Anything ({args.mode} mode) → http://{'localhost' if host == '127.0.0.1' else host}:{args.port}")
    uvicorn.run(app, host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
