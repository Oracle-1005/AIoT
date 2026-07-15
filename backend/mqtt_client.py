"""MQTT publisher for Interface ⑥.

The client is optional during local development. A missing broker must not
prevent Flask or SQLite from starting.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

import paho.mqtt.client as mqtt


MQTT_HOST = os.getenv("AIOT_MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("AIOT_MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("AIOT_MQTT_TOPIC", "aiot/gesture")
MQTT_ENABLED = os.getenv("AIOT_MQTT_ENABLED", "0").lower() in {"1", "true", "yes", "on"}


class GestureMQTTClient:
    def __init__(self) -> None:
        self._connected = False
        self._lock = threading.Lock()
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="aiot-flask-backend",
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> bool:
        if not MQTT_ENABLED:
            return False

        try:
            self._client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
            self._client.loop_start()
            return True
        except OSError as exc:
            print(f"[MQTT] Connection startup failed: {exc}")
            return False

    def stop(self) -> None:
        try:
            self._client.loop_stop()
            if self._connected:
                self._client.disconnect()
        except Exception as exc:  # pragma: no cover - shutdown safety
            print(f"[MQTT] Shutdown warning: {exc}")

    def publish_prediction(self, result: dict[str, Any]) -> bool:
        """Publish exactly the fields defined by Interface ⑥."""
        if not MQTT_ENABLED or not self._connected:
            return False

        payload = {
            "gesture": result["gesture"],
            "gesture_id": int(result.get("gesture_id", 0)),
            "confidence": float(result["confidence"]),
            "timestamp": float(result["timestamp"]),
        }

        with self._lock:
            info = self._client.publish(
                MQTT_TOPIC,
                json.dumps(payload, ensure_ascii=False),
                qos=0,
            )
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self._connected = reason_code == 0
        print(f"[MQTT] Connected={self._connected}, broker={MQTT_HOST}:{MQTT_PORT}")

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self._connected = False
        print(f"[MQTT] Disconnected: {reason_code}")


mqtt_client = GestureMQTTClient()
