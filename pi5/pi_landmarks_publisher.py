#!/usr/bin/env python3
"""
Pi 5 Landmarks Publisher — Pi Camera → MediaPipe Hands → MQTT
==============================================================
Captures frames from the Pi Camera Module 3, runs MediaPipe Hand Landmarker,
and publishes hand landmark coordinates to MQTT.

Architecture:
  Pi Camera → OpenCV / picamera2 → MediaPipe Hands → MQTT: camera/landmarks

Prerequisites:
  - sudo apt install -y mosquitto mosquitto-clients
  - pip install opencv-python mediapipe paho-mqtt picamera2
  - sudo raspi-config → Enable Camera
  - models/hand_landmarker.task must be present

Usage:
  python pi_landmarks_publisher.py
  python pi_landmarks_publisher.py --camera 0 --width 640 --height 480

Data Format (published to MQTT — camera/landmarks):
  {
    "timestamp": 1234567890.123,
    "frame_index": 1234,
    "hands": [
      [x0, y0, z0, x1, y1, z1, ... x20, y20, z20],   # 21 landmarks × 3 = 63 floats
      ...                                               # up to 2 hands
    ],
    "handedness": ["Left", ...],    # Optional: Left/Right labels
    "num_hands": 2,
    "fps": 28.5
  }
"""

import json
import os
import signal
import sys
import time
import threading
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_LANDMARKS = "camera/landmarks"
MQTT_TOPIC_STATUS = "camera/status"

# Camera
DEFAULT_CAMERA_ID = int(os.getenv("PI_CAMERA_ID", "0"))
DEFAULT_WIDTH = int(os.getenv("PI_CAMERA_WIDTH", "640"))
DEFAULT_HEIGHT = int(os.getenv("PI_CAMERA_HEIGHT", "480"))
DEFAULT_FPS = int(os.getenv("PI_CAMERA_FPS", "30"))

# MediaPipe
HAND_LANDMARKER_MODEL = "hand_landmarker.task"
MIN_DETECTION_CONFIDENCE = float(os.getenv("MP_MIN_DETECTION", "0.5"))
MIN_PRESENCE_CONFIDENCE = float(os.getenv("MP_MIN_PRESENCE", "0.5"))
MIN_TRACKING_CONFIDENCE = float(os.getenv("MP_MIN_TRACKING", "0.5"))

# Status reporting interval (seconds)
STATUS_INTERVAL = float(os.getenv("STATUS_INTERVAL", "5.0"))


# ---------------------------------------------------------------------------
# Pi Camera Wrapper
# ---------------------------------------------------------------------------

class PiCameraCapture:
    """Camera capture using picamera2 (Raspberry Pi) or OpenCV fallback."""

    def __init__(self, camera_id: int = 0, width: int = 640, height: int = 480,
                 fps: int = 30):
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.target_fps = fps
        self._cap = None
        self._picam2 = None
        self._use_picamera2 = False

    def open(self) -> bool:
        """Open the camera. Tries picamera2 first, then OpenCV as fallback."""
        # Try picamera2 (Raspberry Pi libcamera stack)
        try:
            from picamera2 import Picamera2
            self._picam2 = Picamera2()
            config = self._picam2.create_preview_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"},
            )
            self._picam2.configure(config)
            self._picam2.start()
            self._use_picamera2 = True
            print(f"[CAMERA] Using picamera2: {self.width}×{self.height} @ {self.target_fps}fps")
            # Warm up
            time.sleep(0.5)
            return True
        except ImportError:
            print("[CAMERA] picamera2 not available, falling back to OpenCV")
        except Exception as e:
            print(f"[CAMERA] picamera2 failed: {e}, falling back to OpenCV")

        # Fallback to OpenCV VideoCapture
        import cv2
        self._cap = cv2.VideoCapture(self.camera_id)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)

        if not self._cap.isOpened():
            print(f"[CAMERA] ✗ Failed to open camera {self.camera_id}")
            return False

        actual_w = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"[CAMERA] Using OpenCV: {actual_w:.0f}×{actual_h:.0f} @ {self.target_fps}fps")
        return True

    def read(self) -> Optional[np.ndarray]:
        """Read a BGR frame. Returns numpy array or None."""
        if self._use_picamera2 and self._picam2:
            try:
                frame = self._picam2.capture_array()
                # picamera2 returns RGB; convert to BGR for consistency
                import cv2
                return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            except Exception as e:
                print(f"[CAMERA] picamera2 read error: {e}")
                return None
        elif self._cap:
            import cv2
            ret, frame = self._cap.read()
            return frame if ret else None
        return None

    def release(self):
        """Release camera resources."""
        if self._picam2:
            try:
                self._picam2.stop()
            except Exception:
                pass
            self._picam2 = None
        if self._cap:
            self._cap.release()
            self._cap = None
        print("[CAMERA] Released.")


