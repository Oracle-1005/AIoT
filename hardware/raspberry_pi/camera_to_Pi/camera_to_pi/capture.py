from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from .models import CameraFrame, CameraMetadata

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CameraCaptureConfig:
    width: int = 640
    height: int = 480
    fps: float = 30.0
    pixel_format: str = "RGB888"
    queue_size: int = 2
    buffer_count: int = 4
    horizontal_flip: bool = False
    vertical_flip: bool = False
    warmup_seconds: float = 1.0


class LatestFrameQueue:
    """Bounded queue that drops the oldest frame instead of accumulating latency."""

    def __init__(self, maxsize: int) -> None:
        self._queue: queue.Queue[CameraFrame] = queue.Queue(maxsize=maxsize)
        self.dropped_frames = 0

    def put_latest(self, frame: CameraFrame) -> None:
        try:
            self._queue.put_nowait(frame)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
            self.dropped_frames += 1
        except queue.Empty:
            pass
        self._queue.put_nowait(frame)

    def get(self, timeout: float | None = None) -> CameraFrame:
        return self._queue.get(timeout=timeout)


class Picamera2CaptureWorker:
    def __init__(self, config: CameraCaptureConfig) -> None:
        self.config = config
        self.frames = LatestFrameQueue(config.queue_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._picam2: Any = None
        self._error: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("capture worker already started")
        self._thread = threading.Thread(target=self._run, name="camera-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if self._picam2 is not None:
            try:
                self._picam2.stop()
            except Exception:
                LOGGER.exception("failed to stop Picamera2 cleanly")

    def get(self, timeout: float = 2.0) -> CameraFrame:
        if self._error is not None:
            raise RuntimeError("camera capture worker failed") from self._error
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty as exc:
            if self._error is not None:
                raise RuntimeError("camera capture worker failed") from self._error
            raise TimeoutError("no camera frame received within timeout") from exc

    def _run(self) -> None:
        try:
            from libcamera import Transform
            from picamera2 import Picamera2

            self._picam2 = Picamera2()
            frame_duration_us = int(round(1_000_000 / self.config.fps))
            configuration = self._picam2.create_video_configuration(
                main={
                    "size": (self.config.width, self.config.height),
                    "format": self.config.pixel_format,
                },
                controls={"FrameDurationLimits": (frame_duration_us, frame_duration_us)},
                transform=Transform(
                    hflip=int(self.config.horizontal_flip),
                    vflip=int(self.config.vertical_flip),
                ),
                buffer_count=self.config.buffer_count,
                queue=False,
            )
            self._picam2.configure(configuration)
            self._picam2.start()
            if self.config.warmup_seconds > 0:
                time.sleep(self.config.warmup_seconds)

            sequence = 0
            while not self._stop.is_set():
                request = self._picam2.capture_request()
                try:
                    # make_array may reference a camera-owned buffer, so copy before release.
                    image = request.make_array("main").copy()
                    metadata = request.get_metadata()
                    received_ns = time.monotonic_ns()
                finally:
                    request.release()

                sensor_timestamp_ns = int(metadata.get("SensorTimestamp", received_ns))
                frame = CameraFrame(
                    frame_sequence=sequence,
                    sensor_timestamp_ns=sensor_timestamp_ns,
                    pi_frame_received_ns=received_ns,
                    width=int(image.shape[1]),
                    height=int(image.shape[0]),
                    pixel_format=self.config.pixel_format,
                    image=image,
                    metadata=CameraMetadata(
                        exposure_time_us=_optional_int(metadata.get("ExposureTime")),
                        analogue_gain=_optional_float(metadata.get("AnalogueGain")),
                        frame_duration_us=_optional_int(metadata.get("FrameDuration")),
                    ),
                )
                self.frames.put_latest(frame)
                sequence += 1
        except BaseException as exc:
            self._error = exc
            LOGGER.exception("camera capture thread stopped due to an error")


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
