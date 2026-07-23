"""YAML configuration loader with deep-merge defaults."""

import os
import yaml
from copy import deepcopy


DEFAULT_CONFIG = {
    "microbits": [
        {"device_id": "MB_LEFT", "hand": "left", "address": ""},
        {"device_id": "MB_RIGHT", "hand": "right", "address": ""},
    ],
    "microbit": {
        "target_sample_rate_hz": 25,
        "ble_scan_timeout_s": 5.0,
    },
    "camera": {
        "width": 640,
        "height": 480,
        "fps": 30,
        "max_hands": 2,
        "frame_queue_size": 10,
    },
    "fusion": {
        "buffer_maxlen": 500,
        "buffer_max_age_s": 10.0,
        "max_bracket_span_ms": 100,
        "max_sample_age_ms": 120,
        "timestamp_alignment_tolerance_ms": 50,
        "min_sync_points": 5,
        "max_sync_points": 20,
        "initial_sync_rounds": 15,
        "resync_interval_s": 15,
        "sync_outlier_rtt_factor": 2.0,
        "loss_window_size": 100,
        "max_gap_interpolate": 3,
        "window_ms": 800,
        "hop_ms": 100,
        "event_cooldown_ms": 200,
        "jerk_threshold_g_s": 5.0,
        "bpm_min": 60,
        "bpm_max": 200,
    },
    "pi_to_pc": {
        "host": "192.168.1.100",
        "port": 9000,
        "reconnect_delay_s": 2.0,
        "max_queue_size": 500,
        "connect_timeout_s": 5.0,
        "fused_frame_max_hz": 25,
        "window_features_hz": 10,
        "status_hz": 1,
    },
    "led": {
        "enabled": False,
        "gpio": 19,
        "panel_count": 2,
        "led_per_panel": 256,
        "brightness_limit": 0.25,
        "refresh_hz": 50,
        "dma_channel": 10,
        "pwm_freq_hz": 800000,
    },
    "general": {
        "pi_id": "raspberrypi-01",
        "schema_version": "1.1",
        "status_interval_s": 1.0,
        "log_level": "INFO",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Returns new dict."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(path: str = "config.yaml") -> dict:
    """Load YAML config file, merging with DEFAULT_CONFIG for missing keys.

    Args:
        path: Path to the YAML config file.

    Returns:
        Merged configuration dict.
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        return _deep_merge(DEFAULT_CONFIG, user_config)
    else:
        # No user config file, return defaults
        return deepcopy(DEFAULT_CONFIG)


def save_default_config(path: str = "config.yaml") -> None:
    """Write the default configuration to a YAML file.

    Args:
        path: Destination path for the config file.
    """
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
