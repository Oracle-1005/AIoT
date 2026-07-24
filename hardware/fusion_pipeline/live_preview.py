#!/usr/bin/env python3
"""Browser preview for camera + micro:bit fusion data before TCP send.

This tool runs the same Pi-side adapters used by main.py, but it does not
connect to the PC backend.  It exposes a local HTTP page that shows:

  - latest camera frame metadata and MediaPipe hand data
  - latest raw decoded micro:bit sensor samples before filtering
  - latest filtered micro:bit samples entering the fusion buffer
  - latest fused_frame/control_event messages that would be sent to the PC
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import threading
import time
from collections import deque
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_HARDWARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARDWARE))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "esp32_ble_gateway_to_Pi"))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "microbit_to_Pi"))

from microbit_receiver.protocol import Hand

from fusion_pipeline.camera_adapter import CameraAdapter
from fusion_pipeline.fusion_engine import FusionEngine
from fusion_pipeline.gateway_adapter import GatewayAdapter, MicrobitSample
from fusion_pipeline.main import load_config

logger = logging.getLogger("fusion_preview")


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIoT Fusion Live Preview</title>
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
      --blue: #235fc8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 18px; font-weight: 700; }
    .status { display: flex; gap: 12px; align-items: center; color: var(--muted); font-size: 13px; }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 5px 9px; background: #fbfcfe; }
    main { padding: 16px; display: grid; gap: 16px; grid-template-columns: 1fr 1fr; }
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
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
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
    .good { color: var(--good); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; padding: 12px; }
      .wide { grid-column: auto; }
      .split { grid-template-columns: 1fr; }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      header { height: auto; min-height: 58px; align-items: flex-start; flex-direction: column; padding: 10px 12px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>AIoT 融合链路实时预览</h1>
    <div class="status">
      <span id="running" class="pill">starting</span>
      <span id="gateway" class="pill">gateway --</span>
      <span id="camera" class="pill">camera --</span>
      <span id="fusion" class="pill">fused --</span>
    </div>
  </header>

  <main>
    <section>
      <div class="section-head">
        <h2>摄像头最新采集与 MediaPipe 输出</h2>
        <span id="camera-age" class="pill">--</span>
      </div>
      <div class="grid">
        <div class="metric"><span class="label">frame</span><span id="frame-id" class="value">--</span></div>
        <div class="metric"><span class="label">hands</span><span id="hands" class="value">--</span></div>
        <div class="metric"><span class="label">clock</span><span id="clock" class="value">--</span></div>
        <div class="metric"><span class="label">latency</span><span id="latency" class="value">--</span></div>
      </div>
      <pre id="camera-json"></pre>
    </section>

    <section>
      <div class="section-head">
        <h2>micro:bit 刚解码原始样本</h2>
        <span id="raw-age" class="pill">--</span>
      </div>
      <div class="split">
        <pre id="raw-left" class="small"></pre>
        <pre id="raw-right" class="small"></pre>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>micro:bit 过滤后进入融合缓冲的样本</h2>
        <span id="filtered-age" class="pill">--</span>
      </div>
      <div class="split">
        <pre id="filtered-left" class="small"></pre>
        <pre id="filtered-right" class="small"></pre>
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>整理后即将发送给 PC 的完整消息</h2>
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
        $("running").textContent = data.running ? "preview running" : "preview stopped";
        $("running").className = "pill " + (data.running ? "good" : "bad");
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
        self.latest_raw_microbits: dict[str, dict[str, Any]] = {}
        self.latest_filtered_microbits: dict[str, dict[str, Any]] = {}
        self.latest_outbound: dict[str, Any] | None = None
        self.latest_status: dict[str, Any] | None = None
        self.outbound_tail: deque[dict[str, Any]] = deque(maxlen=20)
        self.update_times_ns = {
            "camera": 0,
            "raw_microbit": 0,
            "filtered_microbit": 0,
            "outbound": 0,
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

    def set_camera(self, frame: dict[str, Any]) -> None:
        with self._lock:
            self.latest_camera = deepcopy(frame)
            self.update_times_ns["camera"] = time.monotonic_ns()
            self.counters["camera_frames"] += 1

    def set_raw_microbit(self, item: dict[str, Any]) -> None:
        source = str(item.get("source", ""))
        with self._lock:
            if source in {"left", "right"}:
                self.latest_raw_microbits[source] = deepcopy(item)
            self.update_times_ns["raw_microbit"] = time.monotonic_ns()
            self.counters["raw_microbit"] += 1

    def set_filtered_microbit(self, sample: MicrobitSample) -> None:
        item = sample.to_dict()
        source = str(item.get("source", ""))
        with self._lock:
            if source in {"left", "right"}:
                self.latest_filtered_microbits[source] = item
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
                self.latest_status = item

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
                "latest_status": deepcopy(self.latest_status),
                "outbound_tail": list(deepcopy(self.outbound_tail)),
                "counters": dict(self.counters),
                "ages_ms": {
                    "camera": _age_ms("camera"),
                    "raw_microbit": _age_ms("raw_microbit"),
                    "filtered_microbit": _age_ms("filtered_microbit"),
                    "outbound": _age_ms("outbound"),
                },
            }


class PreviewApp:
    def __init__(self, config: dict[str, Any], state: PreviewState) -> None:
        self._cfg = config
        self._state = state
        self._gateway: GatewayAdapter | None = None
        self._camera: CameraAdapter | None = None
        self._fusion: FusionEngine | None = None
        self._running = False

    async def start(self) -> None:
        fusion_cfg = self._cfg["fusion"]
        self._fusion = FusionEngine(
            max_age_ms=fusion_cfg["max_age_ms"],
            buffer_max_age_s=fusion_cfg["buffer_max_age_s"],
            jitter_buffer_ms=fusion_cfg["jitter_buffer_ms"],
        )

        gw_cfg = self._cfg["gateway"]
        allowed = {Hand.from_label(h) for h in gw_cfg["allowed_hands"]}
        self._gateway = GatewayAdapter(
            listen_host=gw_cfg["listen_host"],
            listen_port=gw_cfg["listen_port"],
            allowed_hands=allowed,
            event_dedup_ttl_s=gw_cfg["event_dedup_ttl_s"],
            noise_filter_config=gw_cfg.get("noise_filter", {}),
            on_raw_sensor_state=self._on_raw_microbit_sample,
            on_sensor_state=self._on_microbit_sample,
            on_control_event=self._on_control_event,
        )
        await self._gateway.start()

        cam_cfg = self._cfg["camera"]
        self._camera = CameraAdapter(
            width=cam_cfg["width"],
            height=cam_cfg["height"],
            fps=cam_cfg["fps"],
            max_hands=cam_cfg["max_hands"],
            frame_queue_size=cam_cfg["frame_queue_size"],
            buffer_max_age_s=cam_cfg["buffer_max_age_s"],
            clock_min_points=cam_cfg["clock_min_points"],
            clock_max_points=cam_cfg["clock_max_points"],
        )
        if not self._camera.start():
            logger.warning("Camera failed to start; preview will show micro:bit data only.")

        self._running = True
        self._state.set_running(True)
        logger.info("Fusion preview started.")

    async def stop(self) -> None:
        self._running = False
        self._state.set_running(False)
        if self._camera:
            self._camera.stop()
        if self._gateway:
            await self._gateway.stop()
        logger.info("Fusion preview stopped.")

    async def run(self) -> None:
        poll_s = self._cfg["general"]["fusion_poll_interval_s"]
        status_s = self._cfg["general"]["status_interval_s"]
        last_status = time.monotonic()

        while self._running:
            if self._camera and self._camera.is_running() and self._fusion:
                camera_frame = self._camera.poll_frame()
                if camera_frame is not None:
                    self._state.set_camera(camera_frame)
                    self._fusion.enqueue_camera_frame(camera_frame)

            if self._fusion:
                for fused in self._fusion.drain_ready_frames():
                    self._state.add_outbound(fused)

            now = time.monotonic()
            if now - last_status >= status_s and self._fusion:
                gw_status = self._gateway.get_status() if self._gateway else {}
                cam_status = self._camera.get_status() if self._camera else {}
                self._state.add_outbound(self._fusion.build_status(gw_status, cam_status))
                last_status = now

            await asyncio.sleep(poll_s)

    def _on_raw_microbit_sample(self, item: dict[str, Any]) -> None:
        self._state.set_raw_microbit(item)

    def _on_microbit_sample(self, sample: MicrobitSample) -> None:
        self._state.set_filtered_microbit(sample)
        if self._fusion:
            self._fusion.push_microbit_sample(sample)

    def _on_control_event(self, event: dict[str, Any]) -> None:
        self._state.add_outbound(event)


def make_handler(state: PreviewState) -> type[BaseHTTPRequestHandler]:
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

            self.send_error(404)

    return Handler


def start_http_server(host: str, port: int, state: PreviewState) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="preview-http")
    thread.start()
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview camera, micro:bit, and fused outbound data.")
    parser.add_argument("--config", default="config.yaml", help="Fusion config YAML path.")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8790, help="HTTP preview port.")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser.parse_args()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def async_main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parent / config_path
    cfg = load_config(str(config_path))

    state = PreviewState()
    server = start_http_server(args.host, args.port, state)
    logger.info("Preview page: http://%s:%d/", args.host, args.port)

    app = PreviewApp(cfg, state)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    try:
        await app.start()
        runner = asyncio.create_task(app.run())
        stopper = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            [runner, stopper],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        await app.stop()
        server.shutdown()
        server.server_close()


def main() -> int:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
