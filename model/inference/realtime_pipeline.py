"""
Real-Time Gesture Inference Pipeline
=====================================
Continuous inference loop:
  Camera frames + Micro:bit accel → SlidingWindowMerger → Feature vectors
  → Random Forest → Gesture prediction + confidence → MQTT publish

Usage:
  python inference/realtime_pipeline.py --camera 0 --port COM9 --model ../models/gesture_classifier.pkl
"""

import os
import sys
import json
import time
import queue
import threading
import argparse
from pathlib import Path
from collections import deque
from typing import Optional

import numpy as np
import cv2

# Module paths
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from feature_engineering.camera_features import CameraFeatureExtractor
from feature_engineering.accel_features import AccelFeatureExtractor
from feature_engineering.window_merger import SlidingWindowMerger
from microbit_receiver import SerialReceiver, AccelSample


# ============================================================
# Inference Pipeline
# ============================================================

class GestureInferencePipeline:
    """
    Continuous real-time gesture inference.

    Pipeline:
      1. Camera thread: capture frames → MediaPipe Hands → feed to merger
      2. Serial thread:  read accel samples → feed to merger
      3. Inference loop: extract windows → RF predict → publish results
    """

    def __init__(self, camera_id: int = 0, serial_port: str = "auto",
                 model_path: str = "models/gesture_classifier.pkl",
                 window_ms: float = 500, stride_ms: float = 250,
                 min_confidence: float = 0.6):
        self.camera_id = camera_id
        self.serial_port = serial_port
        self.min_confidence = min_confidence

        # Load model
        import joblib
        model_p = Path(model_path)
        if not model_p.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        self.model = joblib.load(model_p)

        # Load metadata
        import pickle
        meta_p = model_p.with_suffix('.meta.pkl')
        with open(meta_p, 'rb') as f:
            self.meta = pickle.load(f)
        self.labels = self.meta['labels']
        self.feature_names = self.meta['feature_names']

        print(f"[MODEL] Loaded: {model_path}")
        print(f"[MODEL] Classes: {self.labels}")
        print(f"[MODEL] Features: {len(self.feature_names)}")

        # Sliding window merger
        self.merger = SlidingWindowMerger(
            window_ms=window_ms, stride_ms=stride_ms,
        )

        # MediaPipe
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        import mediapipe as mp

        model_asset = os.path.join(_parent_dir, 'models', 'hand_landmarker.task')
        base_options = mp_python.BaseOptions(model_asset_path=model_asset)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            running_mode=vision.RunningMode.VIDEO,
        )
        self.hand_detector = vision.HandLandmarker.create_from_options(options)
        self._frame_idx = 0

        # State
        self.running = False
        self.latest_prediction: Optional[dict] = None
        self.prediction_history: deque = deque(maxlen=10)  # Smoothing
        self._cam_thread: Optional[threading.Thread] = None
        self._serial_thread: Optional[threading.Thread] = None
        self._accel_receiver: Optional[SerialReceiver] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_queue = queue.Queue(maxsize=30)

        # MQTT (optional)
        self._mqtt_client = None
        self._mqtt_topic = "model/gesture"

        # Callbacks
        self._on_prediction_callbacks: list = []

    def on_prediction(self, callback):
        """Register callback for prediction events: fn(prediction_dict)"""
        self._on_prediction_callbacks.append(callback)

    # --- Serial ---

    def _on_accel_sample(self, sample: AccelSample):
        """Callback from SerialReceiver → feed to merger"""
        ts = sample.pc_timestamp
        self.merger.add_accel_sample(sample)

    def _serial_loop(self):
        """Background thread: read Micro:bit serial"""
        self._accel_receiver = SerialReceiver(port=self.serial_port)
        self._accel_receiver.on_sample(self._on_accel_sample)
        self._accel_receiver.start()

    # --- Camera ---

    def _camera_loop(self):
        """Background thread: capture frames + MediaPipe detection"""
        self._cap = cv2.VideoCapture(self.camera_id)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap.set(cv2.CAP_PROP_FPS, 30)

        while self.running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # MediaPipe detection
            import mediapipe as mp
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            result = self.hand_detector.detect_for_video(mp_image, self._frame_idx)
            self._frame_idx += 1

            # Extract landmarks
            hands = []
            if result.hand_landmarks:
                for hand_lm in result.hand_landmarks:
                    coords = []
                    for lm in hand_lm:
                        coords.extend([lm.x, lm.y, lm.z])
                    hands.append(coords)

            ts = time.time()
            self.merger.add_camera_frame(hands, ts)

            # Put frame in queue for display (or just store latest)
            if not self._frame_queue.full():
                self._frame_queue.put((frame, hands, ts))

        self._cap.release()

    # --- Inference ---

    def _predict(self, features: np.ndarray) -> dict:
        """Run RF prediction and return formatted result"""
        probs = self.model.predict_proba(features.reshape(1, -1))[0]
        pred_idx = int(np.argmax(probs))
        confidence = float(probs[pred_idx])
        predicted_label = str(self.labels[pred_idx])

        return {
            'gesture': predicted_label,
            'confidence': round(confidence, 4),
            'probabilities': {
                str(lbl): round(float(p), 4)
                for lbl, p in zip(self.labels, probs)
            },
            'timestamp': time.time(),
        }

    def _smooth_prediction(self, gesture: str) -> str:
        """Apply temporal smoothing (majority vote over recent predictions)"""
        self.prediction_history.append(gesture)
        if len(self.prediction_history) < 3:
            return gesture
        # Count occurrences in buffer
        from collections import Counter
        counter = Counter(self.prediction_history)
        most_common = counter.most_common(1)[0]
        # Require >= 60% agreement
        if most_common[1] >= len(self.prediction_history) * 0.6:
            return most_common[0]
        return gesture  # Not enough agreement, keep latest

    # --- MQTT ---

    def enable_mqtt(self, broker: str = "localhost", port: int = 1883, topic: str = "model/gesture"):
        """Enable MQTT publishing of predictions"""
        import paho.mqtt.client as mqtt
        self._mqtt_client = mqtt.Client(client_id="gesture_inference")
        self._mqtt_topic = topic

        def on_connect(client, userdata, flags, rc):
            print(f"[MQTT] Connected to {broker}:{port} (rc={rc})")

        self._mqtt_client.on_connect = on_connect
        self._mqtt_client.connect_async(broker, port)
        self._mqtt_client.loop_start()
        print(f"[MQTT] Publishing to {topic}")

    def _publish_mqtt(self, prediction: dict):
        """Publish prediction via MQTT"""
        if self._mqtt_client:
            payload = json.dumps(prediction)
            self._mqtt_client.publish(self._mqtt_topic, payload, qos=0)

    # --- Main Loop ---

    def start(self, display: bool = True):
        """Start the inference pipeline"""
        self.running = True

        # Start background threads
        self._serial_thread = threading.Thread(target=self._serial_loop, daemon=True)
        self._serial_thread.start()
        time.sleep(0.5)  # Wait for serial connection

        self._cam_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self._cam_thread.start()

        print("\n[INFERENCE] Pipeline started. Press 'q' to quit.\n")

        # Main loop: inference + display
        while self.running:
            # Extract latest window
            jfv = self.merger.extract_latest()
            if jfv is not None:
                features = np.array(jfv.to_list())
                pred = self._predict(features)

                # Smooth
                smoothed_gesture = self._smooth_prediction(pred['gesture'])
                if smoothed_gesture != pred['gesture']:
                    pred['raw_gesture'] = pred['gesture']
                    pred['gesture'] = smoothed_gesture
                    pred['smoothed'] = True
                else:
                    pred['smoothed'] = False

                self.latest_prediction = pred

                # Fire callbacks
                for cb in self._on_prediction_callbacks:
                    try:
                        cb(pred)
                    except Exception as e:
                        print(f"[WARN] Prediction callback error: {e}")

                # Publish via MQTT
                self._publish_mqtt(pred)

            # Display
            if display:
                try:
                    frame, hands, ts = self._frame_queue.get_nowait()
                    self._draw_display(frame, hands)
                    cv2.imshow("Gesture Inference", frame)
                except queue.Empty:
                    pass

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                self.stop()
                break

    def _draw_display(self, frame, hands):
        """Draw UI overlay on frame"""
        h, w = frame.shape[:2]

        # Hand landmarks
        for hand_lms in hands:
            for i in range(0, len(hand_lms), 3):
                x = int(hand_lms[i] * w)
                y = int(hand_lms[i+1] * h)
                cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)

        # Prediction display
        if self.latest_prediction:
            gesture = self.latest_prediction['gesture']
            conf = self.latest_prediction['confidence']
            color = (0, 255, 0) if conf >= self.min_confidence else (0, 165, 255)

            cv2.rectangle(frame, (0, 0), (w, 80), (0, 0, 0), -1)
            cv2.putText(frame, f"Gesture: {gesture}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.putText(frame, f"Conf: {conf:.3f}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)

            # Top-3 probabilities
            if 'probabilities' in self.latest_prediction:
                probs = self.latest_prediction['probabilities']
                sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:3]
                y_offset = 100
                for label, prob in sorted_probs:
                    bar_w = int(prob * 150)
                    cv2.putText(frame, f"{label}", (w - 200, y_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
                    cv2.rectangle(frame, (w - 80, y_offset - 8),
                                  (w - 80 + bar_w, y_offset + 2), (0, 255, 0), -1)
                    y_offset += 18

        # Status bar
        cv2.putText(frame, "Q:Quit", (w - 80, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (128, 128, 128), 1)

    def stop(self):
        """Stop the pipeline"""
        self.running = False
        cv2.destroyAllWindows()
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
        print("[INFERENCE] Pipeline stopped.")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Real-Time Gesture Inference Pipeline")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--port", type=str, default="auto", help="Micro:bit COM port")
    parser.add_argument("--model", type=str, default="models/gesture_classifier.pkl")
    parser.add_argument("--window-ms", type=float, default=500)
    parser.add_argument("--stride-ms", type=float, default=250)
    parser.add_argument("--min-confidence", type=float, default=0.6)
    parser.add_argument("--mqtt-broker", type=str, default=None, help="MQTT broker address")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-topic", type=str, default="model/gesture")
    parser.add_argument("--no-display", action="store_true", help="Run headless")
    args = parser.parse_args()

    # Resolve model path relative to script
    model_p = Path(args.model)
    if not model_p.is_absolute():
        model_p = Path(_script_dir) / model_p
    model_p = str(model_p.resolve())

    pipeline = GestureInferencePipeline(
        camera_id=args.camera,
        serial_port=args.port,
        model_path=model_p,
        window_ms=args.window_ms,
        stride_ms=args.stride_ms,
        min_confidence=args.min_confidence,
    )

    if args.mqtt_broker:
        pipeline.enable_mqtt(args.mqtt_broker, args.mqtt_port, args.mqtt_topic)

    # Print predictions to console
    def print_pred(pred):
        conf_bar = "█" * int(pred['confidence'] * 20)
        print(f"  [{pred['gesture']:15s}] {pred['confidence']:.3f} {conf_bar}")

    pipeline.on_prediction(print_pred)
    pipeline.start(display=not args.no_display)


if __name__ == "__main__":
    main()
