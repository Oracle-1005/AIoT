from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from camera_to_pi.capture import CameraCaptureConfig, Picamera2CaptureWorker
from camera_to_pi.clock import CameraClockMapper
from camera_to_pi.detector import HandDetectorConfig, MediaPipeHandDetector
from camera_to_pi.quality import LandmarkNoiseProcessor, QualityConfig


LOGGER = logging.getLogger("visual-verify")

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Camera to Pi Visual Verify</title>
  <style>
    :root { color-scheme: dark; font-family: Arial, sans-serif; background: #101418; color: #eef3f7; }
    body { margin: 0; min-height: 100vh; display: grid; grid-template-rows: auto 1fr; }
    header { padding: 14px 18px; background: #17202a; border-bottom: 1px solid #2a3440; display: flex; justify-content: space-between; gap: 16px; align-items: center; }
    h1 { font-size: 18px; margin: 0; font-weight: 700; }
    main { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; padding: 16px; }
    .video { width: 100%; max-height: calc(100vh - 96px); object-fit: contain; background: #050607; border: 1px solid #2a3440; }
    aside { display: grid; gap: 10px; align-content: start; }
    .panel { background: #17202a; border: 1px solid #2a3440; padding: 12px; border-radius: 6px; }
    .row { display: flex; justify-content: space-between; gap: 10px; font-size: 14px; padding: 5px 0; border-bottom: 1px solid #26313c; }
    .row:last-child { border-bottom: 0; }
    .label { color: #aab7c4; }
    .ok { color: #6ee7a8; }
    .warn { color: #f4c56a; }
    .bad { color: #ff8a8a; }
    pre { white-space: pre-wrap; word-break: break-word; margin: 0; font-size: 12px; color: #cbd5df; }
    @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>Camera to Pi Visual Verify</h1>
    <span id="state" class="warn">connecting</span>
  </header>
  <main>
    <img class="video" src="/stream" alt="live camera stream">
    <aside>
      <section class="panel">
        <div class="row"><span class="label">Frames</span><strong id="frames">-</strong></div>
        <div class="row"><span class="label">FPS</span><strong id="fps">-</strong></div>
        <div class="row"><span class="label">Hands</span><strong id="hands">-</strong></div>
        <div class="row"><span class="label">Latency</span><strong id="latency">-</strong></div>
        <div class="row"><span class="label">Dropped</span><strong id="dropped">-</strong></div>
        <div class="row"><span class="label">Clock Ready</span><strong id="clock">-</strong></div>
      </section>
      <section class="panel"><pre id="raw">{}</pre></section>
    </aside>
  </main>
  <script>
    async function refresh() {
      try {
        const res = await fetch('/status', { cache: 'no-store' });
        const data = await res.json();
        const ok = data.running && data.frames > 0;
        document.getElementById('state').textContent = ok ? 'running' : 'waiting';
        document.getElementById('state').className = ok ? 'ok' : 'warn';
        document.getElementById('frames').textContent = data.frames ?? '-';
        document.getElementById('fps').textContent = (data.fps ?? 0).toFixed(1);
        document.getElementById('hands').textContent = data.hands_detected ?? '-';
        document.getElementById('latency').textContent = `${Math.round((data.latency_ms ?? 0))} ms`;
        document.getElementById('dropped').textContent = data.dropped_capture_frames ?? '-';
        document.getElementById('clock').textContent = data.clock_ready ? 'yes' : 'warming';
        document.getElementById('raw').textContent = JSON.stringify(data.last_frame ?? {}, null, 2);
      } catch (err) {
        document.getElementById('state').textContent = 'disconnected';
        document.getElementById('state').className = 'bad';
      }
    }
    setInterval(refresh, 500);
    refresh();
  </script>
</body>
</html>
"""

CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]


class SharedState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jpeg: bytes | None = None
        self.status: dict[str, Any] = {"running": False, "frames": 0}

    def update(self, jpeg: bytes, status: dict[str, Any]) -> None:
        with self.lock:
            self.jpeg = jpeg
            self.status = status

    def snapshot(self) -> tuple[bytes | None, dict[str, Any]]:
        with self.lock:
            return self.jpeg, dict(self.status)


def load_config(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def annotate(image: np.ndarray, hands: list[Any], input_order: str) -> np.ndarray:
    if input_order.upper() == "RGB":
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    else:
        bgr = np.ascontiguousarray(image)
    height, width = bgr.shape[:2]
    for hand in hands:
        color = (70, 220, 120) if hand.detection_valid else (50, 180, 255)
        points = [(int(p.x * width), int(p.y * height)) for p in hand.image_landmarks]
        for a, b in CONNECTIONS:
            if a < len(points) and b < len(points):
                cv2.line(bgr, points[a], points[b], color, 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(bgr, point, 3, (255, 255, 255), -1, cv2.LINE_AA)
        if points:
            cv2.putText(
                bgr,
                f"{hand.hand_label} {hand.handedness_score:.2f}",
                (max(0, points[0][0] - 20), max(24, points[0][1] - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
                cv2.LINE_AA,
            )
    return bgr


def worker(config_path: str, state: SharedState, stop: threading.Event) -> None:
    config = load_config(config_path)
    camera_cfg = CameraCaptureConfig(**config.get("camera", {}))
    detector_cfg = HandDetectorConfig(**config.get("detector", {}))
    quality_cfg = QualityConfig(**config.get("quality", {}))
    clock_cfg = config.get("clock", {})

    capture = Picamera2CaptureWorker(camera_cfg)
    detector = MediaPipeHandDetector(detector_cfg)
    quality = LandmarkNoiseProcessor(quality_cfg)
    clock = CameraClockMapper(
        window_size=int(clock_cfg.get("window_size", 120)),
        min_ready_samples=int(clock_cfg.get("min_ready_samples", 10)),
    )

    last_fps_t = time.monotonic()
    frames_since = 0
    fps = 0.0
    total = 0
    capture.start()
    try:
        while not stop.is_set():
            frame = capture.get(timeout=3.0)
            mapping = clock.update(frame.sensor_timestamp_ns, frame.pi_frame_received_ns)
            media_timestamp_ms = clock.media_timestamp_ms(frame.sensor_timestamp_ns)
            raw_hands = detector.detect(frame.image, media_timestamp_ms)
            hands = quality.process(raw_hands, mapping.pi_aligned_timestamp_ns)
            finished_ns = time.monotonic_ns()

            total += 1
            frames_since += 1
            now = time.monotonic()
            elapsed = now - last_fps_t
            if elapsed >= 1.0:
                fps = frames_since / elapsed
                frames_since = 0
                last_fps_t = now

            bgr = annotate(frame.image, hands, detector_cfg.input_array_order)
            ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok:
                continue
            last_frame = {
                "frame_sequence": frame.frame_sequence,
                "sensor_timestamp_ns": frame.sensor_timestamp_ns,
                "pi_aligned_timestamp_ns": mapping.pi_aligned_timestamp_ns,
                "hands": [
                    {
                        "hand_label": hand.hand_label,
                        "score": round(hand.handedness_score, 3),
                        "valid": hand.detection_valid,
                        "source": hand.source,
                        "flags": hand.quality_flags,
                    }
                    for hand in hands
                ],
            }
            state.update(
                encoded.tobytes(),
                {
                    "running": True,
                    "frames": total,
                    "fps": fps,
                    "hands_detected": sum(1 for h in hands if h.source == "detected"),
                    "hands_output": len(hands),
                    "latency_ms": (finished_ns - frame.pi_frame_received_ns) / 1_000_000.0,
                    "dropped_capture_frames": capture.frames.dropped_frames,
                    "clock_ready": mapping.ready,
                    "last_frame": last_frame,
                },
            )
    finally:
        capture.stop()
        detector.close()
        state.status["running"] = False


def make_handler(state: SharedState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            LOGGER.debug(fmt, *args)

        def do_GET(self) -> None:
            if self.path == "/":
                body = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/status":
                _, status = state.snapshot()
                body = json.dumps(status, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while True:
                    jpeg, _ = state.snapshot()
                    if jpeg is None:
                        time.sleep(0.1)
                        continue
                    try:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                        time.sleep(0.05)
                    except (BrokenPipeError, ConnectionResetError):
                        break
                return
            self.send_error(404)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Browser visual verifier for camera-to-pi.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    state = SharedState()
    stop = threading.Event()
    thread = threading.Thread(target=worker, args=(args.config, state, stop), daemon=True)
    thread.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    LOGGER.info("visual verifier listening on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
