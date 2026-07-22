#!/usr/bin/env python3
"""
PC Inference Bridge — MQTT → Random Forest → MQTT
===================================================
Subscribes to Pi 5 MQTT for accelerometer + camera landmarks,
runs the trained Random Forest model, and publishes predictions back.

Architecture:
  Pi 5 MQTT ── microbit/accel/A ──┐
  Pi 5 MQTT ── microbit/accel/B ──┤
  Pi 5 MQTT ── camera/landmarks ──┘
       │
       ▼
  pc_inference_bridge.py
    ├─ Accumulate data in SlidingWindowMerger (500ms window)
    ├─ Extract 43-D joint feature vector
    ├─ Random Forest predict
    └─ Publish to MQTT: model/gesture

Usage:
  python pc_inference_bridge.py --broker <pi5-ip> --model models/gesture_classifier.pkl
  python pc_inference_bridge.py --broker 192.168.1.100 --min-confidence 0.7 --no-console
"""

import json
import os
import sys
import time
import argparse
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

# Add project root to path for model imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_script_dir) if os.path.basename(_script_dir) == "pi5" else _script_dir
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from model.feature_engineering.camera_features import CameraFeatureExtractor, CameraFeatureVector
from model.feature_engineering.accel_features import AccelFeatureExtractor, AccelFeatureVector
from model.feature_engineering.window_merger import SlidingWindowMerger, JointFeatureVector
from model.microbit_receiver import AccelSample


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# MQTT (connect to Pi 5 broker)
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# Topics (subscribe)
MQTT_TOPIC_ACCEL_A = "microbit/accel/A"
MQTT_TOPIC_ACCEL_B = "microbit/accel/B"
MQTT_TOPIC_LANDMARKS = "camera/landmarks"
MQTT_TOPIC_STATUS = "microbit/status/#"

# Topics (publish)
MQTT_TOPIC_GESTURE = "model/gesture"
MQTT_TOPIC_INFERENCE_STATUS = "model/status"

# Sliding window
WINDOW_MS = float(os.getenv("WINDOW_MS", "500"))
STRIDE_MS = float(os.getenv("STRIDE_MS", "250"))

# Inference
DEFAULT_MODEL_PATH = os.path.join(_project_dir, "models", "gesture_classifier.pkl")
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.6"))
MIN_SAMPLES_FOR_WINDOW = int(os.getenv("MIN_SAMPLES_FOR_WINDOW", "5"))

# Smoothing
SMOOTHING_WINDOW = int(os.getenv("SMOOTHING_WINDOW", "5"))

# Status report interval (seconds)
STATUS_INTERVAL = float(os.getenv("STATUS_INTERVAL", "5.0"))


# ---------------------------------------------------------------------------
# MQTT Client
# ---------------------------------------------------------------------------

