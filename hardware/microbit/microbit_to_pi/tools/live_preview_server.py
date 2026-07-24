"""Browser preview for micro:bit -> Raspberry Pi JSON Lines output.

Run this on the Raspberry Pi. It starts the receiver command, reads its stdout,
and serves a small web dashboard over HTTP using only the Python standard
library.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>micro:bit Dual Preview</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #647087;
      --line: #d9e0ec;
      --blue: #2364d2;
      --green: #138a53;
      --red: #bd2f3a;
      --amber: #b46a00;
      --violet: #6b4fd8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 18px; font-weight: 650; }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      color: var(--muted);
    }
    .status-group {
      display: inline-flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--amber);
    }
    .dot.live { background: var(--green); }
    .dot.stale { background: var(--red); }
    main {
      max-width: 1180px;
      margin: 0 auto;
      padding: 18px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    .device {
      display: grid;
      gap: 14px;
      align-content: start;
    }
    .device-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .title {
      margin: 0;
      font-size: 15px;
      font-weight: 700;
      color: var(--ink);
    }
    .subtle {
      color: var(--muted);
      font-size: 13px;
    }
    .tilt-wrap {
      height: 190px;
      display: grid;
      place-items: center;
      perspective: 700px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #eef3fa;
    }
    .tilt {
      width: 150px;
      height: 96px;
      border-radius: 8px;
      background: linear-gradient(135deg, #2364d2, #138a53);
      box-shadow: 0 14px 34px rgba(23, 32, 51, 0.22);
      transform-style: preserve-3d;
      transition: transform 90ms linear;
      position: relative;
    }
    .tilt.right {
      background: linear-gradient(135deg, #6b4fd8, #bd2f3a);
    }
    .tilt::before {
      content: attr(data-label);
      position: absolute;
      inset: 12px;
      border: 2px solid rgba(255,255,255,0.7);
      border-radius: 6px;
      display: grid;
      place-items: center;
      color: white;
      font-weight: 700;
      font-size: 18px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      min-height: 58px;
    }
    .label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .value {
      font: 650 20px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .bars { display: grid; gap: 12px; }
    .bar-row {
      display: grid;
      grid-template-columns: 34px 1fr 72px;
      align-items: center;
      gap: 10px;
      font: 13px ui-monospace, SFMono-Regular, Consolas, monospace;
    }
    .bar-track {
      height: 16px;
      border-radius: 4px;
      background: #edf1f7;
      border: 1px solid var(--line);
      position: relative;
      overflow: hidden;
    }
    .bar-zero {
      position: absolute;
      left: 50%;
      top: 0;
      bottom: 0;
      width: 1px;
      background: #8793a8;
    }
    .bar {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 50%;
      width: 0;
      background: var(--blue);
    }
    canvas {
      width: 100%;
      height: 150px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcff;
    }
    pre {
      height: 168px;
      overflow: auto;
      padding: 10px;
      margin: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #111827;
      color: #d6e1ff;
      font-size: 12px;
      white-space: pre-wrap;
    }
    .wide {
      grid-column: 1 / -1;
    }
    .logs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; padding: 12px; }
      header { padding: 0 12px; }
      .logs { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>micro:bit 双路预览</h1>
    <div class="status-group">
      <div class="status"><span id="left-dot" class="dot"></span><span id="left-status">left waiting</span></div>
      <div class="status"><span id="right-dot" class="dot"></span><span id="right-status">right waiting</span></div>
    </div>
  </header>
  <main>
    <section class="device" id="left-panel">
      <div class="device-head">
        <p class="title">左手 micro:bit</p>
        <span id="left-link" class="subtle">waiting</span>
      </div>
      <div class="tilt-wrap"><div id="left-tilt" class="tilt" data-label="LEFT"></div></div>
      <div class="metrics">
        <div class="metric"><span class="label">pitch</span><span id="left-pitch" class="value">--</span></div>
        <div class="metric"><span class="label">roll</span><span id="left-roll" class="value">--</span></div>
        <div class="metric"><span class="label">sequence</span><span id="left-seq" class="value">--</span></div>
        <div class="metric"><span class="label">age</span><span id="left-age" class="value">--</span></div>
        <div class="metric"><span class="label">RSSI</span><span id="left-rssi" class="value">--</span></div>
        <div class="metric"><span class="label">gap</span><span id="left-gap" class="value">--</span></div>
      </div>
      <div class="bars">
        <div class="bar-row"><span>ax</span><div class="bar-track"><span class="bar-zero"></span><span id="left-bar-ax" class="bar"></span></div><span id="left-ax">--</span></div>
        <div class="bar-row"><span>ay</span><div class="bar-track"><span class="bar-zero"></span><span id="left-bar-ay" class="bar"></span></div><span id="left-ay">--</span></div>
        <div class="bar-row"><span>az</span><div class="bar-track"><span class="bar-zero"></span><span id="left-bar-az" class="bar"></span></div><span id="left-az">--</span></div>
      </div>
      <canvas id="left-chart" width="560" height="180"></canvas>
      <pre id="left-raw"></pre>
    </section>

    <section class="device" id="right-panel">
      <div class="device-head">
        <p class="title">右手 micro:bit</p>
        <span id="right-link" class="subtle">waiting</span>
      </div>
      <div class="tilt-wrap"><div id="right-tilt" class="tilt right" data-label="RIGHT"></div></div>
      <div class="metrics">
        <div class="metric"><span class="label">pitch</span><span id="right-pitch" class="value">--</span></div>
        <div class="metric"><span class="label">roll</span><span id="right-roll" class="value">--</span></div>
        <div class="metric"><span class="label">sequence</span><span id="right-seq" class="value">--</span></div>
        <div class="metric"><span class="label">age</span><span id="right-age" class="value">--</span></div>
        <div class="metric"><span class="label">RSSI</span><span id="right-rssi" class="value">--</span></div>
        <div class="metric"><span class="label">gap</span><span id="right-gap" class="value">--</span></div>
      </div>
      <div class="bars">
        <div class="bar-row"><span>ax</span><div class="bar-track"><span class="bar-zero"></span><span id="right-bar-ax" class="bar"></span></div><span id="right-ax">--</span></div>
        <div class="bar-row"><span>ay</span><div class="bar-track"><span class="bar-zero"></span><span id="right-bar-ay" class="bar"></span></div><span id="right-ay">--</span></div>
        <div class="bar-row"><span>az</span><div class="bar-track"><span class="bar-zero"></span><span id="right-bar-az" class="bar"></span></div><span id="right-az">--</span></div>
      </div>
      <canvas id="right-chart" width="560" height="180"></canvas>
      <pre id="right-raw"></pre>
    </section>

    <section class="wide logs">
      <div>
        <p class="title">最近控制事件</p>
        <pre id="events"></pre>
      </div>
      <div>
        <p class="title">运行日志</p>
        <pre id="logs"></pre>
      </div>
    </section>
  </main>
  <script>
    const state = {
      devices: {
        left: { lastSampleAt: 0, samples: [], latest: null },
        right: { lastSampleAt: 0, samples: [], latest: null }
      },
      events: [],
      logs: []
    };
    const $ = (id) => document.getElementById(id);
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    function sourceOf(item) {
      if (item.source === "left" || item.source === "right") return item.source;
      if (item.hand === 0) return "left";
      if (item.hand === 1) return "right";
      return null;
    }
    function rawOf(item, key) {
      return item.raw && item.raw[key] !== undefined ? item.raw[key] : item[key];
    }
    function setBar(source, axis, value) {
      const bar = $(`${source}-bar-${axis}`);
      const pct = clamp(value / 4000, -1, 1) * 50;
      if (pct >= 0) {
        bar.style.left = "50%";
        bar.style.width = pct + "%";
      } else {
        bar.style.left = (50 + pct) + "%";
        bar.style.width = (-pct) + "%";
      }
    }
    function drawChart(source) {
      const canvas = $(`${source}-chart`);
      const ctx = canvas.getContext("2d");
      const samples = state.devices[source].samples;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "#d9e0ec";
      ctx.lineWidth = 1;
      for (let i = 1; i < 5; i++) {
        const y = i * canvas.height / 5;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
      }
      const series = [
        ["pitch", "#2364d2", 180],
        ["roll", "#138a53", 180],
        ["az", "#bd2f3a", 4000]
      ];
      for (const [key, color, scale] of series) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        samples.forEach((sample, index) => {
          const value = key === "az" ? rawOf(sample, "az_mg") : rawOf(sample, `${key}_deg`);
          const x = index * canvas.width / Math.max(1, samples.length - 1);
          const y = canvas.height / 2 - clamp(value / scale, -1, 1) * canvas.height * 0.42;
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
      ctx.fillStyle = "#647087";
      ctx.font = "13px ui-monospace, Consolas, monospace";
      ctx.fillText("pitch", 12, 20);
      ctx.fillStyle = "#138a53";
      ctx.fillText("roll", 76, 20);
      ctx.fillStyle = "#bd2f3a";
      ctx.fillText("az", 130, 20);
    }
    function updateSample(item) {
      const source = sourceOf(item);
      if (!source) return;
      const pitch = rawOf(item, "pitch_deg") || 0;
      const roll = rawOf(item, "roll_deg") || 0;
      const ax = rawOf(item, "ax_mg") || 0;
      const ay = rawOf(item, "ay_mg") || 0;
      const az = rawOf(item, "az_mg") || 0;
      const device = state.devices[source];
      $(`${source}-tilt`).style.transform = `rotateX(${-pitch}deg) rotateY(${roll}deg)`;
      $(`${source}-pitch`).textContent = `${pitch}°`;
      $(`${source}-roll`).textContent = `${roll}°`;
      $(`${source}-seq`).textContent = item.sample_sequence ?? item.sequence ?? "--";
      $(`${source}-ax`).textContent = `${ax} mg`;
      $(`${source}-ay`).textContent = `${ay} mg`;
      $(`${source}-az`).textContent = `${az} mg`;
      $(`${source}-rssi`).textContent = item.gateway && item.gateway.ble_rssi !== undefined ? `${item.gateway.ble_rssi} dBm` : "--";
      $(`${source}-gap`).textContent = item.missing_sample_count !== undefined ? `${item.missing_sample_count}` : "--";
      $(`${source}-raw`).textContent = JSON.stringify(item, null, 2);
      setBar(source, "ax", ax);
      setBar(source, "ay", ay);
      setBar(source, "az", az);
      device.lastSampleAt = Date.now();
      device.latest = item;
      device.samples.push(item);
      if (device.samples.length > 120) device.samples.shift();
      drawChart(source);
    }
    function addLine(listName, elementId, line) {
      state[listName].unshift(line);
      state[listName] = state[listName].slice(0, 30);
      $(elementId).textContent = state[listName].join("\n");
    }
    const es = new EventSource("/events");
    es.addEventListener("sample", (event) => updateSample(JSON.parse(event.data)));
    es.addEventListener("control", (event) => addLine("events", "events", JSON.stringify(JSON.parse(event.data))));
    es.addEventListener("log", (event) => addLine("logs", "logs", event.data));
    es.onerror = () => {
      for (const source of ["left", "right"]) {
        $(`${source}-status`).textContent = `${source} stream disconnected`;
        $(`${source}-dot`).className = "dot stale";
      }
    };
    setInterval(() => {
      for (const source of ["left", "right"]) {
        const device = state.devices[source];
        const age = device.lastSampleAt ? Date.now() - device.lastSampleAt : Infinity;
        const live = age < 1200;
        const ageText = Number.isFinite(age) ? `${Math.round(age)} ms` : "--";
        $(`${source}-age`).textContent = ageText;
        $(`${source}-status`).textContent = live ? `${source} live` : `${source} waiting`;
        $(`${source}-link`).textContent = live ? `live, age ${ageText}` : "waiting";
        $(`${source}-dot`).className = live ? "dot live" : "dot stale";
      }
    }, 300);
  </script>
</body>
</html>
"""


