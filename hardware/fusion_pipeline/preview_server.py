"""In-process preview server for the formal fusion pipeline.

The server is intentionally read-only: it observes the same camera frames,
micro:bit samples, and outbound messages that main.py uses for the PC backend.
It does not open the camera or bind the ESP32 UDP port by itself.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIoT 正式链路预览</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #647087;
      --line: #d8dee8;
      --good: #14804a;
      --warn: #aa6400;
      --bad: #ba2f3b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      min-height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 10px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 18px; font-weight: 700; }
    .status { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: flex-end; }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 5px 9px; background: #fbfcfe; font-size: 13px; color: var(--muted); }
    .good { color: var(--good); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    main { padding: 16px; display: grid; gap: 16px; grid-template-columns: minmax(420px, 0.9fr) 1.1fr; }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    .wide { grid-column: 1 / -1; }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }
    h2 { margin: 0; font-size: 15px; }
    .video {
      display: block;
      width: 100%;
      aspect-ratio: 4 / 3;
      object-fit: contain;
      background: #101826;
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
    .metric { border: 1px solid var(--line); border-radius: 6px; padding: 9px; min-height: 58px; }
    .label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
    .value { font: 700 18px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .split { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    pre {
      margin: 0;
      height: 300px;
      overflow: auto;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #101826;
      color: #dce8ff;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .small { height: 220px; }
    @media (max-width: 1080px) {
      main { grid-template-columns: 1fr; padding: 12px; }
      .wide { grid-column: auto; }
      .split { grid-template-columns: 1fr; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      header { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>AIoT 正式传输链路预览</h1>
    <div class="status">
      <span id="running" class="pill">starting</span>
      <span id="tcp" class="pill">PC --</span>
      <span id="gateway" class="pill">micro:bit --</span>
      <span id="camera" class="pill">camera --</span>
      <span id="fusion" class="pill">fused --</span>
    </div>
  </header>

  <main>
    <section>
      <div class="section-head">
        <h2>摄像头视频帧</h2>
        <span id="camera-age" class="pill">--</span>
      </div>
      <img class="video" src="/stream" alt="camera preview">
      <div class="grid">
        <div class="metric"><span class="label">frame</span><span id="frame-id" class="value">--</span></div>
        <div class="metric"><span class="label">hands</span><span id="hands" class="value">--</span></div>
        <div class="metric"><span class="label">clock</span><span id="clock" class="value">--</span></div>
        <div class="metric"><span class="label">latency</span><span id="latency" class="value">--</span></div>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>摄像头 MediaPipe 数据</h2>
        <span class="pill">含 world_landmarks</span>
      </div>
      <pre id="camera-json"></pre>
    </section>

    <section>
      <div class="section-head">
        <h2>micro:bit 刚采集/刚解码数据</h2>
        <span id="raw-age" class="pill">--</span>
      </div>
      <div class="split">
        <pre id="raw-left" class="small"></pre>
        <pre id="raw-right" class="small"></pre>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>micro:bit 降噪过滤后数据</h2>
        <span id="filtered-age" class="pill">--</span>
      </div>
      <div class="split">
        <pre id="filtered-left" class="small"></pre>
        <pre id="filtered-right" class="small"></pre>
      </div>
    </section>

    <section class="wide">
      <div class="section-head">
        <h2>正式发送给 PC 后端前的完整消息</h2>
        <span id="outbound-age" class="pill">--</span>
      </div>
      <pre id="outbound-json"></pre>
    </section>

    <section class="wide">
      <div class="section-head">
        <h2>最近发送前消息队列</h2>
        <span class="pill">fused_frame / control_event / status</span>
      </div>
      <pre id="tail-json"></pre>
    </section>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const pretty = (obj) => JSON.stringify(obj ?? {}, null, 2);
    const ageText = (age) => age === null || age === undefined ? "--" : `${Math.round(age)} ms`;
    function side(data, group, hand) {
      return data[group] && data[group][hand] ? data[group][hand] : null;
    }
    function setClassByAge(el, age, staleMs) {
      el.className = "pill " + (age !== null && age < staleMs ? "good" : "warn");
    }
    async function refresh() {
      try {
        const res = await fetch("/state", { cache: "no-store" });
        const data = await res.json();
        const tcp = data.tcp_status || {};
        $("running").textContent = data.running ? "pi-fusion running" : "stopped";
        $("running").className = "pill " + (data.running ? "good" : "bad");
        $("tcp").textContent = `PC ${tcp.pc_connected ? "connected" : "offline"} / q ${tcp.queued_messages ?? 0}`;
        $("tcp").className = "pill " + (tcp.pc_connected ? "good" : "warn");
        $("gateway").textContent = `raw ${data.counters.raw_microbit} / filtered ${data.counters.filtered_microbit}`;
        $("camera").textContent = `camera ${data.counters.camera_frames}`;
        $("fusion").textContent = `fused ${data.counters.fused_frames}`;

        const cam = data.latest_camera || {};
        $("frame-id").textContent = cam.frame_id ?? "--";
        $("hands").textContent = cam.hands_detected ?? "--";
        $("clock").textContent = cam.clock_ready ? "ready" : "warming";
        $("latency").textContent = cam.processing_latency_ms !== undefined ? `${Math.round(cam.processing_latency_ms)} ms` : "--";
        $("camera-json").textContent = pretty(cam);
        $("camera-age").textContent = ageText(data.ages_ms.camera);
        setClassByAge($("camera-age"), data.ages_ms.camera, 1200);

        $("raw-left").textContent = pretty(side(data, "latest_raw_microbits", "left"));
        $("raw-right").textContent = pretty(side(data, "latest_raw_microbits", "right"));
        $("raw-age").textContent = ageText(data.ages_ms.raw_microbit);
        setClassByAge($("raw-age"), data.ages_ms.raw_microbit, 1500);

        $("filtered-left").textContent = pretty(side(data, "latest_filtered_microbits", "left"));
        $("filtered-right").textContent = pretty(side(data, "latest_filtered_microbits", "right"));
        $("filtered-age").textContent = ageText(data.ages_ms.filtered_microbit);
        setClassByAge($("filtered-age"), data.ages_ms.filtered_microbit, 1500);

        $("outbound-json").textContent = pretty(data.latest_outbound);
        $("outbound-age").textContent = ageText(data.ages_ms.outbound);
        setClassByAge($("outbound-age"), data.ages_ms.outbound, 1500);
        $("tail-json").textContent = pretty(data.outbound_tail);
      } catch (err) {
        $("running").textContent = "preview disconnected";
        $("running").className = "pill bad";
      }
    }
    setInterval(refresh, 300);
    refresh();
  </script>
</body>
</html>
"""


