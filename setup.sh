#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Stimma Setup ==="
echo

need_cmd() {
  local cmd="$1"
  local hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing ${cmd}. ${hint}" >&2
    exit 1
  fi
}

need_cmd node "Install Node.js 18+."
need_cmd npm "Install npm."
need_cmd uv "Install uv: https://docs.astral.sh/uv/"
need_cmd python3 "Install Python 3.11+."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Warning: FFmpeg was not found. Video processing will not work until it is installed."
fi

echo "Installing backend dependencies..."
(
  cd "$ROOT_DIR/backend"
  uv sync --all-extras
)

echo "Installing frontend dependencies..."
(
  cd "$ROOT_DIR/frontend"
  npm install
)

echo
echo "Setup complete."
echo
echo "Run Stimma in development mode with:"
echo "  tools/stimma dev backend"
echo "  tools/stimma dev frontend"
echo "  tools/stimma dev app"
echo
echo "The default development ports are backend 9191 and frontend 9192."
