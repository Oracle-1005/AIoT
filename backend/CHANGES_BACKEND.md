# Backend changes for BACKEND_TASKS11 (2026-07-24)

- Changed the fused-frame inference bridge to be camera-primary at about 30 FPS.
- Routed camera observations into independent left/right sliding windows.
- Made inference readiness and cadence depend on camera frames, not sparse IMU samples.
- Kept micro:bit data as an optional auxiliary channel and deduplicated it by `sample_sequence`.
- Added `available` metadata and a zero-valued placeholder when one hand has no micro:bit data.
- Passed raw windows under `camera_features`, `microbit_features`, and `cross_modal_features`; feature calculation remains model-side.
- Preserved the `window_features` compatibility route and its environment switch.
- Preserved all existing REST endpoints and existing response fields; inference status fields remain additive.
- Retained the frozen `led_command` schema, RF-label mapping, Sonic Pi integration, and age-based connectivity fix from the first revision.

Validation performed for this package:

- `python -m compileall backend` passes.
- A model-stub test confirms camera-driven inference, per-hand routing, micro:bit duplicate removal, and zero-placeholder behavior.
