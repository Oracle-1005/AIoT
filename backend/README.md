# Backend

PC-side Flask + SQLite backend using the confirmed Pi ↔ PC architecture:

- PC is a TCP server; Raspberry Pi is the client.
- Transport is TCP + JSON Lines on port `9000` by default.
- Uplink types: `fused_frame`, `window_features`, `control_event`, `status`.
- Internal `payload` fields remain flexible until the hardware schema is final.
- LED/system commands are sent back over the same TCP connection.
- MQTT is no longer part of the active architecture.

## Run

```powershell
cd backend
C:\AIoT\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt
C:\AIoT\backend\.venv\Scripts\python.exe test_backend.py
C:\AIoT\backend\.venv\Scripts\python.exe app.py
```

The PC listens on:

- Flask: `0.0.0.0:5000`
- Pi gateway: `0.0.0.0:9000`

## Pi uplink envelope

One JSON object per line:

```json
{"schema_version":"draft","message_type":"status","session_id":"session-001","packet_sequence":1,"payload":{}}
```

The parser also temporarily accepts `type` instead of `message_type`, and
messages without an explicit `payload`, to reduce coupling while fields are
still being agreed.

## REST endpoints

Existing:

- `GET /api/status`
- `GET /api/gesture/current`
- `GET /api/gesture/history`
- `GET /api/sensors/live`
- `GET /api/music/state`

Added:

- `GET /api/pi/status`
- `GET /api/pi/messages?message_type=status&limit=50`
- `POST /api/pi/send`

Downlink example:

```json
{
  "message_type": "led_command",
  "payload": {
    "effect": "accent_flash",
    "strength": 0.9,
    "duration_ms": 120
  }
}
```

Allowed downlink types are `led_command`, `led_state`, `led_config`,
`system_command`, and `time_sync`.

## Model integration

`window_features` is stored and exposed immediately, but automatic inference
is disabled until its fields are finalized. Set
`AIOT_AUTO_INFER_WINDOW_FEATURES=1` after the model input contract is fixed.
