"""Backend acceptance tests, including flexible Pi JSONL message routing."""

from __future__ import annotations

import json
import time

from app import app
from database import get_pi_message_history, get_prediction_history, init_db, insert_prediction
from message_router import normalize_uplink_message, route_uplink_message


def main() -> None:
    init_db()
    test_result = {
        "gesture": "downbeat", "confidence": 0.92, "gesture_id": 1,
        "timestamp": time.time(), "features_used": 38,
        "all_probs": {"idle": 0.08, "downbeat": 0.92},
    }
    inserted_id = insert_prediction(test_result)

    sample_messages = [
        {"message_type": "status", "session_id": "test", "packet_sequence": 1,
         "payload": {"devices": {"camera": "online", "microbit_left": "online", "microbit_right": "online"}}},
        {"message_type": "fused_frame", "session_id": "test", "packet_sequence": 2,
         "payload": {"camera": {"hands": []}, "microbit_left": {"ax_mg": 1}, "microbit_right": {"ax_mg": 2}}},
        {"message_type": "window_features", "session_id": "test", "packet_sequence": 3,
         "payload": {"draft_feature": 1.0}},
        {"message_type": "control_event", "session_id": "test", "packet_sequence": 4,
         "payload": {"event": "pause"}},
    ]
    for message in sample_messages:
        assert normalize_uplink_message(message)["message_type"] == message["message_type"]
        route_uplink_message(message, ("127.0.0.1", 9999))

    client = app.test_client()
    endpoints = (
        "/api/status", "/api/pi/status", "/api/pi/messages?limit=10",
        "/api/gesture/current", "/api/gesture/history?limit=5",
        "/api/sensors/live", "/api/music/state",
    )
    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200, (endpoint, response.status_code, response.get_data(as_text=True))
        print(endpoint)
        print(json.dumps(response.get_json(), indent=2, ensure_ascii=False))

    assert any(record["id"] == inserted_id for record in get_prediction_history(limit=5))
    assert {record["message_type"] for record in get_pi_message_history(limit=10)}.issuperset(
        {"fused_frame", "window_features", "control_event", "status"}
    )
    disconnected = client.post("/api/pi/send", json={"message_type": "led_command", "payload": {"effect": "test"}})
    assert disconnected.status_code == 503
    print("Backend acceptance test passed.")


if __name__ == "__main__": main()