# ---------------------------------------------------------------------------
# MQTT Publisher
# ---------------------------------------------------------------------------

class MQTTPublisher:
    """Simple MQTT publisher using paho-mqtt."""

    def __init__(self, broker: str = MQTT_BROKER, port: int = MQTT_PORT):
        self.broker = broker
        self.port = port
        self._client = None

    def connect(self):
        import paho.mqtt.client as mqtt
        self._client = mqtt.Client(client_id=f"pi_landmarks_{os.getpid()}")
        self._client.connect_async(self.broker, self.port, keepalive=60)
        self._client.loop_start()
        print(f"[MQTT] Connected to {self.broker}:{self.port}")

    def publish(self, topic: str, payload: dict, qos: int = 0):
        if self._client:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self._client.publish(topic, data, qos=qos)

    def disconnect(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None


# ---------------------------------------------------------------------------
# Landmark Extractor
# ---------------------------------------------------------------------------

class LandmarkExtractor:
    """Wraps MediaPipe Hand Landmarker for per-frame analysis."""

    def __init__(self, model_path: str):
        # Find model file
        model_p = Path(model_path)
        if not model_p.exists():
            # Search in common locations
            candidates = [
                Path.cwd() / model_path,
                Path.cwd() / "models" / model_path,
                Path(__file__).resolve().parent.parent / "models" / model_path,
            ]
            found = False
            for c in candidates:
                if c.exists():
                    model_p = c
                    found = True
                    break
            if not found:
                raise FileNotFoundError(
                    f"hand_landmarker.task not found at {model_path}. "
                    f"Searched: {[str(c) for c in candidates]}"
                )

        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        base_options = mp_python.BaseOptions(model_asset_path=str(model_p))
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=MIN_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=MIN_PRESENCE_CONFIDENCE,
            min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
            running_mode=vision.RunningMode.VIDEO,
        )
        self._detector = vision.HandLandmarker.create_from_options(options)
        print(f"[MEDIAPIPE] Hand Landmarker loaded from {model_p}")

    def detect(self, frame_bgr: np.ndarray, frame_index: int) -> dict:
        """
        Run hand detection on a BGR frame.

        Returns:
          {
            "hands": [[x0,y0,z0,...,x20,y20,z20], ...],
            "handedness": ["Left", ...],
            "num_hands": int
          }
        """
        import cv2
        import mediapipe as mp

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        result = self._detector.detect_for_video(mp_image, frame_index)

        hands = []
        handedness = []

        if result.hand_landmarks:
            for i, hand_lm in enumerate(result.hand_landmarks):
                coords = []
                for lm in hand_lm:
                    coords.extend([lm.x, lm.y, lm.z])
                hands.append(coords)

                # Handedness label
                if result.handedness and i < len(result.handedness):
                    handedness.append(result.handedness[i][0].category_name)
                else:
                    handedness.append("Unknown")

        return {
            "hands": hands,
            "handedness": handedness,
            "num_hands": len(hands),
        }


# ---------------------------------------------------------------------------
# FPS Tracker
# ---------------------------------------------------------------------------

class FPSTracker:
    """Tracks frame rate over a sliding window."""

    def __init__(self, window_size: int = 30):
        self._timestamps: deque = deque(maxlen=window_size)

    def tick(self):
        """Record a frame event."""
        self._timestamps.append(time.time())

    @property
    def fps(self) -> float:
        if len(self._timestamps) < 2:
            return 0.0
        dt = self._timestamps[-1] - self._timestamps[0]
        return (len(self._timestamps) - 1) / dt if dt > 0 else 0.0


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

