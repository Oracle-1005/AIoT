# Backend

Flask + SQLite + MQTT implementation following the original
`docs/INTERFACE_CONTRACT.md`.

## Implemented endpoints

- `GET /api/status`
- `GET /api/gesture/current`
- `GET /api/gesture/history?limit=20&since=<unix_timestamp>`
- `GET /api/sensors/live`
- `GET /api/music/state`

No HTTP model-inference endpoint is introduced. Interface ③ remains an
in-process Python import.

## Setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open:

```text
http://localhost:5000/api/status
```

Expected initial result:

```json
{
  "status": "ok",
  "camera_connected": false,
  "microbit_left": false,
  "microbit_right": false,
  "model_loaded": false,
  "uptime_seconds": 1
}
```

`model_loaded` remains `false` until the model owner provides
`model/inference` and the model file.

## Database test

From `backend/`:

```powershell
python database.py
```

The database is created at `<project-root>/data/aiot.db` by default. This is
portable across PC and Raspberry Pi. Override it with `AIOT_DB_PATH`.

Run all first-week API checks:

```powershell
python test_backend.py
```

## MQTT

MQTT is disabled by default so local Flask development does not fail when the
Pi 5 broker is unavailable.

PowerShell example:

```powershell
$env:AIOT_MQTT_ENABLED = "1"
$env:AIOT_MQTT_HOST = "<Pi5-IP>"
$env:AIOT_MQTT_PORT = "1883"
$env:AIOT_MQTT_TOPIC = "aiot/gesture"
python app.py
```

The backend publishes the exact Interface ⑥ payload to `aiot/gesture`.

## Model integration (Interface ③)

The model owner should provide:

```python
from model.inference import GestureClassifier

classifier = GestureClassifier(model_path="model/models/gesture_classifier.pkl")
result = classifier.predict(window_data)
```

`backend/model_service.py` loads that class. The joint in-process pipeline can
call:

```python
from integration import run_prediction

result = run_prediction(window_data)
```

This performs:

1. `GestureClassifier.predict(window_data)`
2. SQLite insertion
3. live-state update
4. MQTT publication

If the model pipeline already produced the result dictionary, it can call:

```python
from integration import accept_prediction

accept_prediction(result)
```

The result must follow Interface ③ section 4.3.

## Sensor integration

The BLE/MediaPipe pipeline can update the backend in-process:

```python
from integration import update_camera, update_microbit

update_microbit("L", acc_x=-128, acc_y=32, acc_z=-1024, pc_ts=1721052000.12)
update_microbit("R", acc_x=64, acc_y=-16, acc_z=-980, pc_ts=1721052000.13)
update_camera(hand_data={"hands": []}, hand_count=0, pc_ts=1721052000.14)
```

These calls update `/api/sensors/live` and persist `sensor_records`.
