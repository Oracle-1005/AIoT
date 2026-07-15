"""Functions used by the model pipeline inside the same Python process.

The model owner can import these functions after producing a window or a
prediction. No HTTP model-to-backend interface is required.
"""

from __future__ import annotations

import time
from typing import Any

from database import insert_prediction, insert_sensor_record
from model_service import model_service
from mqtt_client import mqtt_client
from state import live_state


def run_prediction(window_data: Any) -> dict[str, Any]:
    """Call GestureClassifier.predict(window_data), then persist and publish."""
    result = model_service.predict(window_data)
    accept_prediction(result)
    return result


def accept_prediction(result: dict[str, Any]) -> None:
    """Accept a result already produced by the in-process model pipeline."""
    insert_prediction(result, latency_ms=result.get("latency_ms"))
    live_state.set_prediction(result)
    mqtt_client.publish_prediction(result)


def update_microbit(
    device_id: str,
    *,
    acc_x: float,
    acc_y: float,
    acc_z: float,
    pc_ts: float | None = None,
) -> None:
    """Update live state and persist one L/R Micro:bit sample."""
    device = device_id.upper()
    if device not in {"L", "R"}:
        raise ValueError("device_id must be 'L' or 'R'")

    timestamp = float(pc_ts if pc_ts is not None else time.time())
    sample = {"acc_x": float(acc_x), "acc_y": float(acc_y), "acc_z": float(acc_z)}

    insert_sensor_record(
        pc_ts=timestamp,
        device_id=device,
        acc_x=sample["acc_x"],
        acc_y=sample["acc_y"],
        acc_z=sample["acc_z"],
    )

    if device == "L":
        live_state.update_sensors(microbit_left=sample, timestamp=timestamp)
    else:
        live_state.update_sensors(microbit_right=sample, timestamp=timestamp)


def update_camera(
    hand_data: dict[str, Any] | list[Any],
    *,
    hand_count: int,
    pc_ts: float | None = None,
) -> None:
    """Update camera status and persist MediaPipe hand data."""
    timestamp = float(pc_ts if pc_ts is not None else time.time())
    insert_sensor_record(
        pc_ts=timestamp,
        device_id="camera",
        hand_data=hand_data,
    )
    live_state.update_sensors(
        hand_detected=hand_count > 0,
        hand_count=hand_count,
        timestamp=timestamp,
    )