class Hub:
    def __init__(self) -> None:
        self.clients: list[queue.Queue[tuple[str, str]]] = []
        self.lock = threading.Lock()
        self.latest: dict[str, Any] | None = None
        self.latest_by_source: dict[str, dict[str, Any]] = {}
        self.logs: list[str] = []

    def subscribe(self) -> queue.Queue[tuple[str, str]]:
        client_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        with self.lock:
            self.clients.append(client_queue)
            for item in self.latest_by_source.values():
                client_queue.put(("sample", json.dumps(item, ensure_ascii=False)))
            for line in self.logs[-8:]:
                client_queue.put(("log", line))
        return client_queue

    def unsubscribe(self, client_queue: queue.Queue[tuple[str, str]]) -> None:
        with self.lock:
            if client_queue in self.clients:
                self.clients.remove(client_queue)

    def publish(self, event_name: str, payload: str) -> None:
        with self.lock:
            if event_name == "sample":
                try:
                    self.latest = json.loads(payload)
                    source = str(self.latest.get("source", ""))
                    if source in {"left", "right"}:
                        self.latest_by_source[source] = self.latest
                except json.JSONDecodeError:
                    pass
            elif event_name == "log":
                print(payload, file=sys.stderr, flush=True)
                self.logs.append(payload)
                self.logs = self.logs[-80:]
            clients = list(self.clients)
        for client_queue in clients:
            client_queue.put((event_name, payload))


