"""Message schemas — compatible with PC backend message_router.py + state.py.

Three output types:
  - fused_frame: camera-triggered sensor fusion (per camera frame)
  - microbit_control_event: micro:bit button events (fast path, event-driven)
  - status: system health (1 Hz)

Format is aligned with backend expectations:
  - fused_frame.payload.microbits[] — list with "hand" field
  - status.payload.microbits.left / .right — nested per-side
"""

# ── fused_frame ────────────────────────────────────────────────────────────

FUSED_FRAME_TEMPLATE = {
    "type": "fused_frame",
    "schema_version": "1.0",
    "fused_sequence": 0,
    "pi_aligned_timestamp_ns": 0,
    "camera": {
        "available": False,
        "frame_sequence": 0,
        "time_delta_ms": 0.0,
        "hands_detected": 0,
        "hands": [],
    },
    "microbits": [
        # Each entry: {"hand": "left"|"right", "available": bool, "sample_sequence": int, ...}
    ],
    "fusion_quality": {
        "max_time_delta_ms": 0.0,
        "missing_sources": [],
        "camera_quality_flags": [],
        "microbit_quality_flags": [],
    },
}

# ── microbit_control_event ─────────────────────────────────────────────────

CONTROL_EVENT_TEMPLATE = {
    "type": "microbit_control_event",
    "source": "",
    "event_sequence": 0,
    "device_timestamp_ms": 0,
    "pi_rx_monotonic_ns": 0,
    "event_code": "",
    "priority": 0,
    "repeat_index": 0,
    "repeat_total": 0,
    "duplicate": False,
    "mapped_candidate": "",
    "gateway": {
        "source_ip": "",
        "ble_rssi": 0,
        "flags": 0,
    },
}

# ── status ─────────────────────────────────────────────────────────────────

STATUS_TEMPLATE = {
    "type": "status",
    "schema_version": "1.0",
    "pi_timestamp_ns": 0,
    "microbits": {
        "left": {
            "connected": False,
            "age_ms": 0.0,
            "rssi": 0,
            "missing_sample_count": 0,
        },
        "right": {
            "connected": False,
            "age_ms": 0.0,
            "rssi": 0,
            "missing_sample_count": 0,
        },
    },
    "camera": {
        "fps": 0.0,
        "hands_detected": 0,
        "dropped_capture_frames": 0,
        "clock_ready": False,
    },
    "jitter": {
        "configured_delay_ms": 0.0,
        "pending_frames": 0,
    },
}

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_MAX_AGE_MS = 120
DEFAULT_BUFFER_MAX_AGE_S = 10

SEQUENCE_STATUS_VALID = {"in_order", "sequence_gap", "first_sample", "device_restart"}
