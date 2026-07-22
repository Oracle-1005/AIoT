"""
Data Collection Tool — Gesture Training Data Recorder
======================================================
Records synchronized Camera (MediaPipe Hands) + Micro:bit (Accelerometer) data
with gesture labels for Random Forest training.

Usage:
  python collect_data.py --camera 0 --port COM9 --output data/raw/

Controls:
  1-9   : Select gesture label (see GESTURE_MAP below)
  SPACE : Start/stop recording
  Q     : Quit

Output per recording:
  data/raw/{label}_{timestamp}_landmarks.csv   — MediaPipe 21-keypoint per frame
  data/raw/{label}_{timestamp}_accel.csv       — Micro:bit acceleration
  data/raw/{label}_{timestamp}_meta.json       — Metadata (label, duration, etc.)
"""

import cv2
import csv
import json
import time
import sys
import os
import argparse
import threading
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# MediaPipe (new API: mediapipe >= 0.10.0)
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Micro:bit receiver (same directory)
import os as _os, sys as _sys
_script_dir = _os.path.dirname(_os.path.abspath(__file__))
if _script_dir not in _sys.path:
    _sys.path.insert(0, _script_dir)
from microbit_receiver import SerialReceiver, AccelSample

# ============================================================
# Gesture Label Map
# ============================================================
GESTURE_MAP = {
    ord('1'): 'beat_4_4',       # 4/4 beat pattern
    ord('2'): 'beat_3_4',       # 3/4 beat pattern
    ord('3'): 'beat_2_4',       # 2/4 beat pattern
    ord('4'): 'crescendo',      # Gradually louder
    ord('5'): 'diminuendo',     # Gradually softer
    ord('6'): 'cutoff',          # Sharp stop
    ord('7'): 'hold',            # Sustained hold
    ord('8'): 'upbeat',          # Upbeat/anacrusis
    ord('9'): 'idle',            # No gesture / resting
}

GESTURE_NAMES = {v: k for k, v in GESTURE_MAP.items()}

# ============================================================
# Data Structures
# ============================================================

@dataclass
class LandmarkFrame:
    """Single frame of MediaPipe hand landmarks"""
    timestamp: float
    hands: list  # List of hand landmark lists (21 points × 3 coords each)

@dataclass
class RecordingSession:
    """One recording session"""
    label: str
    start_time: float
    duration: float = 0.0
    landmarks: list = field(default_factory=list)     # List[LandmarkFrame]
    accel_samples: list = field(default_factory=list)  # List[AccelSample]

    def add_landmarks(self, ts: float, hands: list):
        self.landmarks.append(LandmarkFrame(timestamp=ts, hands=hands))

    def add_accel(self, sample: AccelSample):
        self.accel_samples.append(sample)

    def finish(self):
        self.duration = time.time() - self.start_time

    @property
    def landmark_count(self) -> int:
        return len(self.landmarks)

    @property
    def accel_count(self) -> int:
        return len(self.accel_samples)

# ============================================================
# MediaPipe Hand Landmarker
# ============================================================

class HandLandmarkDetector:
    """Wrapper around MediaPipe HandLandmarker for real-time detection"""

    def __init__(self, model_path: str = None):
        if model_path is None:
            model_path = os.path.join(os.path.dirname(__file__), 'models', 'hand_landmarker.task')

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            running_mode=vision.RunningMode.VIDEO,
        )
        self.detector = vision.HandLandmarker.create_from_options(options)
        self.frame_idx = 0

    def detect(self, frame_bgr) -> list:
        """
        Detect hands in a BGR frame.
        Returns list of hand landmark lists.
        Each hand: [(x, y, z), ...] × 21 landmarks
        """
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        result = self.detector.detect_for_video(mp_image, self.frame_idx)
        self.frame_idx += 1

        hands = []
        if result.hand_landmarks:
            for hand_lm in result.hand_landmarks:
                # Flatten 21 landmarks → [x0,y0,z0, x1,y1,z1, ...]
                coords = []
                for lm in hand_lm:
                    coords.extend([lm.x, lm.y, lm.z])
                hands.append(coords)
        return hands


# ============================================================
# Data Collector
# ============================================================

