"""Camera sensor: Picamera2 capture + MediaPipe Hand Landmarker.

Runs in a dedicated background thread to avoid blocking the asyncio event
loop. Picamera2 capture is blocking I/O and MediaPipe inference is
CPU-intensive — neither should run in asyncio.

Outputs CameraFrame objects via a thread-safe queue.
Applies temporal landmark smoothing to reduce MediaPipe jitter.
"""

import logging
import threading
import queue
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pi_pc import LandmarkSmoother, CameraClockSync

logger = logging.getLogger(__name__)

# MediaPipe and Picamera2 are imported lazily at initialization time
# to allow the module to be imported on non-RPi machines for testing.


@dataclass
class CameraFrame:
    """A single processed camera frame with MediaPipe hand landmarks."""

    frame_id: int
    sensor_timestamp_ns: int        # Raw camera SensorTimestamp
    pi_aligned_timestamp_ns: int    # Mapped to Pi monotonic_ns (via CameraClockSync)
    width: int
    height: int
    hands: list[dict]        # List of hand dicts per the fused_frame schema
    processing_latency_ms: float = 0.0
    clock_ready: bool = False  # Whether CameraClockSync is ready
    preview_jpeg: bytes | None = None
    raw_hands_detected: int = 0
    preview_interpolated_hands: int = 0
    hand_detection_rate_5s: float = 0.0
    consecutive_missed_frames: int = 0


