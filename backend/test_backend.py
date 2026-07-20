"""Backend acceptance tests for the current Pi -> PC message schema."""

from __future__ import annotations

import json
import time

from app import app
from database import (
    get_pi_message_history,
    get_prediction_history,
    init_db,
    insert_prediction,
)
from message_router import normalize_uplink_message, route_uplink_message
from state import live_state


def main() -> None:
    init_db()

    test_result = {
        "gesture": "downbeat",
        "confidence": 0.92,
        "gesture_id": 1,
        "timestamp": time.time(),
        "features_used": 38,
        "all_probs": {
            "idle": 0.08,
            "downbeat": 0.92,
        },
    }
    inserted_id = insert_prediction(test_result)

    sample_messages = [
        {
            "message_type": "status",
            "session_id": "test",
            "packet_sequence": 1,
            "payload": {
                "camera": {
                    "connected": True,
                    "actual_fps": 29.4,
                },
                "microbits": {
                    "left": {
                        "device_id": "MB_LEFT",
                        "connected": True,
                    },
                    "right": {
                        "device_id": "MB_RIGHT",
                        "connected": True,
                    },
                },
                "network": {
                    "pc_connected": True,
                },
                "led": {
                    "enabled": True,
                },
            },
        },
        {
            "message_type": "fused_frame",
            "session_id": "test",
            "packet_sequence": 2,
            "payload": {
                "camera": {
                    "frame_id": 4821,
                    "hands": [],
                },
                "microbits": [
                    {
                        "device_id": "MB_LEFT",
                        "hand": "left",
                        "raw_interpolated": {
                            "acceleration_mg": [84, 1164, -362],
                            "pitch_deg": 18,
                            "roll_deg": -7,
                        },
                    },
                    {
                        "device_id": "MB_RIGHT",
                        "hand": "right",
                        "raw_interpolated": {
                            "acceleration_mg": [-102, 1388, -418],
                            "pitch_deg": 21,
                            "roll_deg": 6,
                        },
                    },
                ],
                "fusion": {
                    "valid": True,
                },
            },
        },
        {
            "message_type": "control_event",
            "session_id": "test",
            "packet_sequence": 3,
            "payload": {
                "event_id": "evt-00005",
                "event": {
                    "type": "right_wrist_strike",
                    "hand": "right",
                    "confidence": 0.94,
                    "strength": 0.83,
                },
                "music_control": {
                    "estimated_bpm": 118.1,
                    "tempo_delta": 0.12,
                    "volume": 0.73,
                    "intensity": 0.81,
                    "articulation": 0.58,
                },
                "led_control": {
                    "pattern": "right_pulse",
                    "brightness": 0.25,
                    "duration_ms": 120,
                },
            },
        },
    ]

    for message in sample_messages:
        normalized = normalize_uplink_message(message)
        assert normalized["message_type"] == message["message_type"]
        route_uplink_message(message, ("127.0.0.1", 9999))

    # Validate fused_frame mapping.
    sensors = live_state.get_sensors()

    assert sensors["microbit_left"]["hand"] == "left"
    assert sensors["microbit_right"]["hand"] == "right"

    assert (
        sensors["microbit_left"]["raw_interpolated"]["acceleration_mg"]
        == [84, 1164, -362]
    )
    assert (
        sensors["microbit_right"]["raw_interpolated"]["acceleration_mg"]
        == [-102, 1388, -418]
    )

    # Validate status mapping.
    assert live_state.camera_connected is True
    assert live_state.microbit_left_connected is True
    assert live_state.microbit_right_connected is True

    # Validate control_event -> music_state mapping.
    music = live_state.get_music()

    assert music["current_gesture"] == "right_wrist_strike"
    assert music["playing"] is True
    assert music["bpm"] == 118
    assert music["volume"] == 0.73

    pi_state = live_state.get_pi_state()
    assert (
        pi_state["last_control_event"]["payload"]["event_id"]
        == "evt-00005"
    )

    client = app.test_client()

    endpoints = (
        "/api/status",
        "/api/pi/status",
        "/api/pi/messages?limit=10",
        "/api/gesture/current",
        "/api/gesture/history?limit=5",
        "/api/sensors/live",
        "/api/music/state",
    )

    for endpoint in endpoints:
        response = client.get(endpoint)

        assert response.status_code == 200, (
            endpoint,
            response.status_code,
            response.get_data(as_text=True),
        )

        print(endpoint)
        print(
            json.dumps(
                response.get_json(),
                indent=2,
                ensure_ascii=False,
            )
        )

    assert any(
        record["id"] == inserted_id
        for record in get_prediction_history(limit=5)
    )

    recorded_types = {
        record["message_type"]
        for record in get_pi_message_history(limit=10)
    }

    assert recorded_types.issuperset(
        {
            "fused_frame",
            "control_event",
            "status",
        }
    )

    disconnected = client.post(
        "/api/pi/send",
        json={
            "message_type": "led_command",
            "payload": {
                "effect": "test",
            },
        },
    )

    assert disconnected.status_code == 503

    print("Backend acceptance test passed.")


if __name__ == "__main__":
    main()