def make_handler(hub: Hub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                body = INDEX_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/health":
                body = json.dumps(
                    {"ok": True, "latest": hub.latest, "latest_by_source": hub.latest_by_source},
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/events":
                client_queue = hub.subscribe()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while True:
                        try:
                            event_name, payload = client_queue.get(timeout=15.0)
                            frame = f"event: {event_name}\ndata: {payload}\n\n"
                        except queue.Empty:
                            frame = ": ping\n\n"
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    hub.unsubscribe(client_queue)
                return

            self.send_error(404)

    return Handler


def stream_receiver(process: subprocess.Popen[str], hub: Hub) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            hub.publish("log", line)
            continue
        item_type = item.get("type")
        if item_type == "microbit_control_event":
            hub.publish("control", json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        else:
            hub.publish("sample", json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    hub.publish("log", f"receiver stdout ended with code {process.poll()}")


def stream_stderr(process: subprocess.Popen[str], hub: Hub) -> None:
    assert process.stderr is not None
    for line in process.stderr:
        hub.publish("log", line.strip())


def stream_fusion_state(url: str, hub: Hub, stop_event: threading.Event) -> None:
    """Feed the legacy dual-hand UI from pi-fusion's read-only state API."""
    last_sequence: dict[str, int | None] = {"left": None, "right": None}
    seen_events: set[tuple[str, int]] = set()
    error_logged = False

    while not stop_event.wait(0.05):
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                state = json.load(response)
            error_logged = False
        except (OSError, ValueError, urllib.error.URLError) as exc:
            if not error_logged:
                hub.publish("log", f"fusion state unavailable: {exc}")
                error_logged = True
            stop_event.wait(1.0)
            continue

        samples = state.get("latest_raw_microbits", {})
        for source in ("left", "right"):
            item = samples.get(source)
            if not isinstance(item, dict):
                continue
            sequence = item.get("sample_sequence")
            if sequence == last_sequence[source]:
                continue
            last_sequence[source] = sequence
            hub.publish(
                "sample",
                json.dumps(item, ensure_ascii=False, separators=(",", ":")),
            )

        for item in state.get("outbound_tail", []):
            if not isinstance(item, dict) or item.get("type") != "control_event":
                continue
            key = (str(item.get("source", "")), int(item.get("event_sequence", 0)))
            if key in seen_events:
                continue
            seen_events.add(key)
            hub.publish(
                "control",
                json.dumps(item, ensure_ascii=False, separators=(",", ":")),
            )
        if len(seen_events) > 100:
            seen_events.clear()


def build_receiver_command(args: argparse.Namespace) -> list[str]:
    return [
        str(args.python),
        "-m",
        args.receiver_module,
        "--config",
        str(args.config),
        "--log-level",
        args.log_level,
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a live dual micro:bit preview page.")
    parser.add_argument("--receiver-dir", type=Path, help="Directory containing microbit_receiver.")
    parser.add_argument("--config", type=Path, help="Receiver JSON config path.")
    parser.add_argument(
        "--fusion-state-url",
        help="Read-only pi-fusion state endpoint, for example http://127.0.0.1:8790/state.",
    )
    parser.add_argument("--python", type=Path, default=Path(sys.executable), help="Python executable for receiver.")
    parser.add_argument(
        "--receiver-module",
        default="microbit_receiver.app",
        help="Python module started by the preview server.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--pid-file", type=Path, default=Path("/tmp/microbit_preview.pid"))
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()

    if not args.fusion_state_url and (args.receiver_dir is None or args.config is None):
        parser.error("--receiver-dir and --config are required without --fusion-state-url")

    receiver_dir = (
        args.receiver_dir.expanduser().resolve()
        if args.receiver_dir is not None
        else Path.cwd()
    )
    if args.config is not None:
        config = args.config.expanduser()
        if not config.is_absolute():
            config = receiver_dir / config
        args.config = config
    python_path = args.python.expanduser()
    if not python_path.is_absolute():
        python_path = (Path.cwd() / python_path).resolve()
    args.python = python_path
    pid_file = args.pid_file.expanduser()
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(existing_pid, 0)
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)
        else:
            print(f"preview already running with pid {existing_pid}", file=sys.stderr)
            return 2
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    hub = Hub()
    process: subprocess.Popen[str] | None = None
    fusion_stop = threading.Event()
    if args.fusion_state_url:
        hub.publish("log", "fusion state source: " + args.fusion_state_url)
        threading.Thread(
            target=stream_fusion_state,
            args=(args.fusion_state_url, hub, fusion_stop),
            daemon=True,
        ).start()
    else:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        command = build_receiver_command(args)
        hub.publish("log", "receiver command: " + " ".join(command))

        process = subprocess.Popen(
            command,
            cwd=receiver_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )

        threading.Thread(target=stream_receiver, args=(process, hub), daemon=True).start()
        threading.Thread(target=stream_stderr, args=(process, hub), daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(hub))
    print(f"preview: http://{args.host}:{args.port}/", flush=True)
    print("press Ctrl+C to stop", flush=True)

    def stop(_signum: int, _frame: Any) -> None:
        server.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    finally:
        fusion_stop.set()
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        server.server_close()
        pid_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
