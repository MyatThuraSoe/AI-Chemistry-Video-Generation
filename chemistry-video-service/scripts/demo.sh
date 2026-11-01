#!/usr/bin/env bash
# Submit one chemistry video job, poll it, and download the MP4.
#
# Usage:
#   scripts/demo.sh "How does the pH scale work?" [output.mp4]
#
# Environment:
#   API_BASE_URL (default http://127.0.0.1:8000)
#   API_KEY (optional X-API-Key)
#   POLL_TIMEOUT_SECONDS (default 900)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUERY="${1:-How does the pH scale work?}"
OUTPUT="${2:-}"

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
API_BASE_URL="${API_BASE_URL%/}"
POLL_TIMEOUT_SECONDS="${POLL_TIMEOUT_SECONDS:-900}"

if [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT_DIR/.venv/Scripts/python.exe"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
else
  PYTHON="${PYTHON:-python}"
fi

AUTH_ARGS=()
if [[ -n "${API_KEY:-}" ]]; then
  AUTH_ARGS=(-H "X-API-Key: ${API_KEY}")
fi

TMP_DIR="$(mktemp -d)"
# Cleanup must never change the script's exit status: a failed/blocked removal
# of a scratch directory should not turn a successful run into a failure.
trap 'rm -rf "$TMP_DIR" 2>/dev/null || true' EXIT

json_value() {
  local file="$1"
  local expression="$2"
  "$PYTHON" -c "import json,sys; data=json.load(open(sys.argv[1], encoding='utf-8')); print($expression)" "$file"
}

PAYLOAD="$("$PYTHON" -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$QUERY")"

echo "Submitting: $QUERY"
HTTP_CODE="$(curl -sS -o "$TMP_DIR/create.json" -w '%{http_code}' \
  -X POST "$API_BASE_URL/v1/video-jobs" \
  -H "Content-Type: application/json" \
  "${AUTH_ARGS[@]}" \
  --data "$PAYLOAD")"

if [[ "$HTTP_CODE" != "202" ]]; then
  echo "ERROR: job creation returned HTTP $HTTP_CODE" >&2
  "$PYTHON" -m json.tool "$TMP_DIR/create.json" >&2 || cat "$TMP_DIR/create.json" >&2
  exit 1
fi

JOB_ID="$(json_value "$TMP_DIR/create.json" 'data["job_id"]')"
CONCEPT_ID="$(json_value "$TMP_DIR/create.json" 'data.get("concept_id") or "unknown"')"
echo "Job ID:     $JOB_ID"
echo "Concept:    $CONCEPT_ID"
echo "Status URL: $API_BASE_URL/v1/video-jobs/$JOB_ID"
echo "Polling..."

STARTED="$(date +%s)"
LAST_LINE=""
while true; do
  HTTP_CODE="$(curl -sS -o "$TMP_DIR/status.json" -w '%{http_code}' \
    "${AUTH_ARGS[@]}" \
    "$API_BASE_URL/v1/video-jobs/$JOB_ID")"
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "ERROR: status request returned HTTP $HTTP_CODE" >&2
    "$PYTHON" -m json.tool "$TMP_DIR/status.json" >&2 || cat "$TMP_DIR/status.json" >&2
    exit 1
  fi

  IFS='|' read -r STATUS STAGE PROGRESS < <(
    "$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print("{}|{}|{}".format(d["status"], d["stage"], d["progress"]))' "$TMP_DIR/status.json"
  )
  LINE="status=$STATUS stage=$STAGE progress=$PROGRESS"
  if [[ "$LINE" != "$LAST_LINE" ]]; then
    echo "  $LINE"
    LAST_LINE="$LINE"
  fi

  case "$STATUS" in
    completed)
      break
      ;;
    failed|canceled)
      echo "ERROR: job ended with status '$STATUS'" >&2
      "$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); e=d.get("error") or {}; print("  {}: {}".format(e.get("code", "UNKNOWN"), e.get("message", "no error message")))' "$TMP_DIR/status.json" >&2
      exit 1
      ;;
  esac

  NOW="$(date +%s)"
  if (( NOW - STARTED > POLL_TIMEOUT_SECONDS )); then
    echo "ERROR: timed out after ${POLL_TIMEOUT_SECONDS}s" >&2
    exit 1
  fi
  sleep 2
done

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="$ROOT_DIR/downloads/$JOB_ID.mp4"
fi
mkdir -p "$(dirname "$OUTPUT")"

echo "Downloading video..."
curl -fsSL "${AUTH_ARGS[@]}" \
  "$API_BASE_URL/v1/video-jobs/$JOB_ID/artifact/video.mp4" \
  -o "$OUTPUT"

OUTPUT_ABS="$("$PYTHON" -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT")"
echo "Artifact:   $OUTPUT_ABS"
echo "Metadata:   $API_BASE_URL/v1/video-jobs/$JOB_ID/artifact"
