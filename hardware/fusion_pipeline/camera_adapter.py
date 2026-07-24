"""Camera adapter: wraps sensors/camera.py CameraSensor for the fusion pipeline.

Provides:
  - Thread-safe frame polling (CameraSensor runs MediaPipe in a background thread)
  - CameraClockSync integration (SensorTimestamp → Pi monotonic_ns)
  - Per-frame status tracking (fps, dropped, clock_ready)

The existing CameraSensor in sensors/camera.py already handles:
  - Picamera2 capture
  - MediaPipe Hand Landmarker inference
  - LandmarkSmoother (temporal smoothing)
  - CameraClockSync (linear-regression clock mapping)
  - CameraFrame output via thread-safe queue

This adapter adds buffer-age pruning and unified status reporting.
"""

from __future__ import annotations

import logging
import time
from collections import deque

from pi_pc.camera_clock import CameraClockSync

logger = logging.getLogger(__name__)


class CameraAdapter:
    """Thin wrapper around CameraSensor with buffer management.

    Args:
        width: Image width.
        height: Image height.
        fps: Target frame rate.
        max_hands: Max hands for MediaPipe detection.
        frame_queue_size: CameraSensor internal queue size.
        buffer_max_age_s: Max age of buffered camera frames before pruning.
        clock_min_points: Min points before CameraClockSync.clock_ready.
        clock_max_points: Max retained calibration points.
    """

    def __init__(
        self,
        *,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        max_hands: int = 2,
        frame_queue_size: int = 10,
        buffer_max_age_s: float = 10.0,
        clock_min_points: int = 10,
        clock_max_points: int = 60,
        enable_preview_jpeg: bool = False,
        preview_jpeg_quality: int = 70,
        preview_jpeg_every_n_frames: int = 2,
    ) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._max_hands = max_hands
        self._frame_queue_size = frame_queue_size
        self._enable_preview_jpeg = enable_preview_jpeg
        self._preview_jpeg_quality = preview_jpeg_quality
        self._preview_jpeg_every_n_frames = preview_jpeg_every_n_frames

        # Camera frame buffer: time-sorted, oldest at index 0.
        # Each entry: {"ts_ns": pi_aligned_timestamp_ns, "frame_id": ..., "hands": [...]}
        self._buffer: deque[dict] = deque()
        self._buffer_max_age_ns = int(buffer_max_age_s * 1_000_000_000)

        # Lazy-imported CameraSensor (import fails on non-RPi)
        self._sensor = None
        self._running = False

        # Status tracking
        self._dropped_frames = 0
        self._latest_frame: dict | None = None
        self._clock_ready = False

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Initialize CameraSensor and begin capture.

        Returns:
            True if started successfully.
        """
        try:
            from sensors.camera import CameraSensor  # noqa: PLC0415

            self._sensor = CameraSensor(
                width=self._width,
                height=self._height,
                fps=self._fps,
                max_hands=self._max_hands,
                frame_queue_size=self._frame_queue_size,
                enable_preview_jpeg=self._enable_preview_jpeg,
                preview_jpeg_quality=self._preview_jpeg_quality,
                preview_jpeg_every_n_frames=self._preview_jpeg_every_n_frames,
            )
        except ImportError as exc:
            logger.error("Camera not available: %s", exc)
            return False
        except Exception as exc:
            logger.error("Camera init failed: %s", exc)
            return False

        ok = self._sensor.start()
        if not ok:
            logger.error("CameraSensor.start() failed")
            return False

        self._running = True
        logger.info("CameraAdapter started: %dx%d @ %d FPS", self._width, self._height, self._fps)
        return True

    def stop(self) -> None:
        """Stop capture and release resources."""
        self._running = False
        if self._sensor:
            self._sensor.stop()
            self._sensor = None
        logger.info("CameraAdapter stopped.")

    # ── Public API ─────────────────────────────────────────────────────────

    def poll_frame(self) -> dict | None:
        """Poll for the next available CameraFrame (non-blocking).

        Converts the internal CameraFrame into a buffer-compatible dict
        and prunes old entries.

        Returns:
            Dict with keys: ts_ns, frame_id, width, height, hands,
            hands_detected, processing_latency_ms, clock_ready.  None if
            no frame is available.
        """
        if not self._sensor or not self._running:
            return None

        try:
            camera_frame = self._sensor.get_frame(timeout=0.0)
        except Exception:
            logger.debug("Camera get_frame error", exc_info=True)
            return None

        if camera_frame is None:
            return None

        # Track dropped frames
        status = self._sensor.get_status()
        self._dropped_frames = status.get("dropped_frames", 0)
        self._clock_ready = status.get("clock_ready", False)

        # Build buffer entry
        hands = camera_frame.hands or []
        entry = {
            "ts_ns": camera_frame.pi_aligned_timestamp_ns,
            "frame_id": camera_frame.frame_id,
            "width": camera_frame.width,
            "height": camera_frame.height,
            "hands": hands,
            "hands_detected": len(hands),
            "processing_latency_ms": camera_frame.processing_latency_ms,
            "clock_ready": camera_frame.clock_ready,
            "preview_jpeg": camera_frame.preview_jpeg,
        }

        # Push to internal buffer and prune
        self._buffer.append(entry)
        self._prune(entry["ts_ns"])
        self._latest_frame = entry

        return entry

    def get_buffer(self) -> deque[dict]:
        """Return the camera frame buffer (for direct access by FusionEngine)."""
        return self._buffer

    def get_status(self) -> dict:
        """Return camera status for the periodic status message."""
        fps = 0.0
        if self._sensor:
            try:
                status = self._sensor.get_status()
                fps = status.get("actual_fps", 0.0)
                self._dropped_frames = status.get("dropped_frames", 0)
                self._clock_ready = status.get("clock_ready", False)
            except Exception:
                pass

        hands_detected = 0
        if self._latest_frame:
            hands_detected = self._latest_frame.get("hands_detected", 0)

        return {
            "fps": round(fps, 1),
            "hands_detected": hands_detected,
            "dropped_capture_frames": self._dropped_frames,
            "clock_ready": self._clock_ready,
        }

    def is_running(self) -> bool:
        return self._running

    def set_frame_image_callback(self, callback) -> None:
        """Attach a raw-frame callback on the underlying CameraSensor.

        The callback receives (rgb_frame_array, hands_data) from the
        capture thread — used by the optional MJPEG video stream
        (fusion_pipeline/video_stream.py).  Pass None to detach.
        """
        if self._sensor is not None:
            self._sensor.frame_image_callback = callback

    # ── Internal ───────────────────────────────────────────────────────────

    def _prune(self, current_ns: int) -> int:
        """Remove frames older than buffer_max_age_s from *current_ns*."""
        cutoff = current_ns - self._buffer_max_age_ns
        count = 0
        while self._buffer and self._buffer[0]["ts_ns"] < cutoff:
            self._buffer.popleft()
            count += 1
        return count
