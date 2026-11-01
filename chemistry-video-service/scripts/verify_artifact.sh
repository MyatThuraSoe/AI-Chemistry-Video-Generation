#!/usr/bin/env bash
# Verify an MP4 with FFprobe using the service's binary auto-discovery.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT_DIR/.venv/Scripts/python.exe"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
else
  PYTHON="${PYTHON:-python}"
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/verify_artifact.sh path/to/video.mp4 [--min-duration 10]" >&2
  exit 2
fi

cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" scripts/verify_artifact.py "$@"
