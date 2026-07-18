"""Validation and dispatch for Pi -> PC uplink messages.

Payload fields intentionally remain flexible until the hardware schema is
finalized.  Only the common envelope and four agreed message types are fixed.
"""

from __future__ import annotations

import os
import time
from typing import Any

from database import insert_pi_message
from integration import accept_prediction
from model_service import model_service
from state import live_state

UPLINK_MESSAGE_TYPES = frozenset({"fused_frame", "window_features", "control_event", "status"})
AUTO_INFER_WINDOW_FEATURES = os.getenv("AIOT_AUTO_INFER_WINDOW_FEATURES", "0").lower() in {
    "1", "true", "yes", "on"
}

COMMON_FIELDS = {
    "schema_version", "message_type", "type", "session_id", "packet_sequence",
    "sequence", "pi_id", "timestamps", "timestamp", "payload",
}


def normalize_uplink_message(message: dict[str, Any]) -> dict[str, Any]:
    message_type = message.get("message_type", message.get("type"))
    if not isinstance(message_type, str) or message_type not in UPLINK_MESSAGE_TYPES:
        raise ValueError(f"message_type must be one of {sorted(UPLINK_MESSAGE_TYPES)}")

    payload = message.get("payload")
    if payload is None:
        # Temporary compatibility while internal fields are still being decided.
        payload = {key: value for key, value in message.items() if key not in COMMON_FIELDS}
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    received_at = time.time()
    return {
        "schema_version": str(message.get("schema_version", "draft")),
        "message_type": message_type,
        "session_id": message.get("session_id"),
        "packet_sequence": message.get("packet_sequence", message.get("sequence")),
        "pi_id": message.get("pi_id"),
        "timestamps": message.get("timestamps", {}),
        "timestamp": message.get("timestamp"),
        "payload": payload,
        "received_at": received_at,
        "raw": message,
    }


def route_uplink_message(message: dict[str, Any], address: tuple[str, int]) -> None:
    normalized = normalize_uplink_message(message)
    normalized["source_address"] = f"{address[0]}:{address[1]}"
    insert_pi_message(normalized)
    live_state.record_pi_message(normalized)

    message_type = normalized["message_type"]
    payload = normalized["payload"]

    if message_type == "status":
        live_state.apply_pi_status(payload)
    elif message_type == "fused_frame":
        live_state.apply_fused_frame(payload, normalized["received_at"])
    elif message_type == "control_event":
        live_state.apply_control_event(payload, normalized["received_at"])
    elif message_type == "window_features" and AUTO_INFER_WINDOW_FEATURES and model_service.loaded:
        result = model_service.predict(payload)
        accept_prediction(result)
