# AIoT Hardware Project Structure

**Last updated**: 2026-07-23

This document records the current hardware-side project layout after unifying
the Raspberry Pi runtime root to:

```text
/home/ag1_client/aiot_conductor/project
```

The Raspberry Pi uses the existing camera virtual environment:

```text
/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python
```

Do not use `/home/ag1_client/aiot_project` as an active runtime root. Its
previous contents have been migrated or archived as legacy material.

## Raspberry Pi Runtime Layout

```text
/home/ag1_client/aiot_conductor/project/
├── camera_to_Pi/                         # Existing camera runtime folder
│   ├── .venv/                            # Unified Python environment
│   ├── camera_to_pi/                     # Original camera package
│   ├── models/                           # Camera preview model assets
│   ├── config.json
│   └── visual_verify.py                  # Camera visual preview entry
│
├── hardware/
│   ├── fusion_pipeline/                  # Integrated camera + micro:bit fusion
│   │   ├── main.py                       # Fusion service entry
│   │   ├── config.yaml                   # UDP/TCP/camera/fusion settings
│   │   ├── gateway_adapter.py            # ESP32 UDP receiver adapter
│   │   ├── camera_adapter.py             # CameraSensor adapter
│   │   ├── fusion_engine.py              # Jitter-buffered fusion engine
│   │   ├── time_aligner.py               # Nearest-neighbor time alignment
│   │   ├── tcp_client.py                 # TCP JSONL uplink to PC backend
│   │   └── pi-fusion.service             # systemd unit template
│   │
│   ├── pi_pc/                            # Shared Pi-side processing helpers
│   │   ├── camera_clock.py               # Camera timestamp alignment
│   │   ├── cleaner.py                    # Gap / sequence cleaning helpers
│   │   └── noise_filter.py               # IMU noise filtering
│   │
│   ├── sensors/                          # Hardware abstraction modules
│   │   ├── base.py
│   │   └── camera.py                     # Picamera2 + MediaPipe camera sensor
│   │
│   ├── raspberry_pi/
│   │   ├── camera_to_Pi/                 # Canonical camera source copy
│   │   ├── esp32_ble_gateway_to_Pi/      # ESP32 UDP frame receiver package
│   │   ├── microbit_to_Pi/               # micro:bit packet protocol/parser
│   │   ├── MICROBIT_ESP32_CAMERA_DATA_FLOW.md
│   │   └── PI_PROJECT_LED_HANDOFF.md
│   │
│   ├── raspberry_pi_iot/
│   │   └── led/                          # Reserved LED strip control module
│   │
│   ├── esp32/
│   │   └── microbit_ble_wifi_gateway/    # ESP32 Arduino gateway firmware
│   │
│   ├── microbit/
│   │   └── microbit_to_pi/               # Current micro:bit MakeCode broadcast firmware
│   │
│   └── utils/
│
├── models/                               # Shared model assets for fusion/backend handoff
└── legacy/                               # Archived old top-level Pi scripts
```

## PC Repository Hardware Layout

```text
hardware/
├── FUSION_PIPELINE_DEPLOY.md             # Deployment and validation guide
├── END_TO_END_TRANSMISSION_VERIFICATION.md # Full PC/Pi validation flow
├── PI_BACKEND_COMMUNICATION_PLAN.md      # Pi <-> PC backend communication plan
├── PROJECT_STRUCTURE.md                  # This structure record
├── requirements.txt
│
├── fusion_pipeline/                      # Pi fusion runtime source
├── pi_pc/                                # Shared filtering / clock-sync helpers
├── sensors/                              # Camera hardware abstraction
├── raspberry_pi/                         # Pi-specific receivers, docs, camera preview
├── raspberry_pi_iot/                     # LED strip control reservation
├── esp32/                                # ESP32 gateway firmware
├── microbit/                             # micro:bit firmware
│   ├── microbit_to_pi/                   # Active BLE broadcast firmware
│   └── legacy_ble_connection_tests/      # Archived direct BLE experiments
│
├── ble/                                  # Earlier BLE receiver experiments
├── features/                             # Earlier feature extraction experiments
├── fusion/                               # Earlier fusion experiments
├── messages/                             # Earlier message schema experiments
├── transport/                            # Earlier transport experiments
└── tests/                                # Earlier hardware unit tests
```

## Current Runtime Notes

- `pi-fusion.service` now runs from
  `/home/ag1_client/aiot_conductor/project/hardware/fusion_pipeline`.
- The service uses
  `/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python`.
- The active PC backend receiver is `backend/pi_gateway.py`, listening on TCP
  port `9000` when `backend/app.py` is running.
- The active micro:bit path is the ESP32 broadcast gateway:
  `micro:bit -> BLE broadcast -> ESP32 -> UDP:17778 -> Pi`.
- Camera preview and micro:bit live preview are validation tools. They should
  be stopped before starting `pi-fusion.service`, because the fusion service
  needs UDP `17778` and the Pi Camera resource.
