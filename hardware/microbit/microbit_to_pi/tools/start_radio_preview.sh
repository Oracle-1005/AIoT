#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/aiot_conductor/project}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8787}"
FUSION_STATE_URL="${FUSION_STATE_URL:-http://127.0.0.1:8790/state}"
PREVIEW_SCRIPT="$PROJECT_ROOT/hardware/microbit/microbit_to_pi/tools/live_preview_server.py"
PYTHON_BIN="$PROJECT_ROOT/camera_to_Pi/.venv/bin/python"

exec "$PYTHON_BIN" "$PREVIEW_SCRIPT" \
  --fusion-state-url "$FUSION_STATE_URL" \
  --host "$HOST" \
  --port "$PORT" \
  --pid-file "/tmp/microbit_radio_preview_${PORT}.pid"
