#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/aiot_conductor/project}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8787}"
LOG_LEVEL="${LOG_LEVEL:-WARNING}"

RECEIVER_DIR="$PROJECT_ROOT/hardware/raspberry_pi/esp32_ble_gateway_to_Pi"
PREVIEW_SCRIPT="$PROJECT_ROOT/hardware/microbit/microbit_to_pi/tools/live_preview_server.py"
CONFIG="${CONFIG:-$RECEIVER_DIR/config.json}"

if [[ -x "$PROJECT_ROOT/camera_to_Pi/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/camera_to_Pi/.venv/bin/python"
elif [[ -x "$PROJECT_ROOT/hardware/raspberry_pi/camera_to_Pi/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/hardware/raspberry_pi/camera_to_Pi/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi

if [[ ! -f "$CONFIG" ]]; then
  cp "$RECEIVER_DIR/config.example.json" "$CONFIG"
fi

exec "$PYTHON_BIN" "$PREVIEW_SCRIPT" \
  --receiver-dir "$RECEIVER_DIR" \
  --config "$CONFIG" \
  --python "$PYTHON_BIN" \
  --receiver-module esp32_gateway_receiver.app \
  --host "$HOST" \
  --port "$PORT" \
  --pid-file "/tmp/microbit_esp32_preview_${PORT}.pid" \
  --log-level "$LOG_LEVEL"
