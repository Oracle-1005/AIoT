"""Validation and dispatch for Pi -> PC uplink messages.

The Pi currently sends four message types:

- fused_frame
- window_features
- control_event
- status

Payload fields remain flexible because the hardware-side internal schema may
continue to evolve.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from coordinate_recognizer import coordinate_recognizer
from database import insert_pi_message
from inference_pipeline import inference_pipeline
from integration import send_pi_command
from sonic_pi import sonic_pi_adapter
from state import live_state

logger = logging.getLogger(__name__)

UPLINK_MESSAGE_TYPES = frozenset({
    "fused_frame",
    "window_features",
    "control_event",
    "status",
})

# ── micro:bit 按键 → LED 即时视觉反馈 ────────────────────────────────────
# 设计（GESTURE_CONDUCTOR_DESIGN）：cutoff=instant_black、急停=emergency_red、
# style_switch=palette_sweep——映射到现有灯效实现。按键是刻意操作，
# 不走 AIOT_LED_AUTO 开关/节流；本开关独立，默认开。
CONTROL_EVENT_LED_ENABLED = os.getenv("AIOT_BUTTON_LED_ENABLED", "1").lower() in {
    "1", "true", "yes", "on",
}
CONTROL_EVENT_LED_BRIGHTNESS = max(
    0.0, min(1.0, float(os.getenv("AIOT_BUTTON_LED_BRIGHTNESS", "0.5")))
)
CONTROL_EVENT_LED_DURATION_MS = max(
    0, int(os.getenv("AIOT_BUTTON_LED_DURATION_MS", "3000"))
)
CONTROL_EVENT_LED_EFFECTS = {
    "resume": "gesture_start",        # 左A短按 继续 → 绿色 wipe
    "cutoff": "off",                  # 左B短按 暂停 → 立即熄灭（instant_black）
    "stop": "stop",                   # 右B长按 急停 → 全红闪（emergency_red）
    "style_switch": "wave",           # 右A短按 风格切换 → 波动扫过（palette_sweep）
    "gesture_start": "gesture_start",  # A+B长按 开始 → 绿色 wipe
}

COMMON_FIELDS = {
    "schema_version",
    "message_type",
    "type",
    "session_id",
    "packet_sequence",
    "sequence",
    "pi_id",
    "timestamps",
    "timestamp",
    "payload",
}


def normalize_uplink_message(
    message: dict[str, Any],
) -> dict[str, Any]:
    message_type = message.get(
        "message_type",
        message.get("type"),
    )

    if (
        not isinstance(message_type, str)
        or message_type not in UPLINK_MESSAGE_TYPES
    ):
        raise ValueError(
            "message_type must be one of "
            f"{sorted(UPLINK_MESSAGE_TYPES)}"
        )

    payload = message.get("payload")

    if payload is None:
        # Compatibility with messages that place business fields
        # directly at the top level.
        payload = {
            key: value
            for key, value in message.items()
            if key not in COMMON_FIELDS
        }

    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    received_at = time.time()

    return {
        "schema_version": str(
            message.get("schema_version", "draft")
        ),
        "message_type": message_type,
        "session_id": message.get("session_id"),
        "packet_sequence": message.get(
            "packet_sequence",
            message.get("sequence"),
        ),
        "pi_id": message.get("pi_id"),
        "timestamps": message.get("timestamps", {}),
        "timestamp": message.get("timestamp"),
        "payload": payload,
        "received_at": received_at,
        "raw": message,
    }


def route_uplink_message(
    message: dict[str, Any],
    address: tuple[str, int],
) -> None:
    normalized = normalize_uplink_message(message)

    normalized["source_address"] = (
        f"{address[0]}:{address[1]}"
    )

    insert_pi_message(normalized)
    live_state.record_pi_message(normalized)

    message_type = normalized["message_type"]
    payload = normalized["payload"]
    received_at = normalized["received_at"]

    if message_type == "status":
        live_state.apply_pi_status(payload)

    elif message_type == "fused_frame":
        live_state.apply_fused_frame(
            payload,
            received_at,
            source_ip=address[0] if address else None,
        )
        inference_pipeline.process_fused_frame(payload, received_at)
        # 坐标手势识别器（规则化，替代旧 ML 手势的音乐控制）
        coordinate_recognizer.process_frame(payload, received_at)

    elif message_type == "window_features":
        inference_pipeline.process_window_features(payload)

    elif message_type == "control_event":
        live_state.apply_control_event(
            payload,
            received_at,
        )
        sonic_pi_adapter.publish_control_event(
            payload,
            live_state.get_music(),
        )
        _maybe_send_control_event_led(payload)


def _maybe_send_control_event_led(payload: dict[str, Any]) -> None:
    """micro:bit 按键的 LED 即时反馈（best-effort，失败不影响路由）。"""
    if not CONTROL_EVENT_LED_ENABLED:
        return
    event = payload.get("event", {})
    if not isinstance(event, dict):
        return
    gesture = str(event.get("type", "")).strip()
    effect = CONTROL_EVENT_LED_EFFECTS.get(gesture)
    if effect is None:
        return
    try:
        send_pi_command("led_command", {
            "effect": effect,
            "brightness": CONTROL_EVENT_LED_BRIGHTNESS,
            "duration_ms": CONTROL_EVENT_LED_DURATION_MS,
            "source": "button",
        })
    except Exception:
        logger.exception("control_event LED feedback failed for %r", gesture)
