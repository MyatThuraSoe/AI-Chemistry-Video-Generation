#!/usr/bin/env bash
# Run all three required queries and verify every downloaded artifact.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

QUERIES=(
  "How does the pH scale work?"
  "Why do atoms form covalent bonds?"
  "What is the difference between ionic and covalent bonding?"
)
SLUGS=(ph_scale covalent_bonding ionic_vs_covalent)

if [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT_DIR/.venv/Scripts/python.exe"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
else
  PYTHON="${PYTHON:-python}"
fi

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
API_BASE_URL="${API_BASE_URL%/}"
export API_BASE_URL

mkdir -p downloads
FAILED=0

for index in "${!QUERIES[@]}"; do
  query="${QUERIES[$index]}"
  output="downloads/${SLUGS[$index]}.mp4"
  echo
  echo "============================================================"
  echo "[$((index + 1))/3] $query"
  echo "============================================================"
  if bash scripts/demo.sh "$query" "$output"; then
    echo "Verifying $output"
    if ! bash scripts/verify_artifact.sh "$output"; then
      echo "FAILED: artifact verification failed for $output" >&2
      FAILED=1
    fi
  else
    echo "FAILED: generation failed for '$query'" >&2
    FAILED=1
  fi
done

echo
if (( FAILED )); then
  echo "Result: FAILED (one or more required jobs did not complete or validate)." >&2
  exit 1
fi

echo "Result: OK"
echo "Videos:"
for index in "${!SLUGS[@]}"; do
  echo "  - downloads/${SLUGS[$index]}.mp4"
done