class MQTTClient:
    """Combined MQTT subscriber + publisher using paho-mqtt."""

    def __init__(self, broker: str = MQTT_BROKER, port: int = MQTT_PORT):
        self.broker = broker
        self.port = port
        self._client = None
        self._message_handlers: dict[str, callable] = {}

    def on_message(self, topic: str, handler: callable):
        """Register a handler for a specific MQTT topic."""
        self._message_handlers[topic] = handler

    def connect_and_subscribe(self):
        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(client_id=f"pc_inference_{os.getpid()}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect_async(self.broker, self.port, keepalive=60)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[MQTT] Connected to {self.broker}:{self.port}")
            # Subscribe to all data topics
            client.subscribe(MQTT_TOPIC_ACCEL_A, qos=0)
            client.subscribe(MQTT_TOPIC_ACCEL_B, qos=0)
            client.subscribe(MQTT_TOPIC_LANDMARKS, qos=0)
            print(f"[MQTT] Subscribed to: {MQTT_TOPIC_ACCEL_A}, {MQTT_TOPIC_ACCEL_B}, {MQTT_TOPIC_LANDMARKS}")
        else:
            print(f"[MQTT] Connection failed: rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        handler = self._message_handlers.get(msg.topic)
        if handler:
            try:
                handler(payload)
            except Exception as e:
                print(f"[MQTT] Handler error for {msg.topic}: {e}")

    def publish(self, topic: str, payload: dict, qos: int = 0):
        """Publish JSON payload to MQTT."""
        if self._client:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self._client.publish(topic, data, qos=qos)

    def disconnect(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None


# ---------------------------------------------------------------------------
# Inference Engine
# ---------------------------------------------------------------------------

class InferenceEngine:
    """
    Receives accel + landmarks via MQTT, accumulates into sliding windows,
    runs Random Forest prediction, publishes results.
    """

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        window_ms: float = WINDOW_MS,
        stride_ms: float = STRIDE_MS,
        min_confidence: float = MIN_CONFIDENCE,
    ):
        self.min_confidence = min_confidence

        # Load model
        import joblib
        import pickle

        model_p = Path(model_path)
        if not model_p.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        self.model = joblib.load(model_p)

        meta_p = model_p.with_suffix(".meta.pkl")
        if meta_p.exists():
            with open(meta_p, "rb") as f:
                self.meta = pickle.load(f)
            self.labels = self.meta["labels"]
            self.feature_names = self.meta["feature_names"]
        else:
            # Fallback: infer from model
            self.labels = list(self.model.classes_)
            self.feature_names = []
            print("[MODEL] Warning: no metadata file, using inferred labels")

        print(f"[MODEL] Loaded: {model_p}")
        print(f"[MODEL] Classes: {self.labels}")
        print(f"[MODEL] Features: {len(self.feature_names)}")

        # Sliding window merger
        self.merger = SlidingWindowMerger(
            window_ms=window_ms,
            stride_ms=stride_ms,
        )

        # Prediction smoothing
        self._prediction_history: deque = deque(maxlen=SMOOTHING_WINDOW)
        self._latest_prediction: Optional[dict] = None

        # Stats
        self.total_accel_received = 0
        self.total_landmarks_received = 0
        self.total_predictions = 0
        self._last_status_time = time.time()

    # ---- Data ingestion (MQTT callbacks) ----

    def ingest_accel(self, payload: dict):
        """Receive one accelerometer sample from MQTT."""
        sample = AccelSample(
            device_id=payload.get("device_id", "?"),
            acc_x=payload.get("acc_x", 0.0),
            acc_y=payload.get("acc_y", 0.0),
            acc_z=payload.get("acc_z", 0.0),
            timestamp_ms=payload.get("timestamp_ms", 0),
            pc_timestamp=payload.get("pc_timestamp", time.time()),
        )
        self.merger.add_accel_sample(sample)
        self.total_accel_received += 1

    def ingest_landmarks(self, payload: dict):
        """Receive one camera landmarks frame from MQTT."""
        hands = payload.get("hands", [])
        ts = payload.get("timestamp", time.time())
        self.merger.add_camera_frame(hands, ts)
        self.total_landmarks_received += 1

    # ---- Inference ----

    def try_inference(self) -> Optional[dict]:
        """
        Try to extract a window and run inference.
        Returns prediction dict or None if not enough data.
        """
        if not self.merger.can_extract():
            return None

        jfv = self.merger.extract_latest()
        if jfv is None:
            return None

        features = np.array(jfv.to_list())
        probs = self.model.predict_proba(features.reshape(1, -1))[0]
        pred_idx = int(np.argmax(probs))
        confidence = float(probs[pred_idx])
        predicted_label = str(self.labels[pred_idx])

        # Smooth prediction
        self._prediction_history.append(predicted_label)
        smoothed = self._smooth(predicted_label)

        prediction = {
            "gesture": smoothed,
            "raw_gesture": predicted_label,
            "confidence": round(confidence, 4),
            "smoothed": smoothed != predicted_label,
            "probabilities": {
                str(lbl): round(float(p), 4)
                for lbl, p in zip(self.labels, probs)
            },
            "timestamp": time.time(),
            "window_start_ts": jfv.window_start_ts,
            "window_end_ts": jfv.window_end_ts,
        }

        self._latest_prediction = prediction
        self.total_predictions += 1

        return prediction if confidence >= self.min_confidence else {
            **prediction,
            "gesture": "unknown",
            "confidence": confidence,
            "filtered": True,
        }

    def _smooth(self, gesture: str) -> str:
        """Majority vote over recent predictions."""
        if len(self._prediction_history) < 3:
            return gesture
        from collections import Counter
        counter = Counter(self._prediction_history)
        most_common, count = counter.most_common(1)[0]
        if count >= len(self._prediction_history) * 0.6:
            return most_common
        return gesture

    @property
    def latest_prediction(self) -> Optional[dict]:
        return self._latest_prediction

    def get_status(self) -> dict:
        return {
            "model_loaded": True,
            "labels": self.labels,
            "total_accel_received": self.total_accel_received,
            "total_landmarks_received": self.total_landmarks_received,
            "total_predictions": self.total_predictions,
            "can_extract": self.merger.can_extract(),
            "latest_camera_ts": self.merger.latest_camera_ts,
            "latest_accel_ts": self.merger.latest_accel_ts,
            "min_confidence": self.min_confidence,
            "timestamp": time.time(),
        }


# ---------------------------------------------------------------------------
# Main Bridge
# ---------------------------------------------------------------------------

class PCInferenceBridge:
    """Orchestrates MQTT → Inference → MQTT."""

    def __init__(self, engine: InferenceEngine, mqtt: MQTTClient):
        self.engine = engine
        self.mqtt = mqtt
        self.running = False

        # Wire MQTT handlers
        self.mqtt.on_message(MQTT_TOPIC_ACCEL_A, self.engine.ingest_accel)
        self.mqtt.on_message(MQTT_TOPIC_ACCEL_B, self.engine.ingest_accel)
        self.mqtt.on_message(MQTT_TOPIC_LANDMARKS, self.engine.ingest_landmarks)

        # Console print throttle
        self._last_print = 0.0
        self._last_status = 0.0

    def start(self):
        """Start the inference bridge (blocking)."""
        print("=" * 60)
        print("[BRIDGE] PC Inference Bridge starting...")
        print(f"[BRIDGE] MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
        print(f"[BRIDGE] Window: {WINDOW_MS}ms / Stride: {STRIDE_MS}ms")
        print(f"[BRIDGE] Min Confidence: {MIN_CONFIDENCE}")
        print(f"[BRIDGE] Publishing to: {MQTT_TOPIC_GESTURE}")
        print("=" * 60)

        self.mqtt.connect_and_subscribe()
        self.running = True

        print("\n[BRIDGE] Running. Waiting for data from Pi 5...\n")
        print("  Press Ctrl+C to stop.\n")

        try:
            while self.running:
                # Try inference
                prediction = self.engine.try_inference()
                if prediction:
                    self.mqtt.publish(MQTT_TOPIC_GESTURE, prediction, qos=0)

                    # Console output (throttled)
                    now = time.time()
                    if now - self._last_print >= 0.5:
                        conf_bar = "█" * int(prediction["confidence"] * 20)
                        filtered = " [FILTERED]" if prediction.get("filtered") else ""
                        print(f"  [{prediction['gesture']:15s}]  "
                              f"conf={prediction['confidence']:.3f}  {conf_bar}{filtered}")
                        self._last_print = now

                # Status reporting
                now = time.time()
                if now - self._last_status >= STATUS_INTERVAL:
                    self.mqtt.publish(MQTT_TOPIC_INFERENCE_STATUS, self.engine.get_status())
                    self._last_status = now

                time.sleep(0.01)  # ~100Hz check rate

        except KeyboardInterrupt:
            print("\n[BRIDGE] Stopping...")
        finally:
            self.stop()

    def stop(self):
        """Graceful shutdown."""
        self.running = False
        self.mqtt.disconnect()
        print("[BRIDGE] Stopped.")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PC Inference Bridge — MQTT → Random Forest → MQTT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pc_inference_bridge.py --broker 192.168.1.100
  python pc_inference_bridge.py --broker pi5.local --min-confidence 0.8
  python pc_inference_bridge.py --broker localhost --model ../models/gesture_classifier.pkl
        """,
    )
    parser.add_argument("--broker", default=MQTT_BROKER,
                        help=f"Pi 5 MQTT broker address (default: {MQTT_BROKER})")
    parser.add_argument("--port", type=int, default=MQTT_PORT,
                        help=f"MQTT broker port (default: {MQTT_PORT})")
    parser.add_argument("--model", default=DEFAULT_MODEL_PATH,
                        help="Path to gesture_classifier.pkl")
    parser.add_argument("--window-ms", type=float, default=WINDOW_MS,
                        help=f"Sliding window size in ms (default: {WINDOW_MS})")
    parser.add_argument("--stride-ms", type=float, default=STRIDE_MS,
                        help=f"Window stride in ms (default: {STRIDE_MS})")
    parser.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE,
                        help=f"Minimum confidence threshold (default: {MIN_CONFIDENCE})")
    parser.add_argument("--no-console", action="store_true",
                        help="Suppress console output")
    args = parser.parse_args()

    # Resolve model path
    model_path = Path(args.model)
    if not model_path.is_absolute():
        # Try relative to project root
        candidates = [
            Path(_project_dir) / args.model,
            Path.cwd() / args.model,
        ]
        for c in candidates:
            if c.exists():
                model_path = c.resolve()
                break

    if not model_path.exists():
        print(f"[ERROR] Model not found: {args.model}")
        print(f"  Searched: {[str(c) for c in candidates]}")
        sys.exit(1)

    mqtt = MQTTClient(broker=args.broker, port=args.port)
    engine = InferenceEngine(
        model_path=str(model_path),
        window_ms=args.window_ms,
        stride_ms=args.stride_ms,
        min_confidence=args.min_confidence,
    )

    bridge = PCInferenceBridge(engine=engine, mqtt=mqtt)
    bridge.start()


if __name__ == "__main__":
    main()
