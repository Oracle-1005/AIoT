"""Small first-week acceptance test using Flask's built-in test client."""

from __future__ import annotations

import json
import time

from app import app
from database import get_prediction_history, init_db, insert_prediction


def main() -> None:
    init_db()
    test_result = {
        "gesture": "downbeat",
        "confidence": 0.92,
        "gesture_id": 1,
        "timestamp": time.time(),
        "features_used": 38,
        "all_probs": {
            "idle": 0.01,
            "downbeat": 0.92,
            "crescendo": 0.02,
            "decrescendo": 0.01,
            "cutoff": 0.01,
            "style_switch": 0.01,
            "tempo_up": 0.01,
            "tempo_down": 0.01,
        },
    }
    inserted_id = insert_prediction(test_result)

    client = app.test_client()
    endpoints = (
        "/api/status",
        "/api/gesture/current",
        "/api/gesture/history?limit=5",
        "/api/sensors/live",
        "/api/music/state",
    )

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200, (endpoint, response.status_code)
        print(endpoint)
        print(json.dumps(response.get_json(), indent=2, ensure_ascii=False))

    history = get_prediction_history(limit=5)
    assert any(record["id"] == inserted_id for record in history)
    print("Backend acceptance test passed.")


if __name__ == "__main__":
    main()
