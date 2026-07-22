#!/usr/bin/env python3
"""
Pi 5 Flask Application — Dashboard + API + SQLite
===================================================
Lightweight Flask backend running on the Raspberry Pi 5, providing:
  - REST API for system status, sensor data, gesture history
  - WebSocket bridge for real-time MQTT → browser dashboard
  - SQLite database for session recording and playback
  - Dashboard HTML page with live sensor/graph views

Architecture:
  Pi 5 runs:
    ┌──────────────────────────────────────┐
    │  Mosquitto MQTT Broker                │
    │  ├─ microbit/accel/A, B               │
    │  ├─ camera/landmarks                  │
    │  ├─ model/gesture                     │
    │  └─ led/status                        │
    │                                       │
    │  pi_flask_app.py (this file)          │
    │  ├─ Flask REST API (:5000)            │
    │  ├─ Flask-SocketIO WebSocket          │
    │  ├─ SQLite session database           │
    │  └─ MQTT subscriber (internal)        │
    └──────────────────────────────────────┘

Usage:
  python pi_flask_app.py
  python pi_flask_app.py --port 5000 --no-mqtt

Dashboard: http://<pi-ip>:5000/
API Docs:  http://<pi-ip>:5000/api/status
"""

import atexit
import json
import os
import sqlite3
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Server
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")

# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "1").lower() in ("1", "true", "yes")

# SQLite
DB_PATH = os.getenv("AIOT_DB_PATH", str(Path(__file__).resolve().parent / "pi_dashboard.db"))

# Data retention
MAX_ACCEL_BUFFER = int(os.getenv("MAX_ACCEL_BUFFER", "1000"))
MAX_LANDMARKS_BUFFER = int(os.getenv("MAX_LANDMARKS_BUFFER", "200"))
MAX_GESTURE_HISTORY = int(os.getenv("MAX_GESTURE_HISTORY", "100"))


# ---------------------------------------------------------------------------
# SQLite Database
# ---------------------------------------------------------------------------

def init_database():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gesture_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            gesture TEXT NOT NULL,
            confidence REAL NOT NULL,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS sensor_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            sensor_type TEXT NOT NULL,   -- 'accel', 'landmarks', 'system'
            device_id TEXT,              -- 'A', 'B', or NULL
            data_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS session_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_start REAL NOT NULL,
            session_end REAL,
            total_gestures INTEGER DEFAULT 0,
            notes TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_gesture_ts ON gesture_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_sensor_ts ON sensor_log(timestamp);
    """)
    conn.commit()
    conn.close()


def log_gesture_to_db(gesture: str, confidence: float, raw_json: str = None):
    """Write a gesture prediction to the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO gesture_log (timestamp, gesture, confidence, raw_json) VALUES (?, ?, ?, ?)",
            (time.time(), gesture, confidence, raw_json),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Error logging gesture: {e}")