class LandmarksPublisher:
    """Main loop: capture → detect → publish."""

    def __init__(
        self,
        mqtt: MQTTPublisher,
        camera: PiCameraCapture,
        extractor: LandmarkExtractor,
    ):
        self.mqtt = mqtt
        self.camera = camera
        self.extractor = extractor
        self.running = False
        self._frame_count = 0
        self._fps_tracker = FPSTracker()
        self._status_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the capture→detect→publish loop (blocking)."""
        if not self.camera.open():
            print("[ERROR] Cannot open camera. Exiting.")
            return

        self.mqtt.connect()
        self.running = True

        # Start status reporting thread
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()

        print("\n[PIPELINE] Started. Press Ctrl+C to stop.\n")

        try:
            while self.running:
                frame = self.camera.read()
                if frame is None:
                    time.sleep(0.005)
                    continue

                self._frame_count += 1
                self._fps_tracker.tick()

                # Run MediaPipe detection
                detection = self.extractor.detect(frame, self._frame_count)

                # Build MQTT payload
                payload = {
                    "timestamp": time.time(),
                    "frame_index": self._frame_count,
                    "hands": detection["hands"],
                    "handedness": detection["handedness"],
                    "num_hands": detection["num_hands"],
                    "fps": round(self._fps_tracker.fps, 1),
                }

                # Publish
                self.mqtt.publish(MQTT_TOPIC_LANDMARKS, payload, qos=0)

                # Console output (throttled)
                if self._frame_count % 30 == 0:
                    fps = self._fps_tracker.fps
                    hands_str = f"{detection['num_hands']} hand(s)" if detection["num_hands"] > 0 else "no hands"
                    print(f"  Frame #{self._frame_count:5d}  |  {hands_str:10s}  |  {fps:5.1f} fps")

        except KeyboardInterrupt:
            print("\n[PIPELINE] Stopping...")
        finally:
            self.stop()

    def stop(self):
        """Graceful shutdown."""
        self.running = False
        self.camera.release()
        self.mqtt.disconnect()
        if self._status_thread and self._status_thread.is_alive():
            self._status_thread.join(timeout=2)
        print("[PIPELINE] Stopped.")

    def _status_loop(self):
        """Publish camera status periodically."""
        while self.running:
            time.sleep(STATUS_INTERVAL)
            if not self.running:
                break
            self.mqtt.publish(MQTT_TOPIC_STATUS, {
                "frame_count": self._frame_count,
                "fps": round(self._fps_tracker.fps, 1),
                "timestamp": time.time(),
            })


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Pi 5 Landmarks Publisher — Pi Camera → MediaPipe Hands → MQTT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--camera", type=int, default=DEFAULT_CAMERA_ID,
                        help=f"Camera device ID (default: {DEFAULT_CAMERA_ID})")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH,
                        help=f"Capture width (default: {DEFAULT_WIDTH})")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT,
                        help=f"Capture height (default: {DEFAULT_HEIGHT})")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help=f"Target FPS (default: {DEFAULT_FPS})")
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT broker port")
    parser.add_argument("--model", default=HAND_LANDMARKER_MODEL,
                        help="Path to hand_landmarker.task model file")
    args = parser.parse_args()

    print("=" * 60)
    print("[Pi5] Landmarks Publisher")
    print(f"[Pi5] Camera: {args.camera} ({args.width}×{args.height} @ {args.fps}fps)")
    print(f"[Pi5] MQTT: {args.broker}:{args.port}")
    print(f"[Pi5] Model: {args.model}")
    print("=" * 60)

    mqtt = MQTTPublisher(broker=args.broker, port=args.port)
    camera = PiCameraCapture(
        camera_id=args.camera,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    extractor = LandmarkExtractor(model_path=args.model)

    pipeline = LandmarksPublisher(mqtt=mqtt, camera=camera, extractor=extractor)
    pipeline.start()


if __name__ == "__main__":
    main()