class DataCollector:
    """Main data collection controller"""

    def __init__(self, camera_id: int = 0, serial_port: str = "auto",
                 output_dir: str = "data/raw/", model_path: str = None):
        self.camera_id = camera_id
        self.serial_port = serial_port
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # State
        self.selected_label: Optional[str] = None
        self.is_recording = False
        self.current_session: Optional[RecordingSession] = None
        self.running = True

        # Modules
        self.landmark_detector = HandLandmarkDetector(model_path)
        self.accel_buffer: deque = deque(maxlen=500)  # Rolling buffer for alignment
        self.serial_receiver: Optional[SerialReceiver] = None
        self._accel_thread: Optional[threading.Thread] = None
        self._latest_accel: Optional[AccelSample] = None

        # Camera
        self.cap: Optional[cv2.VideoCapture] = None

    def _on_accel(self, sample: AccelSample):
        """Callback for incoming accelerometer data"""
        self.accel_buffer.append(sample)
        self._latest_accel = sample
        if self.is_recording and self.current_session:
            self.current_session.add_accel(sample)

    def _start_serial(self):
        """Start serial receiver in background thread"""
        if self.serial_port and self.serial_port != "none":
            self.serial_receiver = SerialReceiver(port=self.serial_port)
            self.serial_receiver.on_sample(self._on_accel)
            self._accel_thread = threading.Thread(
                target=self.serial_receiver.start, daemon=True
            )
            self._accel_thread.start()
            time.sleep(0.5)  # Wait for connection

    def start(self):
        """Start data collection UI"""
        # Initialize serial
        self._start_serial()

        # Initialize camera
        self.cap = cv2.VideoCapture(self.camera_id)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        if not self.cap.isOpened():
            print(f"[ERROR] Cannot open camera {self.camera_id}")
            return

        print("\n" + "=" * 60)
        print("  AIoT Gesture Data Collection Tool")
        print("=" * 60)
        print("  Controls:")
        for key_code, label in GESTURE_MAP.items():
            print(f"    [{chr(key_code)}] {label}")
        print("    [SPACE] Start/Stop recording")
        print("    [Q]     Quit")
        print("=" * 60)
        print()

        # Main loop
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                print("[ERROR] Camera frame read failed")
                break

            frame = cv2.flip(frame, 1)  # Mirror for selfie view

            # Detect hands
            hands = self.landmark_detector.detect(frame)
            now = time.time()

            # Record landmarks if recording
            if self.is_recording and self.current_session:
                self.current_session.add_landmarks(now, hands)

            # Draw UI overlay
            self._draw_ui(frame, hands)

            cv2.imshow("Data Collector", frame)

            # Handle keyboard
            key = cv2.waitKey(1) & 0xFF
            self._handle_key(key)

        self._cleanup()

    def _handle_key(self, key: int):
        """Process keyboard input"""
        if key == ord('q') or key == ord('Q'):
            if self.is_recording:
                self._stop_recording()
            self.running = False
            return

        # Label selection
        if key in GESTURE_MAP:
            self.selected_label = GESTURE_MAP[key]
            print(f"[LABEL] Selected: {self.selected_label}")

        # Start/stop recording
        if key == ord(' '):
            if self.is_recording:
                self._stop_recording()
            else:
                self._start_recording()

    def _start_recording(self):
        """Start a new recording session"""
        if self.selected_label is None:
            print("[WARN] Select a gesture label first (press 1-9)")
            return

        self.is_recording = True
        self.current_session = RecordingSession(
            label=self.selected_label,
            start_time=time.time(),
        )
        print(f"[REC] Started recording '{self.selected_label}'...")

    def _stop_recording(self):
        """Stop current recording and save data"""
        if not self.current_session:
            return

        self.is_recording = False
        self.current_session.finish()
        session = self.current_session
        self.current_session = None

        duration = session.duration
        if duration < 0.2 or session.landmark_count < 5:
            print(f"[WARN] Recording too short ({duration:.1f}s, {session.landmark_count} frames), discarded")
            return

        # Save
        ts = int(time.time())
        prefix = f"{session.label}_{ts}"

        # Save landmarks CSV
        lm_path = self.output_dir / f"{prefix}_landmarks.csv"
        with open(lm_path, 'w', newline='') as f:
            writer = csv.writer(f)
            header = ['timestamp']
            for i in range(21):
                header += [f'lm{i}_x', f'lm{i}_y', f'lm{i}_z']
            header += ['num_hands']
            writer.writerow(header)

            for lf in session.landmarks:
                if lf.hands:
                    # Use first hand (dominant)
                    row = [lf.timestamp] + lf.hands[0] + [len(lf.hands)]
                else:
                    row = [lf.timestamp] + [0.0] * 63 + [0]
                writer.writerow(row)

        # Save accel CSV
        accel_path = self.output_dir / f"{prefix}_accel.csv"
        with open(accel_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['pc_ts', 'device_id', 'acc_x', 'acc_y', 'acc_z', 'timestamp_ms'])
            for s in session.accel_samples:
                writer.writerow([s.pc_timestamp, s.device_id, s.acc_x, s.acc_y, s.acc_z, s.timestamp_ms])

        # Save metadata
        meta_path = self.output_dir / f"{prefix}_meta.json"
        meta = {
            'label': session.label,
            'duration_s': round(duration, 2),
            'landmark_frames': session.landmark_count,
            'accel_samples': session.accel_count,
            'landmark_fps': round(session.landmark_count / duration, 1) if duration > 0 else 0,
            'accel_hz': round(session.accel_count / duration, 1) if duration > 0 else 0,
        }
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)

        print(f"[SAVED] {prefix}")
        print(f"        {session.landmark_count} lm frames, {session.accel_count} accel samples, {duration:.1f}s")
        print(f"        -> {lm_path.name}")
        print(f"        -> {accel_path.name}")

    def _draw_ui(self, frame, hands):
        """Draw UI overlay on frame"""
        h, w = frame.shape[:2]

        # Status bar at top
        status_color = (0, 255, 0) if self.is_recording else (200, 200, 200)
        status_text = "RECORDING" if self.is_recording else "STANDBY"
        cv2.putText(frame, status_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, status_color, 2)

        # Selected label
        label_text = f"Label: {self.selected_label or '(none)'}"
        cv2.putText(frame, label_text, (10, 55), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 0), 1)

        # Accel data
        if self._latest_accel:
            s = self._latest_accel
            accel_text = f"Accel: x={s.acc_x:5.0f} y={s.acc_y:5.0f} z={s.acc_z:5.0f}"
            cv2.putText(frame, accel_text, (10, 80), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 255), 1)

        # Recording timer
        if self.is_recording and self.current_session:
            elapsed = time.time() - self.current_session.start_time
            timer_text = f"REC: {elapsed:.1f}s"
            cv2.putText(frame, timer_text, (w - 200, 25), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2)

        # Draw hand landmarks
        if hands:
            for hand_lms in hands:
                for i in range(0, len(hand_lms), 3):
                    x = int(hand_lms[i] * w)
                    y = int(hand_lms[i+1] * h)
                    cv2.circle(frame, (x, y), 3, (0, 255, 0), -1)

        # Help at bottom
        help_text = "1-9:Label | SPACE:Record | Q:Quit"
        cv2.putText(frame, help_text, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (150, 150, 150), 1)

    def _cleanup(self):
        """Release resources"""
        self.running = False
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        if self.serial_receiver and self.serial_receiver._ser:
            self.serial_receiver._ser.close()
        print("\n[INFO] Data collector stopped.")


# ============================================================
# CLI Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="AIoT Gesture Data Collection Tool")
    parser.add_argument("--camera", type=int, default=0, help="Camera device ID")
    parser.add_argument("--port", type=str, default="auto", help="Micro:bit serial port (COMx or 'none')")
    parser.add_argument("--output", type=str, default="data/raw/", help="Output directory")
    parser.add_argument("--model", type=str, default=None, help="Path to hand_landmarker.task")
    args = parser.parse_args()

    collector = DataCollector(
        camera_id=args.camera,
        serial_port=args.port,
        output_dir=args.output,
        model_path=args.model,
    )
    collector.start()


if __name__ == "__main__":
    main()
