"""Integration helpers for the PC-side model and legacy local test pipelines."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from database import insert_prediction, insert_sensor_record
from model_service import model_service
from gesture_mapping import normalize_prediction
from pi_gateway import pi_gateway
from sonic_pi import sonic_pi_adapter
from state import live_state

# ── 预测自动联动 LED（默认关；AIOT_LED_AUTO_* 环境变量控制）────────────────
# 推理步长 3 帧 ≈ 每秒最多 ~10 次预测，必须冷却防灯板频闪；只有真正发出去
# 才占用冷却（Pi 离线时 send 返回 False，下个预测周期自动重试）。
LED_AUTO_ENABLED = os.getenv("AIOT_LED_AUTO_ENABLED", "0").lower() in {
    "1", "true", "yes", "on",
}
LED_AUTO_MIN_CONFIDENCE = float(os.getenv("AIOT_LED_AUTO_MIN_CONFIDENCE", "0.6"))
LED_AUTO_COOLDOWN_S = float(os.getenv("AIOT_LED_AUTO_COOLDOWN_S", "2.0"))
LED_AUTO_BRIGHTNESS = max(0.0, min(1.0, float(os.getenv("AIOT_LED_AUTO_BRIGHTNESS", "0.5"))))
LED_AUTO_DURATION_MS = max(0, int(os.getenv("AIOT_LED_AUTO_DURATION_MS", "3000")))
LED_AUTO_SKIP_GESTURES = frozenset(
    g.strip()
    for g in os.getenv("AIOT_LED_AUTO_SKIP_GESTURES", "idle").split(",")
    if g.strip()
)
_led_auto_lock = threading.Lock()
_led_auto_last = {"at": 0.0, "gesture": None}


def run_prediction(window_data: Any) -> dict[str, Any]:
    result = normalize_prediction(model_service.predict(window_data))
    accept_prediction(result)
    return result


def accept_prediction(result: dict[str, Any]) -> None:
    insert_prediction(result, latency_ms=result.get("latency_ms"))
    live_state.set_prediction(result)
    sonic_pi_adapter.publish_prediction(result, live_state.get_music())
    _maybe_send_led(result)


def _maybe_send_led(result: dict[str, Any]) -> bool:
    """预测达标时自动下发 led_command；各种过滤不满足时静默跳过。"""
    if not LED_AUTO_ENABLED:
        return False
    gesture = result.get("gesture")
    if not gesture or gesture in LED_AUTO_SKIP_GESTURES:
        return False
    try:
        confidence = float(result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False
    if confidence < LED_AUTO_MIN_CONFIDENCE:
        return False
    now = time.time()
    with _led_auto_lock:
        if now - _led_auto_last["at"] < LED_AUTO_COOLDOWN_S:
            return False
        sent = send_pi_command("led_command", {
            "effect": gesture,
            "brightness": LED_AUTO_BRIGHTNESS,
            "duration_ms": LED_AUTO_DURATION_MS,
            "source": "backend-auto",
        })
        if sent:
            _led_auto_last["at"] = now
            _led_auto_last["gesture"] = gesture
    return sent


def send_pi_command(message_type: str, payload: dict[str, Any], **metadata: Any) -> bool:
    """Send a downlink command over the existing Pi TCP connection."""
    allowed = {"led_command", "led_state", "led_config", "system_command", "time_sync"}
    if message_type not in allowed:
        raise ValueError(f"message_type must be one of {sorted(allowed)}")
    message = {"message_type": message_type, "payload": payload, **metadata}
    return pi_gateway.send(message)


def update_microbit(device_id: str, *, acc_x: float, acc_y: float, acc_z: float,
                    pc_ts: float | None = None) -> None:
    device = device_id.upper()
    if device not in {"L", "R"}: raise ValueError("device_id must be 'L' or 'R'")
    timestamp = float(pc_ts if pc_ts is not None else time.time())
    sample = {"acc_x": float(acc_x), "acc_y": float(acc_y), "acc_z": float(acc_z)}
    insert_sensor_record(pc_ts=timestamp, device_id=device, **sample)
    if device == "L": live_state.update_sensors(microbit_left=sample, timestamp=timestamp)
    else: live_state.update_sensors(microbit_right=sample, timestamp=timestamp)


def update_camera(hand_data: dict[str, Any] | list[Any], *, hand_count: int,
                  pc_ts: float | None = None) -> None:
    timestamp = float(pc_ts if pc_ts is not None else time.time())
    insert_sensor_record(pc_ts=timestamp, device_id="camera", hand_data=hand_data)
    live_state.update_sensors(hand_detected=hand_count > 0, hand_count=hand_count, timestamp=timestamp)
