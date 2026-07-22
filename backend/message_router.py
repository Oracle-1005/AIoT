"""Validation and dispatch for Pi -> PC uplink messages.

The Pi currently sends three message types:

- fused_frame
- control_event
- status

Payload fields remain flexible because the hardware-side internal schema may
continue to evolve.
"""

from __future__ import annotations

import time
from typing import Any

from database import insert_pi_message
from sonic_pi import sonic_pi_adapter
from state import live_state

UPLINK_MESSAGE_TYPES = frozenset({
    "fused_frame",
    "control_event",
    "status",
})

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
        )

    elif message_type == "control_event":
        live_state.apply_control_event(
            payload,
            received_at,
        )
        sonic_pi_adapter.publish_control_event(
            payload,
            live_state.get_music(),
        )