def log_sensor_to_db(sensor_type: str, data_json: str, device_id: str = None):
    """Write sensor data to the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO sensor_log (timestamp, sensor_type, device_id, data_json) VALUES (?, ?, ?, ?)",
            (time.time(), sensor_type, device_id, data_json),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Error logging sensor: {e}")


def get_gesture_history(limit: int = 50, since: float = None) -> list[dict]:
    """Retrieve recent gesture predictions."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if since:
        rows = conn.execute(
            "SELECT * FROM gesture_log WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM gesture_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# In-Memory State
# ---------------------------------------------------------------------------

class SystemState:
    """Thread-safe in-memory state for the dashboard."""

    def __init__(self):
        self._lock = threading.RLock()

        # Latest data
        self.latest_accel_a: Optional[dict] = None
        self.latest_accel_b: Optional[dict] = None
        self.latest_landmarks: Optional[dict] = None
        self.latest_gesture: Optional[dict] = None

        # Buffers for chart data
        self.accel_buffer_a: deque = deque(maxlen=MAX_ACCEL_BUFFER)
        self.accel_buffer_b: deque = deque(maxlen=MAX_ACCEL_BUFFER)
        self.landmarks_buffer: deque = deque(maxlen=MAX_LANDMARKS_BUFFER)
        self.gesture_history: deque = deque(maxlen=MAX_GESTURE_HISTORY)

        # System status
        self.ble_status: dict = {}
        self.camera_status: dict = {}
        self.led_status: dict = {}
        self.start_time = time.time()

        # Performance
        self.total_accel_samples = 0
        self.total_camera_frames = 0
        self.total_gestures = 0

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    # ---- Update methods (called from MQTT) ----

    def update_accel(self, device_id: str, data: dict):
        with self._lock:
            self.total_accel_samples += 1
            entry = {**data, "received_at": time.time()}
            if device_id == "A":
                self.latest_accel_a = entry
                self.accel_buffer_a.append(entry)
            elif device_id == "B":
                self.latest_accel_b = entry
                self.accel_buffer_b.append(entry)

    def update_landmarks(self, data: dict):
        with self._lock:
            self.total_camera_frames += 1
            self.latest_landmarks = {**data, "received_at": time.time()}
            self.landmarks_buffer.append(self.latest_landmarks)

    def update_gesture(self, data: dict):
        with self._lock:
            self.total_gestures += 1
            self.latest_gesture = {**data, "received_at": time.time()}
            self.gesture_history.append(self.latest_gesture)

            # Log to database
            gesture_name = data.get("gesture", "unknown")
            confidence = data.get("confidence", 0.0)
            log_gesture_to_db(gesture_name, confidence, json.dumps(data))

    def update_status(self, component: str, data: dict):
        with self._lock:
            if component == "ble":
                self.ble_status = data
            elif component == "camera":
                self.camera_status = data
            elif component == "led":
                self.led_status = data

    # ---- Query methods ----

    def get_full_state(self) -> dict:
        with self._lock:
            return {
                "uptime_seconds": round(self.uptime_seconds, 1),
                "latest": {
                    "accel_a": self.latest_accel_a,
                    "accel_b": self.latest_accel_b,
                    "landmarks": self.latest_landmarks,
                    "gesture": self.latest_gesture,
                },
                "stats": {
                    "total_accel_samples": self.total_accel_samples,
                    "total_camera_frames": self.total_camera_frames,
                    "total_gestures": self.total_gestures,
                    "buffer_sizes": {
                        "accel_a": len(self.accel_buffer_a),
                        "accel_b": len(self.accel_buffer_b),
                        "landmarks": len(self.landmarks_buffer),
                        "gestures": len(self.gesture_history),
                    },
                },
                "status": {
                    "ble": self.ble_status,
                    "camera": self.camera_status,
                    "led": self.led_status,
                },
            }

    def get_accel_data(self, device_id: str = "A", limit: int = 100) -> list[dict]:
        with self._lock:
            buf = self.accel_buffer_a if device_id == "A" else self.accel_buffer_b
            return list(buf)[-limit:]

    def get_recent_gestures(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return list(self.gesture_history)[-limit:]


# Global state instance
state = SystemState()


# ---------------------------------------------------------------------------
# MQTT Subscriber (internal to Flask app)
# ---------------------------------------------------------------------------

class InternalMQTTSubscriber:
    """Subscribes to all relevant MQTT topics and updates SystemState."""

    def __init__(self, state: SystemState):
        self.state = state
        self._client = None
        self._running = False
        self._socketio = None  # Set by Flask app for WebSocket push

    def set_socketio(self, sio):
        self._socketio = sio

    def start(self):
        if not MQTT_ENABLED:
            print("[MQTT] Disabled. Running without MQTT integration.")
            return

        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(client_id=f"pi_flask_{os.getpid()}")

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print(f"[MQTT] Connected to {MQTT_BROKER}:{MQTT_PORT}")
                # Subscribe to all data topics
                client.subscribe("microbit/accel/A", qos=0)
                client.subscribe("microbit/accel/B", qos=0)
                client.subscribe("camera/landmarks", qos=0)
                client.subscribe("model/gesture", qos=0)
                client.subscribe("microbit/status/#", qos=0)
                client.subscribe("camera/status", qos=0)
                client.subscribe("led/status", qos=0)
                print("[MQTT] Subscribed to all data topics")
            else:
                print(f"[MQTT] Connection failed: rc={rc}")

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except Exception:
                return

            topic = msg.topic

            if topic == "microbit/accel/A":
                self.state.update_accel("A", payload)
                self._emit_socket("accel_update", {"device_id": "A", "data": payload})
            elif topic == "microbit/accel/B":
                self.state.update_accel("B", payload)
                self._emit_socket("accel_update", {"device_id": "B", "data": payload})
            elif topic == "camera/landmarks":
                self.state.update_landmarks(payload)
                # Don't push full landmarks via WebSocket (too large); push summary
                self._emit_socket("landmarks_update", {
                    "num_hands": payload.get("num_hands", 0),
                    "fps": payload.get("fps", 0),
                    "timestamp": payload.get("timestamp"),
                })
            elif topic == "model/gesture":
                self.state.update_gesture(payload)
                self._emit_socket("gesture_update", payload)
            elif topic.startswith("microbit/status/"):
                self.state.update_status("ble", payload)
                self._emit_socket("status_update", {"component": "ble", "data": payload})
            elif topic == "camera/status":
                self.state.update_status("camera", payload)
                self._emit_socket("status_update", {"component": "camera", "data": payload})
            elif topic == "led/status":
                self.state.update_status("led", payload)
                self._emit_socket("status_update", {"component": "led", "data": payload})

        self._client.on_connect = on_connect
        self._client.on_message = on_message
        self._client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self._client.loop_start()
        self._running = True

    def _emit_socket(self, event: str, data: dict):
        """Push real-time update to WebSocket clients."""
        if self._socketio:
            try:
                self._socketio.emit(event, data, namespace="/dashboard")
            except Exception:
                pass

    def stop(self):
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    def publish(self, topic: str, payload: dict):
        """Publish a message to MQTT (e.g. for LED commands)."""
        if self._client and self._running:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self._client.publish(topic, data, qos=0)


# Global MQTT subscriber
mqtt_subscriber = InternalMQTTSubscriber(state)


# ---------------------------------------------------------------------------
# Flask Application
# ---------------------------------------------------------------------------

from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# SocketIO (optional — gracefully degrade if not installed)
try:
    from flask_socketio import SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
    mqtt_subscriber.set_socketio(socketio)
    HAS_SOCKETIO = True
except ImportError:
    print("[Flask] flask-socketio not installed — WebSocket disabled")
    socketio = None
    HAS_SOCKETIO = False


# ---- Dashboard HTML (inline) -------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AIoT Smart Conducting — Dashboard</title>
<style>
  :root {
    --bg: #0a0a0f;
    --card-bg: #141420;
    --text: #e0e0e0;
    --accent: #4fc3f7;
    --green: #66bb6a;
    --red: #ef5350;
    --yellow: #ffa726;
    --border: #2a2a3a;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  header {
    background: var(--card-bg);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  header h1 { font-size: 1.3rem; font-weight: 600; }
  header .status-dot {
    width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 6px;
  }
  header .status-dot.online { background: var(--green); }
  header .status-dot.offline { background: var(--red); }
  main {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px;
    padding: 20px;
    max-width: 1400px;
    margin: 0 auto;
  }
  .card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }
  .card.full-width { grid-column: 1 / -1; }
  .card h2 {
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #888;
    margin-bottom: 12px;
  }
  .gesture-display {
    font-size: 2.5rem;
    font-weight: 700;
    text-align: center;
    padding: 24px 0;
    color: var(--accent);
    transition: all 0.3s ease;
  }
  .gesture-display.conf-high { color: var(--green); }
  .gesture-display.conf-medium { color: var(--yellow); }
  .gesture-display.conf-low { color: var(--red); }
  .confidence-bar {
    height: 6px; background: #222; border-radius: 3px; overflow: hidden; margin-top: 8px;
  }
  .confidence-bar-fill {
    height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s ease;
  }
  .stat-row {
    display: flex; justify-content: space-between; padding: 6px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }
  .stat-label { color: #888; font-size: 0.85rem; }
  .stat-value { font-weight: 600; font-variant-numeric: tabular-nums; }
  .accel-chart { display: flex; gap: 4px; align-items: flex-end; height: 80px; padding: 4px 0; }
  .accel-chart .bar {
    flex: 1; min-width: 2px; background: var(--accent); border-radius: 2px 2px 0 0;
    opacity: 0.7; transition: height 0.1s ease;
  }
  .gesture-history { max-height: 200px; overflow-y: auto; }
  .gesture-history-item {
    display: flex; justify-content: space-between; padding: 4px 8px;
    font-size: 0.85rem; border-radius: 4px;
  }
  .gesture-history-item:nth-child(odd) { background: rgba(255,255,255,0.03); }
  .gesture-tag {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600;
  }
  .gesture-tag.start { background: rgba(102,187,106,0.2); color: var(--green); }
  .gesture-tag.stop { background: rgba(239,83,80,0.2); color: var(--red); }
  .gesture-tag.downbeat { background: rgba(255,255,255,0.15); color: #fff; }
  .gesture-tag.upbeat { background: rgba(255,167,38,0.2); color: var(--yellow); }
  .gesture-tag.idle { background: rgba(79,195,247,0.15); color: var(--accent); }
  .gesture-tag.default { background: rgba(255,255,255,0.08); color: #aaa; }
  .connection-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .connection-item { text-align: center; padding: 12px; border-radius: 8px; background: rgba(255,255,255,0.03); }
  .connection-dot { width: 12px; height: 12px; border-radius: 50%; margin: 0 auto 6px; }
  .connection-dot.connected { background: var(--green); box-shadow: 0 0 8px rgba(102,187,106,0.5); }
  .connection-dot.disconnected { background: #555; }
  @media (max-width: 700px) {
    main { grid-template-columns: 1fr; padding: 10px; }
    .gesture-display { font-size: 1.8rem; }
  }
</style>
</head>
<body>
<header>
  <h1>🎵 AIoT Smart Conducting System</h1>
  <div>
    <span class="status-dot online" id="sys-dot"></span>
    <span style="font-size:0.85rem;color:#888;" id="sys-uptime">--</span>
  </div>
</header>

<main>
  <!-- Gesture Display -->
  <div class="card full-width" style="text-align:center;">
    <h2>Current Gesture</h2>
    <div class="gesture-display" id="gesture-name">--</div>
    <div class="confidence-bar">
      <div class="confidence-bar-fill" id="confidence-fill" style="width:0%;"></div>
    </div>
    <div style="margin-top:4px;font-size:0.8rem;color:#888;">
      Confidence: <span id="confidence-value">0.00</span>
    </div>
  </div>

  <!-- Connection Status -->
  <div class="card">
    <h2>Connections</h2>
    <div class="connection-grid">
      <div class="connection-item">
        <div class="connection-dot disconnected" id="dot-ble-a"></div>
        <div style="font-size:0.8rem;">Micro:bit A</div>
        <div style="font-size:0.7rem;color:#888;" id="rate-ble-a">--</div>
      </div>
      <div class="connection-item">
        <div class="connection-dot disconnected" id="dot-ble-b"></div>
        <div style="font-size:0.8rem;">Micro:bit B</div>
        <div style="font-size:0.7rem;color:#888;" id="rate-ble-b">--</div>
      </div>
      <div class="connection-item">
        <div class="connection-dot disconnected" id="dot-camera"></div>
        <div style="font-size:0.8rem;">Camera</div>
        <div style="font-size:0.7rem;color:#888;" id="rate-camera">--</div>
      </div>
      <div class="connection-item">
        <div class="connection-dot disconnected" id="dot-led"></div>
        <div style="font-size:0.8rem;">LED Matrix</div>
        <div style="font-size:0.7rem;color:#888;" id="rate-led">--</div>
      </div>
    </div>
  </div>

  <!-- Statistics -->
  <div class="card">
    <h2>Statistics</h2>
    <div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value" id="stat-uptime">--</span></div>
    <div class="stat-row"><span class="stat-label">Accel Samples</span><span class="stat-value" id="stat-accel">0</span></div>
    <div class="stat-row"><span class="stat-label">Camera Frames</span><span class="stat-value" id="stat-frames">0</span></div>
    <div class="stat-row"><span class="stat-label">Total Gestures</span><span class="stat-value" id="stat-gestures">0</span></div>
    <div class="stat-row"><span class="stat-label">MQTT Connected</span><span class="stat-value" id="stat-mqtt">--</span></div>
  </div>

  <!-- Accel Live Chart -->
  <div class="card">
    <h2>Accel A (Left Wrist)</h2>
    <div class="accel-chart" id="accel-a-chart"></div>
    <div style="font-size:0.7rem;color:#888;text-align:center;">Acceleration Norm (mg)</div>
  </div>

  <div class="card">
    <h2>Accel B (Right Wrist)</h2>
    <div class="accel-chart" id="accel-b-chart"></div>
    <div style="font-size:0.7rem;color:#888;text-align:center;">Acceleration Norm (mg)</div>
  </div>

  <!-- Gesture History -->
  <div class="card" style="grid-column: span 2;">
    <h2>Recent Gestures</h2>
    <div class="gesture-history" id="gesture-history">
      <div style="text-align:center;color:#555;padding:20px;">Waiting for data...</div>
    </div>
  </div>
</main>

<script>
  // Connect WebSocket
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = io ? io() : null;

  function updateAccelChart(containerId, normValues) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const maxNorm = 1500; // 1.5g max display
    container.innerHTML = '';
    for (const norm of normValues.slice(-40)) {
      const bar = document.createElement('div');
      bar.className = 'bar';
      const h = Math.max(2, (norm / maxNorm) * 100);
      bar.style.height = h + '%';
      container.appendChild(bar);
    }
  }

  function getGestureClass(gesture) {
    const map = {
      'start': 'start', '开始': 'start',
      'stop': 'stop', '停止': 'stop',
      'downbeat': 'downbeat', '强拍': 'downbeat',
      'upbeat': 'upbeat', '弱拍': 'upbeat',
      'idle': 'idle', '静止': 'idle',
    };
    return map[gesture] || 'default';
  }

  function updateDashboard(state) {
    if (!state) return;

    // Gesture
    const gesture = state.latest?.gesture;
    if (gesture) {
      const el = document.getElementById('gesture-name');
      el.textContent = gesture.gesture || '--';
      const conf = gesture.confidence || 0;
      document.getElementById('confidence-value').textContent = conf.toFixed(3);
      document.getElementById('confidence-fill').style.width = (conf * 100) + '%';

      el.className = 'gesture-display';
      if (conf >= 0.8) el.classList.add('conf-high');
      else if (conf >= 0.5) el.classList.add('conf-medium');
      else el.classList.add('conf-low');
    }

    // Stats
    const stats = state.stats || {};
    document.getElementById('stat-uptime').textContent = formatUptime(state.uptime_seconds || 0);
    document.getElementById('stat-accel').textContent = (stats.total_accel_samples || 0).toLocaleString();
    document.getElementById('stat-frames').textContent = (stats.total_camera_frames || 0).toLocaleString();
    document.getElementById('stat-gestures').textContent = (stats.total_gestures || 0).toLocaleString();

    // Accel charts from latest data
    if (state.latest?.accel_a?.acc_norm != null) {
      const chart = document.getElementById('accel-a-chart');
      // Append bar
    }
  }

  function formatUptime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`;
  }

  // Poll /api/status every second for data
  async function pollStatus() {
    try {
      const resp = await fetch('/api/status');
      const data = await resp.json();
      updateDashboard(data);

      // Connection dots
      if (data.status?.ble) {
        const ble = data.status.ble;
        for (const key of ['A', 'B']) {
          const dot = document.getElementById('dot-ble-' + key.toLowerCase());
          const rate = document.getElementById('rate-ble-' + key.toLowerCase());
          const info = ble[key] || ble;
          if (dot) dot.className = 'connection-dot ' + (info?.connected ? 'connected' : 'disconnected');
          if (rate) rate.textContent = info?.sample_rate ? `${info.sample_rate} Hz` : '--';
        }
      }
      if (data.status?.camera) {
        const dot = document.getElementById('dot-camera');
        const rate = document.getElementById('rate-camera');
        if (dot) dot.className = 'connection-dot ' + (data.status.camera.fps > 0 ? 'connected' : 'disconnected');
        if (rate) rate.textContent = data.status.camera.fps ? `${data.status.camera.fps} fps` : '--';
      }
      if (data.status?.led) {
        const dot = document.getElementById('dot-led');
        if (dot) dot.className = 'connection-dot connected';
      }
    } catch (e) {
      console.error('Status poll error:', e);
    }
  }

  setInterval(pollStatus, 1000);
  pollStatus();

  // WebSocket event handlers
  if (socket) {
    socket.on('gesture_update', function(data) {
      const el = document.getElementById('gesture-name');
      el.textContent = data.gesture || '--';
      document.getElementById('confidence-value').textContent = (data.confidence || 0).toFixed(3);
      document.getElementById('confidence-fill').style.width = ((data.confidence || 0) * 100) + '%';

      // Add to history
      const hist = document.getElementById('gesture-history');
      const cls = getGestureClass(data.gesture);
      hist.innerHTML = `<div class="gesture-history-item">
        <span class="gesture-tag ${cls}">${data.gesture}</span>
        <span>${(data.confidence || 0).toFixed(2)}</span>
      </div>` + hist.innerHTML;
      // Keep only 20 items
      while (hist.children.length > 20) hist.removeChild(hist.lastChild);
    });

    socket.on('accel_update', function(msg) {
      // Update chart bars
      const chartId = 'accel-' + msg.device_id.toLowerCase() + '-chart';
      if (msg.data?.acc_norm != null) {
        const chart = document.getElementById(chartId);
        if (chart) {
          const bar = document.createElement('div');
          bar.className = 'bar';
          bar.style.height = Math.max(2, (msg.data.acc_norm / 1500) * 100) + '%';
          chart.appendChild(bar);
          while (chart.children.length > 40) chart.removeChild(chart.firstChild);
        }
      }
    });
  }
</script>
</body>
</html>"""


# ---- API Routes ---------------------------------------------------------

@app.route("/")
def index():
    """Dashboard HTML page."""
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/status")
def api_status():
    """Full system status."""
    return jsonify(state.get_full_state())


@app.route("/api/gesture/current")
def api_gesture_current():
    """Latest gesture prediction."""
    with state._lock:
        gesture = state.latest_gesture
    return jsonify(gesture or {"gesture": None, "confidence": 0})


@app.route("/api/gesture/history")
def api_gesture_history():
    """Recent gesture history."""
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    # Try in-memory first, fall back to DB
    recent = state.get_recent_gestures(limit)
    if len(recent) < limit:
        db_records = get_gesture_history(limit)
        # Merge (deduplicated by timestamp)
        seen_ts = {r.get("timestamp") for r in recent}
        for r in db_records:
            if r.get("timestamp") not in seen_ts:
                recent.append(r)
        recent.sort(key=lambda r: r.get("timestamp", 0))
        recent = recent[-limit:]

    return jsonify({"count": len(recent), "records": recent})


@app.route("/api/sensors/live")
def api_sensors_live():
    """Latest sensor data (accel + camera)."""
    return jsonify({
        "accel_a": state.latest_accel_a,
        "accel_b": state.latest_accel_b,
        "landmarks_summary": {
            "num_hands": state.latest_landmarks.get("num_hands") if state.latest_landmarks else 0,
            "fps": state.latest_landmarks.get("fps") if state.latest_landmarks else 0,
        },
    })


@app.route("/api/sensors/accel/<device_id>")
def api_sensors_accel(device_id: str):
    """Recent accelerometer data for a specific device."""
    if device_id.upper() not in ("A", "B"):
        return jsonify({"error": "device_id must be A or B"}), 400
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400

    data = state.get_accel_data(device_id.upper(), limit)
    return jsonify({"device_id": device_id.upper(), "count": len(data), "records": data})


@app.route("/api/led/send", methods=["POST"])
def api_led_send():
    """Send a command to the LED driver via MQTT."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400

    command = body.get("command")
    if not command:
        return jsonify({"error": "command field is required"}), 400

    valid_commands = {"set_brightness", "fill", "clear", "test", "gesture_override"}
    if command not in valid_commands:
        return jsonify({"error": f"command must be one of {sorted(valid_commands)}"}), 400

    if MQTT_ENABLED and mqtt_subscriber._running:
        mqtt_subscriber.publish("led/command", body)
        return jsonify({"sent": True, "command": command})
    else:
        return jsonify({"sent": False, "error": "MQTT not available"}), 503


@app.route("/api/system/info")
def api_system_info():
    """System information."""
    import platform
    return jsonify({
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "db_path": DB_PATH,
        "mqtt_broker": f"{MQTT_BROKER}:{MQTT_PORT}",
        "mqtt_enabled": MQTT_ENABLED,
    })


@app.route("/api/health")
def api_health():
    """Simple health check."""
    return jsonify({"status": "ok", "timestamp": time.time()})


# 404 handler
@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Endpoint not found"}), 404


# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Pi 5 Flask Application — Dashboard + API + SQLite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=FLASK_HOST, help=f"Bind address (default: {FLASK_HOST})")
    parser.add_argument("--port", type=int, default=FLASK_PORT, help=f"Port (default: {FLASK_PORT})")
    parser.add_argument("--no-mqtt", action="store_true", help="Disable MQTT subscriber")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    global MQTT_ENABLED
    MQTT_ENABLED = not args.no_mqtt

    print("=" * 60)
    print("[Flask] Pi 5 Dashboard Server")
    print(f"[Flask] Listening: {args.host}:{args.port}")
    print(f"[Flask] MQTT: {'enabled' if MQTT_ENABLED else 'disabled'} @ {MQTT_BROKER}:{MQTT_PORT}")
    print(f"[Flask] Database: {DB_PATH}")
    print(f"[Flask] Dashboard: http://<pi-ip>:{args.port}/")
    print("=" * 60)

    # Initialize database
    init_database()

    # Start MQTT subscriber
    mqtt_subscriber.start()
    atexit.register(mqtt_subscriber.stop)

    # Start Flask
    if HAS_SOCKETIO:
        socketio.run(app, host=args.host, port=args.port, debug=args.debug, allow_unsafe_werkzeug=True)
    else:
        app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
