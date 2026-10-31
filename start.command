#!/usr/bin/env bash
# Search Anything — one-step start for macOS (also works on Linux).
#   Double-click this file in Finder, or run:  ./start.command
#   Extra options are passed to the app, e.g.  ./start.command --folder ~/Work
# First run: installs what it needs into .venv (a few minutes). Later runs start at once.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# 1) Python 3.10+
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then
    say "Installing Python with Homebrew…"
    brew install python@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    say "Python 3.10 or newer is needed. Opening the download page — install it, then run this file again."
    open "https://www.python.org/downloads/macos/" 2>/dev/null || true
    read -r -p "Press Enter to close…" _ || true
    exit 1
  fi
fi

# 2) Private environment + packages (only re-installed when requirements.txt changes)
if [ ! -x .venv/bin/python ]; then
  say "First run: preparing (this takes a few minutes)…"
  "$PY" -m venv .venv
fi
HASH="$(.venv/bin/python -c "import hashlib; print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())")"
if [ ! -f .venv/.requirements.sha ] || [ "$(cat .venv/.requirements.sha)" != "$HASH" ]; then
  say "Installing packages…"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  echo "$HASH" > .venv/.requirements.sha
fi

# 3) Run (browser opens by itself; close with Ctrl+C or by closing this window)
say "Starting Search Anything…"
exec .venv/bin/python -m search_anything --open-browser --default-folders "$@"
