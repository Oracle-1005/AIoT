from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path
from threading import Event
from typing import Any

from camera_to_pi.capture import CameraCaptureConfig, Picamera2CaptureWorker
from camera_to_pi.clock import CameraClockMapper
from camera_to_pi.detector import HandDetectorConfig, MediaPipeHandDetector
from camera_to_pi.models import CameraLandmarkFrame
from camera_to_pi.output import JsonLinesWriter
from camera_to_pi.quality import LandmarkNoiseProcessor, QualityConfig

LOGGER = logging.getLogger("camera-to-pi")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture OV5647 frames and emit MediaPipe hand landmarks as JSON Lines."
    )
    parser.add_argument("--config", default="config.json", help="path to JSON configuration")
    parser.add_argument("--max-frames", type=int, default=0, help="0 means run continuously")
    parser.add_argument("--output", default=None, help="JSONL output path; default is stdout")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON for debugging")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config)

    camera_cfg = CameraCaptureConfig(**config.get("camera", {}))
    detector_cfg = HandDetectorConfig(**config.get("detector", {}))
    quality_cfg = QualityConfig(**config.get("quality", {}))
    clock_cfg = config.get("clock", {})

    stop_event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    capture = Picamera2CaptureWorker(camera_cfg)
    detector = MediaPipeHandDetector(detector_cfg)
    quality = LandmarkNoiseProcessor(quality_cfg)
    clock = CameraClockMapper(
        window_size=int(clock_cfg.get("window_size", 120)),
        min_ready_samples=int(clock_cfg.get("min_ready_samples", 10)),
    )
    writer = JsonLinesWriter(args.output, pretty=args.pretty)

    emitted = 0
    capture.start()
    LOGGER.info(
        "camera pipeline started: %dx%d @ %.1f FPS, format=%s",
        camera_cfg.width,
        camera_cfg.height,
        camera_cfg.fps,
        camera_cfg.pixel_format,
    )

    try:
        while not stop_event.is_set() and (args.max_frames <= 0 or emitted < args.max_frames):
            frame = capture.get(timeout=3.0)
            mapping = clock.update(frame.sensor_timestamp_ns, frame.pi_frame_received_ns)
            media_timestamp_ms = clock.media_timestamp_ms(frame.sensor_timestamp_ns)
            raw_hands = detector.detect(frame.image, media_timestamp_ms)
            hands = quality.process(raw_hands, mapping.pi_aligned_timestamp_ns)

            output_frame = CameraLandmarkFrame(
                frame_sequence=frame.frame_sequence,
                sensor_timestamp_ns=frame.sensor_timestamp_ns,
                pi_frame_received_ns=frame.pi_frame_received_ns,
                media_timestamp_ms=media_timestamp_ms,
                width=frame.width,
                height=frame.height,
                pixel_format=frame.pixel_format,
                metadata=frame.metadata,
                hands=hands,
                clock=mapping,
                processing_finished_ns=time.monotonic_ns(),
                dropped_capture_frames=capture.frames.dropped_frames,
            )
            writer.write(output_frame.to_dict())
            emitted += 1
    except TimeoutError:
        LOGGER.exception("camera produced no frame; check CSI connection and rpicam-hello")
        return 2
    except Exception:
        LOGGER.exception("camera pipeline failed")
        return 1
    finally:
        capture.stop()
        detector.close()
        writer.close()
        LOGGER.info("camera pipeline stopped after %d output frames", emitted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
