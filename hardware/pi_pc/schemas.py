"""JSON schema definitions, field constants, and message templates.

Defines all valid values for message types, event types, hand labels,
LED patterns, and invalid reasons. Also provides template dicts for
each of the 3 message types to ensure consistent field presence.

Three message types are sent to PC:
  - fused_frame: real-time synchronized sensor fusion (20-30 Hz)
  - control_event: discrete action/gesture events (event-driven)
  - status: system health monitoring (1 Hz)
"""

# ---- Message types ----
MESSAGE_TYPES = ["fused_frame", "control_event", "status"]

# ---- Event types ----
EVENT_TYPES = [
    "downbeat",
    "left_wrist_strike",
    "right_wrist_strike",
    "bilateral_strike",
    "gesture_start",
    "gesture_end",
    "stop",
    "resume",
]

# ---- Hand labels ----
HAND_VALUES = ["left", "right", "both", "none", "unknown"]

# ---- LED animation patterns ----
LED_PATTERNS = [
    "left_pulse",
    "right_pulse",
    "bilateral_pulse",
    "wave",
    "breathing",
    "clear",
]

# ---- Invalid reasons (for quality.reason field) ----
INVALID_REASONS = [
    "clock_not_ready",
    "ble_sample_too_old",
    "no_bracket",
    "bracket_too_wide",
    "interpolation_failed",
    "camera_frame_missing",
    "left_ble_disconnected",
    "right_ble_disconnected",
    "window_not_filled",
    "camera_missing",
    "sync_error_too_large",
    "insufficient_samples",
]

# ---- Motion directions ----
MOTION_DIRECTIONS = ["up", "down", "left", "right", "forward", "backward", "still"]

# ---- Message templates ----
# These provide default empty structures so that all fields are always
# present in outgoing JSON, even when data is partial.

FUSED_FRAME_TEMPLATE = {
    "schema_version": "1.1",
    "message_type": "fused_frame",
    "session_id": "",
    "packet_sequence": 0,
    "pi_id": "raspberrypi-01",
    "timestamps": {
        "fusion_target_timestamp_ns": 0,
        "pi_packet_created_mono_ns": 0,
        "pi_unix_time_ns": 0,
    },
    "camera": {
        "source": "camera",
        "frame_id": 0,
        "sensor_timestamp_ns": 0,
        "mediapipe_timestamp_ms": 0,
        "width": 640,
        "height": 480,
        "configured_fps": 30,
        "processing_latency_ms": 0.0,
        "hands": [],
    },
    "microbits": [],
    "fusion": {
        "valid": False,
        "alignment_method": "camera_timestamp_target",
        "camera_valid": False,
        "left_microbit_valid": False,
        "right_microbit_valid": False,
        "cross_modal_features": {
            "beat_candidate": False,
            "beat_strength": 0.0,
            "vision_imu_consistency": 0.0,
            "combined_motion_intensity": 0.0,
        },
    },
}

CONTROL_EVENT_TEMPLATE = {
    "schema_version": "1.1",
    "message_type": "control_event",
    "session_id": "",
    "packet_sequence": 0,
    "pi_id": "raspberrypi-01",
    "timestamps": {
        "pi_packet_created_mono_ns": 0,
        "pi_unix_time_ns": 0,
    },
    "event_id": "",
    "event": {
        "type": "",
        "hand": "none",
        "confidence": 0.0,
        "strength": 0.0,
    },
    "music_control": {
        "estimated_bpm": 0.0,
        "tempo_delta": 0.0,
        "volume": 0.0,
        "intensity": 0.0,
        "articulation": 0.5,
    },
    "led_control": {
        "pattern": "clear",
        "brightness": 0.0,
        "duration_ms": 0,
    },
}

STATUS_TEMPLATE = {
    "schema_version": "1.1",
    "message_type": "status",
    "session_id": "",
    "packet_sequence": 0,
    "pi_id": "raspberrypi-01",
    "timestamps": {
        "pi_packet_created_mono_ns": 0,
        "pi_unix_time_ns": 0,
    },
    "camera": {
        "connected": False,
        "configured_fps": 30,
        "actual_fps": 0.0,
        "dropped_frames": 0,
        "last_frame_age_ms": 0.0,
        "processing_latency_ms": 0.0,
    },
    "microbits": {
        "left": {
            "device_id": "MB_LEFT",
            "transport": "ble",
            "connected": False,
            "rssi_dbm": 0,
            "sample_rate_hz": 0.0,
            "recent_loss_ratio": 0.0,
            "clock_ready": False,
            "sync_rtt_ms": 0.0,
            "last_sample_age_ms": 0.0,
        },
        "right": {
            "device_id": "MB_RIGHT",
            "transport": "ble",
            "connected": False,
            "rssi_dbm": 0,
            "sample_rate_hz": 0.0,
            "recent_loss_ratio": 0.0,
            "clock_ready": False,
            "sync_rtt_ms": 0.0,
            "last_sample_age_ms": 0.0,
        },
    },
    "network": {
        "pc_connected": False,
        "queued_messages": 0,
        "dropped_messages": 0,
        "send_rate_hz": 0.0,
        "reconnect_count": 0,
    },
    "led": {
        "connected": False,
        "backend": "rpi_ws281x",
        "gpio": 18,
        "panel_count": 2,
        "total_leds": 512,
        "brightness_limit": 0.25,
        "actual_brightness": 0.0,
        "fps": 50,
        "error": None,
    },
}
