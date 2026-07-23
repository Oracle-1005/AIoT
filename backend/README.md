# Backend

PC-side Flask + SQLite backend using the confirmed Pi ↔ PC architecture:

- PC is a TCP server; Raspberry Pi is the client.
- Transport is TCP + JSON Lines on port `9000` by default.
- Uplink types: `fused_frame`, `window_features`, `control_event`, `status`.
- Internal `payload` fields remain flexible until the hardware schema is final.
- LED/system commands are sent back over the same TCP connection.
- Sonic Pi is controlled through OSC on the local PC.
- MQTT is no longer part of the active architecture.

## Run

```powershell
cd G:\code\AIoT\AIoT
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe backend\test_backend.py
backend\.venv\Scripts\python.exe backend\app.py
```

The PC listens on:

- Flask: `0.0.0.0:5000`
- Pi gateway: `0.0.0.0:9000`
- Sonic Pi feedback OSC: `127.0.0.1:4561`

## Verify live Pi data

After starting `backend/app.py` and the Raspberry Pi `fusion_pipeline`, run:

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 30
```

The verifier polls:

- `GET /api/status`
- `GET /api/pi/status`
- `GET /api/sensors/live`

It prints the TCP gateway connection state, Pi message counters, camera status,
left/right micro:bit status, and the latest control event. A successful run
should show:

- `gateway_running=yes`
- `pi_connected=yes`
- `status` counter increasing
- `fused_frame` counter increasing when the camera fusion service is running
- `control_event` counter increasing after pressing a micro:bit button

For a stricter check that requires both fused camera frames and button events:

```powershell
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 60 --require status --require fused_frame --require control_event
```

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
- `GET /api/sonic-pi/status`
- `POST /api/sonic-pi/transport`
- `POST /api/sonic-pi/state`

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

## Sonic Pi integration

Open Sonic Pi, paste and run:

```text
../music/sonic_pi/aiot_conductor_ode_to_joy.rb
```

The backend sends OSC commands to Sonic Pi at `127.0.0.1:4560` and listens for
Sonic Pi feedback on `127.0.0.1:4561`.

Control events automatically map to Sonic Pi:

- `downbeat`, `left_wrist_strike`, `right_wrist_strike`: accent + start
- `tempo_up`, `tempo_down`: BPM update
- `crescendo`, `decrescendo`: volume/energy state update
- `cutoff`, `stop`, `gesture_end`: cutoff/pause

The frontend still reads `/api/music/state`; once Sonic Pi returns
`/music/state` or `/music/beat`, the same endpoint includes the actual BPM,
section, beat, and Sonic Pi connection state.

## Model integration

`window_features` is stored and exposed immediately, but automatic inference
is disabled until its fields are finalized. Set
`AIOT_AUTO_INFER_WINDOW_FEATURES=1` after the model input contract is fixed.