class PreviewState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.latest_camera: dict[str, Any] | None = None
        self.latest_jpeg: bytes | None = None
        self.latest_raw_microbits: dict[str, dict[str, Any]] = {}
        self.latest_filtered_microbits: dict[str, dict[str, Any]] = {}
        self.latest_outbound: dict[str, Any] | None = None
        self.outbound_tail: deque[dict[str, Any]] = deque(maxlen=20)
        self.tcp_status: dict[str, Any] = {}
        self.update_times_ns = {
            "camera": 0,
            "raw_microbit": 0,
            "filtered_microbit": 0,
            "outbound": 0,
            "jpeg": 0,
        }
        self.counters = {
            "camera_frames": 0,
            "raw_microbit": 0,
            "filtered_microbit": 0,
            "fused_frames": 0,
            "control_events": 0,
            "status_messages": 0,
        }

    def set_running(self, running: bool) -> None:
        with self._lock:
            self.running = running

    def set_tcp_status(self, status: dict[str, Any]) -> None:
        with self._lock:
            self.tcp_status = deepcopy(status)

    def set_camera(self, frame: dict[str, Any]) -> None:
        camera = dict(frame)
        jpeg = camera.pop("preview_jpeg", None)
        with self._lock:
            self.latest_camera = deepcopy(camera)
            if jpeg:
                self.latest_jpeg = jpeg
                self.update_times_ns["jpeg"] = time.monotonic_ns()
            self.update_times_ns["camera"] = time.monotonic_ns()
            self.counters["camera_frames"] += 1

    def set_raw_microbit(self, item: dict[str, Any]) -> None:
        source = str(item.get("source", ""))
        with self._lock:
            if source in {"left", "right"}:
                self.latest_raw_microbits[source] = deepcopy(item)
            self.update_times_ns["raw_microbit"] = time.monotonic_ns()
            self.counters["raw_microbit"] += 1

    def set_filtered_microbit(self, item: dict[str, Any]) -> None:
        source = str(item.get("source", ""))
        with self._lock:
            if source in {"left", "right"}:
                self.latest_filtered_microbits[source] = deepcopy(item)
            self.update_times_ns["filtered_microbit"] = time.monotonic_ns()
            self.counters["filtered_microbit"] += 1

    def add_outbound(self, message: dict[str, Any]) -> None:
        item = deepcopy(message)
        message_type = item.get("type")
        with self._lock:
            self.latest_outbound = item
            self.outbound_tail.appendleft(item)
            self.update_times_ns["outbound"] = time.monotonic_ns()
            if message_type == "fused_frame":
                self.counters["fused_frames"] += 1
            elif message_type == "control_event":
                self.counters["control_events"] += 1
            elif message_type == "status":
                self.counters["status_messages"] += 1

    def latest_jpeg_snapshot(self) -> bytes | None:
        with self._lock:
            return self.latest_jpeg

    def snapshot(self) -> dict[str, Any]:
        now_ns = time.monotonic_ns()

        def _age_ms(key: str) -> float | None:
            ts = self.update_times_ns.get(key, 0)
            if ts <= 0:
                return None
            return (now_ns - ts) / 1_000_000.0

        with self._lock:
            return {
                "running": self.running,
                "latest_camera": deepcopy(self.latest_camera),
                "latest_raw_microbits": deepcopy(self.latest_raw_microbits),
                "latest_filtered_microbits": deepcopy(self.latest_filtered_microbits),
                "latest_outbound": deepcopy(self.latest_outbound),
                "outbound_tail": list(deepcopy(self.outbound_tail)),
                "tcp_status": deepcopy(self.tcp_status),
                "counters": dict(self.counters),
                "ages_ms": {
                    "camera": _age_ms("camera"),
                    "raw_microbit": _age_ms("raw_microbit"),
                    "filtered_microbit": _age_ms("filtered_microbit"),
                    "outbound": _age_ms("outbound"),
                    "jpeg": _age_ms("jpeg"),
                },
            }


class PreviewServer:
    def __init__(self, *, host: str, port: int, state: PreviewState) -> None:
        self._host = host
        self._port = port
        self._state = state
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._server = ThreadingHTTPServer((self._host, self._port), self._make_handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="fusion-preview-http",
        )
        self._thread.start()
        logger.info("Fusion preview listening on http://%s:%d/", self._host, self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        state = self._state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                logger.debug(fmt, *args)

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path in {"/", "/index.html"}:
                    body = HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if path == "/state":
                    body = json.dumps(
                        state.snapshot(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if path == "/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    last_frame = None
                    while True:
                        jpeg = state.latest_jpeg_snapshot()
                        if jpeg is None or jpeg is last_frame:
                            time.sleep(0.05)
                            continue
                        last_frame = jpeg
                        try:
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                            self.wfile.write(jpeg)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            break
                    return

                self.send_error(404)

        return Handler