class CameraSensor:
    """Camera capture and hand tracking in a background thread.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        fps: Target frame rate.
        max_hands: Maximum number of hands to detect.
        frame_queue_size: Max size of the output queue. Old frames are
            dropped when the queue is full.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        max_hands: int = 2,
        frame_queue_size: int = 10,
        pixel_format: str = "BGR888",
        min_hand_detection_confidence: float = 0.35,
        min_hand_presence_confidence: float = 0.35,
        min_tracking_confidence: float = 0.40,
        max_missing_frames: int = 4,
        detection_window_seconds: float = 5.0,
        enable_preview_jpeg: bool = False,
        preview_jpeg_quality: int = 70,
        preview_jpeg_every_n_frames: int = 2,
    ):
        self._width = width
        self._height = height
        self._fps = fps
        self._max_hands = max_hands
        self._pixel_format = pixel_format.upper()
        if self._pixel_format not in {"BGR888", "RGB888"}:
            raise ValueError("pixel_format must be BGR888 or RGB888")
        self._min_hand_detection_confidence = self._validate_confidence(
            "min_hand_detection_confidence", min_hand_detection_confidence
        )
        self._min_hand_presence_confidence = self._validate_confidence(
            "min_hand_presence_confidence", min_hand_presence_confidence
        )
        self._min_tracking_confidence = self._validate_confidence(
            "min_tracking_confidence", min_tracking_confidence
        )
        self._max_missing_frames = max(0, int(max_missing_frames))
        self._enable_preview_jpeg = enable_preview_jpeg
        self._preview_jpeg_quality = max(30, min(95, preview_jpeg_quality))
        self._preview_jpeg_every_n_frames = max(1, preview_jpeg_every_n_frames)

        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._frame_queue: queue.Queue = queue.Queue(maxsize=frame_queue_size)
        self._frame_counter = 0

        # Status tracking
        self._actual_fps = 0.0
        self._dropped_frames = 0
        self._last_frame_time_ns = 0
        self._processing_latency_ms = 0.0
        self._connected = False
        self._detection_window_seconds = max(1.0, float(detection_window_seconds))
        self._detection_window: deque[tuple[float, int]] = deque()
        self._detection_lock = threading.Lock()
        self._consecutive_missed_frames = 0
        self._preview_tracks: dict[str, dict] = {}
        self._preview_interpolated_hands = 0

        # Lazy imports
        self._picam2 = None
        self._mp = None
        self._hand_landmarker = None
        self._mp_drawing = None
        self._cv2 = None

        # Per-hand state for velocity computation
        self._prev_wrist_pos: dict[str, tuple[float, float, float] | None] = {}
        self._prev_frame_time: dict[str, int] = {}

        # Landmark temporal smoother (reduces MediaPipe jitter)
        self._landmark_smoother = LandmarkSmoother(min_cutoff_hz=1.5, beta=0.05)

        # Camera clock sync: maps SensorTimestamp → Pi monotonic_ns
        # Same linear-regression pattern as BLE ClockSync
        self._camera_clock = CameraClockSync(
            min_points=10,
            max_points=60,
            outlier_offset_factor=3.0,
        )

        # Optional hook for the in-process MJPEG video stream
        # (fusion_pipeline/video_stream.py).  Signature:
        #     cb(frame_array_rgb, hands_data) -> None
        # Invoked from the capture thread right after MediaPipe; must be
        # fast and non-blocking.  None = disabled (zero cost).
        self.frame_image_callback = None

    # ---- Public API ----

    def start(self) -> bool:
        """Initialize camera and MediaPipe, launch background thread.

        Returns:
            True if started successfully.
        """
        try:
            self._init_camera()
            self._init_mediapipe()
        except Exception as e:
            logger.error("Camera/MediaPipe init failed: %s", e)
            self._connected = False
            return False

        self._connected = True
        self._running.set()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="camera-thread")
        self._thread.start()
        logger.info("Camera thread started: %dx%d @ %d FPS", self._width, self._height, self._fps)
        return True

    def stop(self) -> None:
        """Signal thread to stop, join, and release resources."""
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._connected = False
        self._preview_tracks.clear()
        self._preview_interpolated_hands = 0

        # Release MediaPipe
        if self._hand_landmarker:
            try:
                self._hand_landmarker.close()
            except Exception:
                pass
            self._hand_landmarker = None

        # Release Picamera2
        if self._picam2:
            try:
                self._picam2.close()
            except Exception:
                pass

        logger.info("Camera stopped.")

    def get_frame(self, timeout: float = 0.05) -> CameraFrame | None:
        """Get the next processed frame from the queue (thread-safe).

        Args:
            timeout: Seconds to wait for a frame. 0 = non-blocking.

        Returns:
            CameraFrame or None if no frame available.
        """
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def is_running(self) -> bool:
        """Return whether the camera thread is active."""
        return self._running.is_set()

    def get_status(self) -> dict:
        """Return camera status for the status message."""
        now_ns = time.monotonic_ns()
        last_frame_age_ms = (
            (now_ns - self._last_frame_time_ns) / 1_000_000.0
            if self._last_frame_time_ns > 0
            else 0.0
        )

        return {
            "connected": self._connected,
            "configured_fps": self._fps,
            "actual_fps": self._actual_fps,
            "dropped_frames": self._dropped_frames,
            "last_frame_age_ms": round(last_frame_age_ms, 1),
            "processing_latency_ms": round(self._processing_latency_ms, 1),
            "clock_ready": self._camera_clock.clock_ready,
            "clock_points": self._camera_clock.point_count,
            "pixel_format": self._pixel_format,
            "hand_detection_rate_5s": round(self._hand_detection_rate(), 3),
            "consecutive_missed_frames": self._consecutive_missed_frames,
            "preview_interpolated_hands": self._preview_interpolated_hands,
            "thresholds": {
                "detection": self._min_hand_detection_confidence,
                "presence": self._min_hand_presence_confidence,
                "tracking": self._min_tracking_confidence,
            },
        }

    # ---- Internal: Initialization ----

    def _init_camera(self) -> None:
        """Initialize Picamera2 with configured resolution and format."""
        try:
            from picamera2 import Picamera2

            self._picam2 = Picamera2()
            config = self._picam2.create_video_configuration(
                main={
                    "size": (self._width, self._height),
                    "format": self._pixel_format,
                },
                controls={"FrameRate": self._fps},
            )
            self._picam2.configure(config)
            self._picam2.start()
            # Warm up: capture a few frames to stabilize exposure/AWB
            for _ in range(5):
                self._picam2.capture_array("main")
            logger.info(
                "Picamera2 initialized: %dx%d @ %d FPS, format=%s",
                self._width,
                self._height,
                self._fps,
                self._pixel_format,
            )

        except ImportError:
            raise RuntimeError("picamera2 not installed. Run: pip install picamera2")
        except Exception as e:
            raise RuntimeError(f"Picamera2 init failed: {e}")

    def _init_mediapipe(self) -> None:
        """Initialize MediaPipe Hand Landmarker."""
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            self._mp = mp

            model_path = self._find_hand_landmarker_model()
            if model_path is None:
                raise RuntimeError(
                    "hand_landmarker.task not found. Expected it under "
                    "models/ or camera_to_Pi/models/ in the project root."
                )

            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=self._max_hands,
                min_hand_detection_confidence=self._min_hand_detection_confidence,
                min_hand_presence_confidence=self._min_hand_presence_confidence,
                min_tracking_confidence=self._min_tracking_confidence,
            )
            self._hand_landmarker = vision.HandLandmarker.create_from_options(options)

            logger.info("MediaPipe HandLandmarker initialized: %s", model_path)

        except ImportError:
            raise RuntimeError("mediapipe not installed. Run: pip install mediapipe")
        except Exception as e:
            raise RuntimeError(f"MediaPipe init failed: {e}")

    def _init_preview_encoder(self) -> None:
        """Initialize optional OpenCV JPEG encoder for browser preview."""
        if not self._enable_preview_jpeg:
            return
        try:
            import cv2

            self._cv2 = cv2
        except Exception as exc:
            self._cv2 = None
            logger.warning("Preview JPEG disabled: OpenCV import failed: %s", exc)

    @staticmethod
    def _find_hand_landmarker_model() -> Path | None:
        """Locate the MediaPipe hand landmarker model in known project paths."""
        here = Path(__file__).resolve()
        project_root = here.parents[2]
        candidates = [
            Path.cwd() / "hand_landmarker.task",
            Path.cwd() / "models" / "hand_landmarker.task",
            project_root / "models" / "hand_landmarker.task",
            project_root / "camera_to_Pi" / "models" / "hand_landmarker.task",
            project_root / "hardware" / "raspberry_pi" / "camera_to_Pi" / "models" / "hand_landmarker.task",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    # ---- Internal: Capture Loop (runs in background thread) ----

    def _capture_loop(self) -> None:
        """Main capture loop running in a background daemon thread.

        Captures frames from Picamera2, runs MediaPipe inference, extracts
        hand features, and pushes CameraFrame objects to the output queue.
        """
        fps_window: list[float] = []  # For actual FPS calculation
        last_fps_update = time.monotonic()
        self._init_preview_encoder()

        while self._running.is_set():
            try:
                t_start = time.monotonic()

                # Capture frame + metadata
                captured_array = self._picam2.capture_array("main")
                frame_array = self._to_rgb_array(captured_array)
                metadata = self._picam2.capture_metadata()
                sensor_ts_ns = metadata.get("SensorTimestamp", time.monotonic_ns())

                # Record Pi receive time immediately after capture for clock sync.
                # The offset (pi_receive_ns - sensor_ts_ns) = camera clock offset
                # + pipeline latency.  CameraClockSync models this with linear
                # regression, same pattern as BLE ClockSync.
                pi_receive_ns = time.monotonic_ns()
                self._camera_clock.add_frame(sensor_ts_ns, pi_receive_ns)
                aligned_ns = self._camera_clock.sensor_to_pi_ns(sensor_ts_ns)

                # Run MediaPipe inference
                mp_image = self._mp.Image(
                    image_format=self._mp.ImageFormat.SRGB,
                    data=frame_array,
                )
                timestamp_ms = sensor_ts_ns // 1_000_000
                result = self._hand_landmarker.detect_for_video(mp_image, timestamp_ms)

                # Extract hand data
                hands_data = self._extract_hand_data(result, sensor_ts_ns)
                preview_hands = self._update_preview_hands(hands_data)

                # Optional video tap (in-process MJPEG stream). Defensive:
                # a streamer exception must never break capture.
                cb = self.frame_image_callback
                if cb is not None:
                    try:
                        cb(frame_array, preview_hands)
                    except Exception:
                        pass

                # Compute processing latency
                t_end = time.monotonic()
                latency_ms = (t_end - t_start) * 1000.0
                self._processing_latency_ms = latency_ms

                # Create CameraFrame
                self._frame_counter += 1
                preview_jpeg = self._make_preview_jpeg(frame_array, preview_hands)
                frame = CameraFrame(
                    frame_id=self._frame_counter,
                    sensor_timestamp_ns=sensor_ts_ns,
                    pi_aligned_timestamp_ns=aligned_ns,
                    width=self._width,
                    height=self._height,
                    hands=hands_data,
                    processing_latency_ms=latency_ms,
                    clock_ready=self._camera_clock.clock_ready,
                    preview_jpeg=preview_jpeg,
                    raw_hands_detected=len(hands_data),
                    preview_interpolated_hands=self._preview_interpolated_hands,
                    hand_detection_rate_5s=self._hand_detection_rate(),
                    consecutive_missed_frames=self._consecutive_missed_frames,
                )

                # Push to queue
                try:
                    self._frame_queue.put_nowait(frame)
                    self._last_frame_time_ns = time.monotonic_ns()
                except queue.Full:
                    self._dropped_frames += 1
                    # Consumer too slow — log periodically
                    if self._dropped_frames % 30 == 0:
                        logger.warning(
                            "Camera queue full: %d frames dropped so far.",
                            self._dropped_frames,
                        )

                # Track actual FPS
                fps_window.append(t_end)
                if t_end - last_fps_update > 2.0:
                    recent = [t for t in fps_window if t_end - t < 2.0]
                    if len(recent) > 1:
                        self._actual_fps = len(recent) / (recent[-1] - recent[0])
                    last_fps_update = t_end

            except Exception as e:
                logger.error("Camera capture error: %s", e, exc_info=True)
                time.sleep(0.1)

    @staticmethod
    def _validate_confidence(name: str, value: float) -> float:
        normalized = float(value)
        if not 0.0 <= normalized <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
        return normalized

    def _to_rgb_array(self, frame_array: np.ndarray) -> np.ndarray:
        """Return contiguous RGB data for MediaPipe and preview encoders.

        Picamera2/libcamera format names describe packed pixels. A BGR888
        stream is exposed by capture_array as [R, G, B], while RGB888 is
        exposed as [B, G, R].
        """
        if self._pixel_format == "BGR888":
            return np.ascontiguousarray(frame_array)
        return np.ascontiguousarray(frame_array[:, :, ::-1])

    def _update_preview_hands(self, hands: list[dict]) -> list[dict]:
        """Bridge short detector gaps for display without altering raw samples."""
        detected = bool(hands)
        now = time.monotonic()
        with self._detection_lock:
            self._detection_window.append((now, 1 if detected else 0))
            self._prune_detection_window(now)
        self._consecutive_missed_frames = (
            0 if detected else self._consecutive_missed_frames + 1
        )

        display_hands: list[dict] = []
        current_keys: set[str] = set()
        for index, hand in enumerate(hands):
            key = str(hand.get("hand_id") or f"unknown-{index}")
            current_keys.add(key)
            current = deepcopy(hand)
            current["interpolated"] = False
            current["missing_frames"] = 0
            self._preview_tracks[key] = {"hand": deepcopy(current), "misses": 0}
            display_hands.append(current)

        for key, track in list(self._preview_tracks.items()):
            if key in current_keys:
                continue
            track["misses"] += 1
            if track["misses"] > self._max_missing_frames:
                del self._preview_tracks[key]
                continue
            held = deepcopy(track["hand"])
            held["interpolated"] = True
            held["missing_frames"] = track["misses"]
            display_hands.append(held)

        self._preview_interpolated_hands = sum(
            1 for hand in display_hands if hand.get("interpolated")
        )
        return display_hands

    def _hand_detection_rate(self) -> float:
        with self._detection_lock:
            self._prune_detection_window(time.monotonic())
            if not self._detection_window:
                return 0.0
            return sum(value for _, value in self._detection_window) / len(
                self._detection_window
            )

    def _prune_detection_window(self, now: float) -> None:
        cutoff = now - self._detection_window_seconds
        while self._detection_window and self._detection_window[0][0] < cutoff:
            self._detection_window.popleft()

    def _make_preview_jpeg(self, frame_array, hands: list[dict]) -> bytes | None:
        """Encode a lightweight JPEG preview frame for the in-process dashboard."""
        if not self._enable_preview_jpeg or self._cv2 is None:
            return None
        if self._frame_counter % self._preview_jpeg_every_n_frames != 0:
            return None

        try:
            cv2 = self._cv2
            bgr = cv2.cvtColor(frame_array, cv2.COLOR_RGB2BGR)
            height, width = bgr.shape[:2]
            for hand in hands:
                points = [
                    (int(p[0] * width), int(p[1] * height))
                    for p in hand.get("landmarks_normalized", [])
                ]
                color = (60, 220, 120) if hand.get("valid") else (50, 180, 255)
                for a, b in (
                    (0, 1), (1, 2), (2, 3), (3, 4),
                    (0, 5), (5, 6), (6, 7), (7, 8),
                    (5, 9), (9, 10), (10, 11), (11, 12),
                    (9, 13), (13, 14), (14, 15), (15, 16),
                    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
                ):
                    if a < len(points) and b < len(points):
                        cv2.line(bgr, points[a], points[b], color, 2, cv2.LINE_AA)
                for point in points:
                    cv2.circle(bgr, point, 3, (255, 255, 255), -1, cv2.LINE_AA)
                if points:
                    label = f"{hand.get('handedness', 'hand')} {hand.get('confidence', 0.0):.2f}"
                    cv2.putText(
                        bgr,
                        label,
                        (max(0, points[0][0] - 20), max(24, points[0][1] - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        color,
                        2,
                        cv2.LINE_AA,
                    )

            ok, encoded = cv2.imencode(
                ".jpg",
                bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), self._preview_jpeg_quality],
            )
            if not ok:
                return None
            return encoded.tobytes()
        except Exception:
            logger.debug("Preview JPEG encode failed", exc_info=True)
            return None

    # ---- Internal: Hand Feature Extraction ----

    def _extract_hand_data(self, mp_result, sensor_ts_ns: int) -> list[dict]:
        """Extract hand landmarks and compute visual features.

        Args:
            mp_result: MediaPipe HandLandmarkerResult.
            sensor_ts_ns: Camera sensor timestamp for this frame.

        Returns:
            List of hand dicts following the fused_frame.camera.hands[] schema.
        """
        if mp_result is None or not mp_result.hand_landmarks:
            return []

        hands = []
        used_hand_ids: set[str] = set()
        for idx, landmarks in enumerate(mp_result.hand_landmarks):
            # Handedness
            handedness = "unknown"
            confidence = 0.0
            if mp_result.handedness and idx < len(mp_result.handedness):
                categories = mp_result.handedness[idx]
                if categories:
                    handedness = categories[0].category_name.lower()
                    confidence = categories[0].score

            hand_id = handedness if handedness in {"left", "right"} else f"unknown-{idx}"
            if hand_id in used_hand_ids:
                hand_id = f"{hand_id}-{idx}"
            used_hand_ids.add(hand_id)

            # Normalized landmarks as [[x,y,z], ...]
            landmarks_raw = [
                [lm.x, lm.y, lm.z] for lm in landmarks
            ]
            world_landmarks = []
            if mp_result.hand_world_landmarks and idx < len(mp_result.hand_world_landmarks):
                world_landmarks = [
                    [lm.x, lm.y, lm.z]
                    for lm in mp_result.hand_world_landmarks[idx]
                ]

            # Apply temporal smoothing to reduce MediaPipe jitter
            timestamp_s = sensor_ts_ns / 1_000_000_000.0
            landmarks_normalized = self._landmark_smoother.smooth_landmarks(
                hand_id, landmarks_raw, timestamp_s
            )

            # Wrist position from smoothed landmarks (index 0)
            wrist_pos = (
                landmarks_normalized[0][0],
                landmarks_normalized[0][1],
                landmarks_normalized[0][2],
            )

            # Compute features using smoothed landmarks
            features = self._compute_camera_features(
                handedness, landmarks, wrist_pos, sensor_ts_ns
            )

            hand_data = {
                "hand_id": hand_id,
                "handedness": handedness,
                "confidence": confidence,
                "handedness_confidence": confidence,
                "confidence_type": "handedness",
                "valid": confidence >= 0.5,
                "interpolated": False,
                "missing_frames": 0,
                "landmarks_normalized": landmarks_normalized,
                "world_landmarks": world_landmarks,
                "features": features,
            }

            hands.append(hand_data)

        return hands

    def _compute_camera_features(
        self,
        handedness: str,
        landmarks,
        wrist_pos: tuple[float, float, float],
        sensor_ts_ns: int,
    ) -> dict:
        """Compute per-frame visual features for a single hand.

        Args:
            handedness: "left", "right", or "unknown".
            landmarks: MediaPipe NormalizedLandmark list.
            wrist_pos: (x, y, z) of wrist landmark.
            sensor_ts_ns: Frame timestamp.

        Returns:
            Features dict following fused_frame schema.
        """
        features = {
            "palm_center": self._compute_palm_center(landmarks),
            "palm_normal": [0.0, 0.0, 1.0],  # Placeholder
            "openness": self._compute_openness(landmarks),
            "finger_states": self._compute_finger_states(landmarks),
            "joint_angles": [],  # Placeholder
            "pinch_distance": self._compute_pinch_distance(landmarks),
            "wrist_position": list(wrist_pos),
            "wrist_velocity": [0.0, 0.0, 0.0],
            "wrist_acceleration": [0.0, 0.0, 0.0],
            "motion_direction": "still",
        }

        # Compute wrist velocity
        hand_key = f"{handedness}-wrist"
        prev_pos = self._prev_wrist_pos.get(hand_key)
        prev_time = self._prev_frame_time.get(hand_key, 0)

        if prev_pos is not None and prev_time > 0:
            dt_s = (sensor_ts_ns - prev_time) / 1_000_000_000.0
            if dt_s > 0:
                dx = (wrist_pos[0] - prev_pos[0]) / dt_s
                dy = (wrist_pos[1] - prev_pos[1]) / dt_s
                dz = (wrist_pos[2] - prev_pos[2]) / dt_s
                features["wrist_velocity"] = [dx, dy, dz]

                # Compute motion direction
                features["motion_direction"] = self._classify_direction(dx, dy, dz)

        # Store for next frame
        self._prev_wrist_pos[hand_key] = wrist_pos
        self._prev_frame_time[hand_key] = sensor_ts_ns

        return features

    # ---- Internal: Feature Helpers ----

    @staticmethod
    def _compute_palm_center(landmarks) -> list[float]:
        """Compute palm center as average of wrist + MCP joints."""
        # Landmarks: 0=wrist, 1=thumb_cmc, 5=index_mcp, 9=middle_mcp,
        #            13=ring_mcp, 17=pinky_mcp
        palm_indices = [0, 1, 5, 9, 13, 17]
        x = sum(landmarks[i].x for i in palm_indices) / len(palm_indices)
        y = sum(landmarks[i].y for i in palm_indices) / len(palm_indices)
        z = sum(landmarks[i].z for i in palm_indices) / len(palm_indices)
        return [x, y, z]

    @staticmethod
    def _compute_openness(landmarks) -> float:
        """Estimate palm openness from finger extension relative to palm.

        Returns:
            Value in [0, 1] where 0=fist, 1=fully open.
        """
        # Compare fingertip distances to wrist vs MCP distances to wrist.
        # Simplified: use the average distance of fingertips from the wrist
        # normalized by a reference distance.
        wrist = (landmarks[0].x, landmarks[0].y, landmarks[0].z)
        # Finger MCP joints: 5(index), 9(middle), 13(ring), 17(pinky)
        # Finger TIP joints: 8(index), 12(middle), 16(ring), 20(pinky)
        mcp_indices = [5, 9, 13, 17]
        tip_indices = [8, 12, 16, 20]

        def dist(a, b):
            return ((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2) ** 0.5

        # Reference: MCP-to-wrist distance (when fingers are curled, tips are close to MCPs)
        mcp_dists = [
            dist(wrist, (landmarks[i].x, landmarks[i].y, landmarks[i].z))
            for i in mcp_indices
        ]
        tip_dists = [
            dist(wrist, (landmarks[i].x, landmarks[i].y, landmarks[i].z))
            for i in tip_indices
        ]

        # Ratio: if tips > MCPs, hand is open
        ratios = []
        for mcp_d, tip_d in zip(mcp_dists, tip_dists):
            if mcp_d > 0:
                ratios.append(min(tip_d / mcp_d, 1.5))  # Cap at 1.5

        if not ratios:
            return 0.0

        openness = sum(ratios) / len(ratios)
        # Normalize: ratio ~1.0 means tip at MCP distance (curled)
        # ratio ~1.3+ means tip far from MCP (extended)
        # Map to [0, 1]: openness = (avg_ratio - 1.0) / 0.3
        return max(0.0, min(1.0, (openness - 1.0) / 0.3))

    @staticmethod
    def _compute_finger_states(landmarks) -> list[int]:
        """Estimate which fingers are extended.

        Returns:
            List of 5 ints (1=extended, 0=curled). Order: thumb, index,
            middle, ring, pinky.
        """
        wrist = (landmarks[0].x, landmarks[0].y, landmarks[0].z)

        def dist_to_wrist(idx):
            return (
                (landmarks[idx].x - wrist[0]) ** 2
                + (landmarks[idx].y - wrist[1]) ** 2
                + (landmarks[idx].z - wrist[2]) ** 2
            ) ** 0.5

        states = []
        # Thumb: tip(4) vs IP(3)
        thumb_tip = dist_to_wrist(4)
        thumb_ip = dist_to_wrist(3)
        states.append(1 if thumb_tip > thumb_ip * 1.1 else 0)

        # Other fingers: TIP vs PIP
        for tip_idx, pip_idx in [(8, 6), (12, 10), (16, 14), (20, 18)]:
            tip_d = dist_to_wrist(tip_idx)
            pip_d = dist_to_wrist(pip_idx)
            states.append(1 if tip_d > pip_d * 1.1 else 0)

        return states

    @staticmethod
    def _compute_pinch_distance(landmarks) -> float:
        """Compute distance between thumb tip and index fingertip."""
        thumb_tip = landmarks[4]
        index_tip = landmarks[8]
        return (
            (thumb_tip.x - index_tip.x) ** 2
            + (thumb_tip.y - index_tip.y) ** 2
            + (thumb_tip.z - index_tip.z) ** 2
        ) ** 0.5

    @staticmethod
    def _classify_direction(dx: float, dy: float, dz: float) -> str:
        """Classify wrist motion direction based on velocity components.

        Args:
            dx, dy, dz: Velocity components.

        Returns:
            One of: "up", "down", "left", "right", "forward", "backward", "still".
        """
        threshold = 0.01  # Minimum velocity magnitude for non-still
        abs_dx, abs_dy, abs_dz = abs(dx), abs(dy), abs(dz)

        if max(abs_dx, abs_dy, abs_dz) < threshold:
            return "still"

        # In image coordinates: y-down. So -dy = up, +dy = down
        if abs_dy >= abs_dx and abs_dy >= abs_dz:
            return "up" if dy < 0 else "down"
        elif abs_dx >= abs_dy and abs_dx >= abs_dz:
            return "right" if dx > 0 else "left"
        else:
            return "forward" if dz > 0 else "backward"
