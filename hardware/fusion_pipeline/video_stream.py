"""Optional in-process MJPEG live video stream for the fusion pipeline.

Lets a browser watch the camera (with MediaPipe landmark overlay) WHILE
pi-fusion is running. The camera device is single-owner on Linux, so the
standalone previews (8765 camera / 8790 joint) cannot run together with
pi-fusion. This streamer instead taps frames from the running
``CameraSensor`` via ``CameraSensor.frame_image_callback`` and JPEG-encodes
them in a separate worker thread. The capture thread only hands the frame
into a single-slot buffer (latest wins), so streaming never blocks fusion.

Enable in config.yaml:

    video_stream:
      enabled: true
      host: "0.0.0.0"
      port: 8791
      fps: 10          # encode/send cap (camera itself stays at 30 fps)
      quality: 70      # JPEG quality
      annotate: true   # overlay MediaPipe landmarks

Then open http://<pi-ip>:8791/ while pi-fusion runs.
Disabled by default — zero cost when off.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

_INDEX_HTML = b"""<!doctype html>
<html><head><meta charset="utf-8"><title>pi-fusion video</title>
<style>body{margin:0;background:#111;display:flex;justify-content:center}
img{max-width:100vw;max-height:100vh}</style></head>
<body><img src="/stream" alt="camera stream"></body></html>"""


class MjpegStreamer:
    """Latest-frame MJPEG HTTP server fed by the camera capture thread."""

    def __init__(self, *, host: str = "0.0.0.0", port: int = 8791,
                 fps: float = 10.0, quality: int = 70,
                 annotate: bool = True) -> None:
        self._host = host
        self._port = int(port)
        self._min_interval = 1.0 / max(1.0, float(fps))
        self._quality = int(quality)
        self._annotate = bool(annotate)

        self._cv2 = None
        self._server: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._running = False

        # Single-slot handoff buffer, latest frame wins.
        self._pending: tuple | None = None
        self._pending_lock = threading.Lock()
        self._last_submit = 0.0

        self._cond = threading.Condition()  # signals a fresh JPEG to clients
        self._latest_jpeg: bytes | None = None
        self.frames_encoded = 0
        self.frames_dropped = 0

    # -- lifecycle -------------------------------------------------------

    def start(self) -> bool:
        """Start encoder worker + HTTP server. False if cv2 unavailable."""
        try:
            import cv2  # noqa: PLC0415
            self._cv2 = cv2
        except ImportError:
            logger.error("video_stream: cv2 not available — stream disabled")
            return False

        streamer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path.startswith("/stream"):
                    try:
                        streamer._serve_mjpeg(self)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                elif self.path.startswith("/health"):
                    streamer._serve_health(self)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(_INDEX_HTML)))
                    self.end_headers()
                    self.wfile.write(_INDEX_HTML)

            def log_message(self, *_args):  # keep journald output clean
                pass

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._server.daemon_threads = True
        self._running = True
        self._http_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="mjpeg-http")
        self._worker = threading.Thread(
            target=self._encode_loop, daemon=True, name="mjpeg-encode")
        self._http_thread.start()
        self._worker.start()
        logger.info(
            "video_stream: MJPEG on http://%s:%d/ (fps<=%g, quality=%d, annotate=%s)",
            self._host, self._port, 1.0 / self._min_interval,
            self._quality, self._annotate)
        return True

    def stop(self) -> None:
        """Stop HTTP server and worker; safe to call more than once."""
        self._running = False
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        with self._cond:
            self._cond.notify_all()
        for thread in (self._http_thread, self._worker):
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
        logger.info("video_stream: stopped (encoded=%d dropped=%d)",
                    self.frames_encoded, self.frames_dropped)

    # -- producer (called from the camera capture thread) ----------------

    def submit(self, rgb_array, hands) -> None:
        """Hand off a raw RGB frame + hands list. Never blocks the caller."""
        if not self._running:
            return
        now = time.monotonic()
        if now - self._last_submit < self._min_interval:
            return
        with self._pending_lock:
            if self._pending is not None:
                self.frames_dropped += 1  # encoder busy — drop this frame
                return
            self._pending = (rgb_array, hands)
            self._last_submit = now

    # -- encoder worker --------------------------------------------------

    def _encode_loop(self) -> None:
        cv2 = self._cv2
        while self._running:
            with self._pending_lock:
                item = self._pending
                self._pending = None
            if item is None:
                time.sleep(0.005)
                continue
            rgb, hands = item
            try:
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                if self._annotate and hands:
                    self._draw_hands(bgr, hands)
                ok, enc = cv2.imencode(
                    ".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), self._quality])
            except Exception:
                logger.debug("video_stream: encode failed", exc_info=True)
                continue
            if not ok:
                continue
            with self._cond:
                self._latest_jpeg = enc.tobytes()
                self.frames_encoded += 1
                self._cond.notify_all()

    def _draw_hands(self, bgr, hands) -> None:
        """Overlay MediaPipe landmarks (normalized coords → pixels)."""
        cv2 = self._cv2
        height, width = bgr.shape[:2]
        colors = {"left": (255, 190, 40), "right": (60, 200, 255)}  # BGR
        for hand in hands:
            if not isinstance(hand, dict):
                continue
            lms = hand.get("landmarks_normalized") or []
            color = colors.get(str(hand.get("handedness", "")).lower(),
                               (80, 255, 120))
            for lm in lms:
                if len(lm) >= 2:
                    cv2.circle(bgr, (int(lm[0] * width), int(lm[1] * height)),
                               3, color, -1)
            if lms and len(lms[0]) >= 2:
                wrist = (int(lms[0][0] * width), int(lms[0][1] * height))
                cv2.circle(bgr, wrist, 7, color, 2)
                cv2.putText(bgr, str(hand.get("handedness", "?")),
                            (wrist[0] + 10, wrist[1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # -- HTTP endpoints --------------------------------------------------

    def _serve_mjpeg(self, req: BaseHTTPRequestHandler) -> None:
        req.send_response(200)
        req.send_header("Content-Type",
                        "multipart/x-mixed-replace; boundary=frame")
        req.send_header("Cache-Control", "no-cache")
        req.end_headers()
        last_sent = None
        while self._running:
            with self._cond:
                self._cond.wait(timeout=2.0)
                data = self._latest_jpeg
            if data is None or data is last_sent:
                continue
            req.wfile.write(
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n")
            req.wfile.flush()
            last_sent = data

    def _serve_health(self, req: BaseHTTPRequestHandler) -> None:
        body = json.dumps({
            "running": self._running,
            "frames_encoded": self.frames_encoded,
            "frames_dropped": self.frames_dropped,
        }).encode()
        req.send_response(200)
        req.send_header("Content-Type", "application/json")
        req.send_header("Content-Length", str(len(body)))
        req.end_headers()
        req.wfile.write(body)
