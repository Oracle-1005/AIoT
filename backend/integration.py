"""Integration helpers for the PC-side model and legacy local test pipelines."""

from __future__ import annotations

import time
from typing import Any

from database import insert_prediction, insert_sensor_record
from model_service import model_service
from pi_gateway import pi_gateway
from state import live_state


def run_prediction(window_data: Any) -> dict[str, Any]:
    result = model_service.predict(window_data)
    accept_prediction(result)
    return result


def accept_prediction(result: dict[str, Any]) -> None:
    insert_prediction(result, latency_ms=result.get("latency_ms"))
    live_state.set_prediction(result)


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
