#!/usr/bin/env bash
# CAHON — one-step start for macOS (also works on Linux).
#   Double-click this file in Finder, or run:  ./start.command
#
# Runs in Docker when Docker is installed and running, otherwise in a Python
# virtual environment (.venv). Options:
#   --docker          use Docker (fail if it is not available)
#   --no-docker       always use Python/.venv
#   --folder PATH     folder to search (repeatable; default: Documents, Desktop, Downloads)
#   anything else is passed to the app, e.g. --reindex-interval 600
# Environment: CAHON_PORT (default 8765).
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
PORT="${CAHON_PORT:-8765}"
URL="http://localhost:$PORT"
NAME="cahon"
IMAGE="cahon:local"
VOLUME="cahon-data"

USE="auto"
FOLDERS=()
APP_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --docker) USE="docker" ;;
    --no-docker) USE="venv" ;;
    --folder) shift; FOLDERS+=("$1") ;;
    --folder=*) FOLDERS+=("${1#--folder=}") ;;
    *) APP_ARGS+=("$1") ;;
  esac
  shift
done

open_url() {
  if command -v open >/dev/null 2>&1; then open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  else echo "Open $1 in your browser"; fi
}

wait_and_open() {
  for _ in $(seq 1 120); do
    if curl -fsS -o /dev/null "$URL/api/status" 2>/dev/null; then open_url "$URL"; return 0; fi
    sleep 0.5
  done
  echo "The app did not answer at $URL yet."
}

docker_ready() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }

# ------------------------------------------------------------------ venv
run_venv() {
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
      say "Python 3.10 or newer is needed. Opening the download page — install it (or Docker Desktop), then run this file again."
      open_url "https://www.python.org/downloads/macos/"
      read -r -p "Press Enter to close…" _ || true
      exit 1
    fi
  fi
  if [ ! -x .venv/bin/python ]; then
    say "First run: preparing Python environment (a few minutes)…"
    "$PY" -m venv .venv
  fi
  HASH="$(.venv/bin/python -c "import hashlib; print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())")"
  if [ ! -f .venv/.requirements.sha ] || [ "$(cat .venv/.requirements.sha)" != "$HASH" ]; then
    say "Installing packages…"
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -r requirements.txt
    echo "$HASH" > .venv/.requirements.sha
  fi
  # Fast Rust readers for Word/Excel/PowerPoint (optional; needs Rust to build once).
  NATIVE_HASH="$(.venv/bin/python -c "import hashlib, pathlib; print(hashlib.sha256(b''.join(p.read_bytes() for p in sorted(pathlib.Path('native').rglob('*')) if p.is_file() and 'target' not in p.parts)).hexdigest())")"
  if [ ! -f .venv/.native.sha ] || [ "$(cat .venv/.native.sha)" != "$NATIVE_HASH" ]; then
    if command -v cargo >/dev/null 2>&1 || [ -x "$HOME/.cargo/bin/cargo" ]; then
      say "Building the fast file readers (Rust, first time only)…"
      if PATH="$HOME/.cargo/bin:$PATH" .venv/bin/python -m pip install --quiet ./native; then
        echo "$NATIVE_HASH" > .venv/.native.sha
      else
        echo "Could not build them — using the Python readers (slower, same results)."
      fi
    else
      echo "Tip: install Rust (https://rustup.rs) for ~3x faster scanning of Word/Excel/PowerPoint files (or run with Docker)."
    fi
  fi
  if ! command -v tesseract >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/tesseract ] && [ ! -x /usr/local/bin/tesseract ]; then
    echo "Tip: to search scanned PDFs (OCR), install Tesseract:  brew install tesseract tesseract-lang   (or run with Docker)"
  fi
  say "Starting CAHON (Python)…   data: ./data   stop: Ctrl+C"
  ARGS=(--port "$PORT" --open-browser)
  if [ ${#FOLDERS[@]} -eq 0 ]; then ARGS+=(--default-folders); else for f in "${FOLDERS[@]}"; do ARGS+=(--folder "$f"); done; fi
  exec .venv/bin/python -m cahon "${ARGS[@]}" ${APP_ARGS[@]+"${APP_ARGS[@]}"}
}

# ---------------------------------------------------------------- docker
run_docker() {
  say "Building the Docker image (quick after the first time)…"
  if ! docker build -q -t "$IMAGE" . >/dev/null; then
    if docker image inspect "$IMAGE" >/dev/null 2>&1; then
      say "Build failed (offline?) — using the image built earlier."
    elif [ "$USE" = "docker" ]; then
      say "Docker build failed."; exit 1
    else
      say "Docker build failed — starting with Python instead."; run_venv
    fi
  fi

  # Folders to search: mounted read-only at /host/<name>.
  if [ ${#FOLDERS[@]} -eq 0 ]; then
    for d in Documents Desktop Downloads; do [ -d "$HOME/$d" ] && FOLDERS+=("$HOME/$d"); done
  fi
  MOUNTS=(); INNER=(); MAP=""
  for f in ${FOLDERS[@]+"${FOLDERS[@]}"}; do
    abs="$(cd "$f" 2>/dev/null && pwd)" || { echo "Skipping missing folder: $f"; continue; }
    name="$(basename "$abs")"; inner="/host/$name"; n=2
    while printf '%s\n' ${INNER[@]+"${INNER[@]}"} | grep -qx "$inner"; do inner="/host/$name-$n"; n=$((n + 1)); done
    INNER+=("$inner")
    MOUNTS+=(--mount "type=bind,source=$abs,target=$inner,readonly")
    MAP="$MAP$inner=$abs;"
  done
  CAHON_FOLDERS_IN="$(IFS=:; echo ${INNER[@]+"${INNER[*]}"})"

  docker rm -f "$NAME" >/dev/null 2>&1 || true
  say "Starting CAHON (Docker)…   data: Docker volume $VOLUME   stop: Ctrl+C"
  # Port published on 127.0.0.1 only: reachable from this computer, not the network.
  docker run -d --rm --init --name "$NAME" -p "127.0.0.1:$PORT:8765" \
    -v "$VOLUME":/data \
    -e CAHON_MODE=local -e CAHON_HOST=0.0.0.0 -e CAHON_IN_CONTAINER=1 \
    -e CAHON_FOLDERS="$CAHON_FOLDERS_IN" -e CAHON_PATH_MAP="$MAP" \
    ${MOUNTS[@]+"${MOUNTS[@]}"} "$IMAGE" python -m cahon ${APP_ARGS[@]+"${APP_ARGS[@]}"} >/dev/null
  stop_app() { say "Stopping…"; docker stop "$NAME" >/dev/null 2>&1 || true; exit 0; }
  trap stop_app INT TERM HUP
  wait_and_open
  # Follow the logs in the background and *wait*: unlike a foreground command,
  # wait is interrupted at once by Ctrl+C / closing the window / TERM.
  docker logs -f "$NAME" 2>&1 &
  wait $! || true
  stop_app
}

if [ "$USE" = "venv" ]; then
  run_venv
elif docker_ready; then
  run_docker
elif [ "$USE" = "docker" ]; then
  say "Docker is not installed or not running. Start Docker Desktop, or run without --docker."
  exit 1
else
  say "Docker not found or not running — using Python instead."
  run_venv
fi
