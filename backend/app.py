"""PC backend for the AIoT Smart Conducting System.

Current architecture:
- Flask + SQLite remain available for frontend/history.
- PC acts as TCP server for Pi JSON Lines messages.
- Four Pi uplink types are accepted: fused_frame, window_features,
  control_event and status.
- LED/system downlink uses the same TCP connection; MQTT is not used.
"""

from __future__ import annotations

import atexit
import os
import time

from flask import Flask, jsonify, request
from flask_cors import CORS

from database import DB_PATH, get_pi_message_history, get_prediction_history, init_db
from message_router import UPLINK_MESSAGE_TYPES, route_uplink_message
from inference_pipeline import inference_pipeline
from model_service import model_service
from pi_gateway import PI_GATEWAY_ENABLED, PI_GATEWAY_HOST, PI_GATEWAY_PORT, pi_gateway
from sonic_pi import sonic_pi_adapter
from state import live_state

DOWNLINK_MESSAGE_TYPES = frozenset({"led_command", "led_state", "led_config", "system_command", "time_sync"})


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)
    init_db()
    model_service.load()
    pi_gateway.set_handler(route_uplink_message)
    pi_gateway.start()
    sonic_pi_adapter.start()

    @app.get("/api/status")
    def status():
        return jsonify({
            "status": "ok",
            "camera_connected": live_state.camera_connected,
            "microbit_left": live_state.microbit_left_connected,
            "microbit_right": live_state.microbit_right_connected,
            "model_loaded": model_service.loaded,
            "pi_gateway": pi_gateway.status(),
            "sonic_pi": sonic_pi_adapter.status(),
            "inference": inference_pipeline.status(),
            "uptime_seconds": live_state.uptime_seconds(),
        })

    @app.get("/api/pi/status")
    def pi_status():
        return jsonify({"gateway": pi_gateway.status(), "runtime": live_state.get_pi_state()})

    @app.get("/api/pi/messages")
    def pi_messages():
        try:
            limit = int(request.args.get("limit", 50))
        except ValueError:
            return jsonify({"error": "limit must be an integer"}), 400
        message_type = request.args.get("message_type")
        if message_type and message_type not in UPLINK_MESSAGE_TYPES:
            return jsonify({"error": f"message_type must be one of {sorted(UPLINK_MESSAGE_TYPES)}"}), 400
        records = get_pi_message_history(message_type=message_type, limit=limit)
        return jsonify({"count": len(records), "records": records})

    @app.post("/api/pi/send")
    def pi_send():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        message_type = body.get("message_type", body.get("type"))
        if message_type not in DOWNLINK_MESSAGE_TYPES:
            return jsonify({"error": f"message_type must be one of {sorted(DOWNLINK_MESSAGE_TYPES)}"}), 400
        payload = body.get("payload", {})
        if not isinstance(payload, dict):
            return jsonify({"error": "payload must be a JSON object"}), 400
        if message_type == "led_command":
            required = {"effect", "brightness", "duration_ms"}
            missing = required.difference(payload)
            if missing:
                return jsonify({"error": f"led_command missing fields: {sorted(missing)}"}), 400
            try:
                brightness = float(payload["brightness"])
                duration_ms = int(payload["duration_ms"])
            except (TypeError, ValueError):
                return jsonify({"error": "brightness must be numeric and duration_ms must be an integer"}), 400
            if not 0.0 <= brightness <= 1.0 or duration_ms < 0:
                return jsonify({"error": "brightness must be in [0,1] and duration_ms must be >= 0"}), 400
            payload = dict(payload)
            payload["effect"] = str(payload["effect"])
            payload["brightness"] = brightness
            payload["duration_ms"] = duration_ms
            payload.setdefault("source", "backend")
        message = {
            "schema_version": str(body.get("schema_version", "draft")),
            "message_type": message_type,
            "sequence": body.get("sequence"),
            "created_at": time.time(),
            "payload": payload,
        }
        if not pi_gateway.send(message):
            return jsonify({"sent": False, "error": "Pi is not connected"}), 503
        return jsonify({"sent": True, "message": message})

    @app.get("/api/gesture/current")
    def gesture_current(): return jsonify(live_state.get_prediction())

    @app.get("/api/gesture/history")
    def gesture_history():
        try:
            limit = int(request.args.get("limit", 20))
            since_raw = request.args.get("since")
            since = float(since_raw) if since_raw not in (None, "") else None
        except ValueError:
            return jsonify({"error": "limit must be int and since must be float"}), 400
        records = get_prediction_history(limit=limit, since=since)
        return jsonify({"count": len(records), "records": records})

    @app.get("/api/sensors/live")
    def sensors_live(): return jsonify(live_state.get_sensors())

    @app.get("/api/music/state")
    def music_state(): return jsonify(live_state.get_music())

    @app.get("/api/sonic-pi/status")
    def sonic_pi_status(): return jsonify(sonic_pi_adapter.status())

    @app.post("/api/sonic-pi/transport")
    def sonic_pi_transport():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        action = str(body.get("action", "")).strip()
        if action not in {"start", "resume", "play", "pause", "stop", "cutoff", "reset"}:
            return jsonify({
                "error": "action must be one of start, resume, play, pause, stop, cutoff, reset"
            }), 400
        sent = sonic_pi_adapter.send_transport(action)
        if sent:
            live_state.apply_sonic_pi_transport_intent(action, time.time())
        return jsonify({
            "sent": sent,
            "music": live_state.get_music(),
            "sonic_pi": sonic_pi_adapter.status(),
            "inference": inference_pipeline.status(),
        }), 200 if sent else 503

    @app.post("/api/sonic-pi/state")
    def sonic_pi_state():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        sent = sonic_pi_adapter.send_state_from_music(
            live_state.get_music(),
            body,
        )
        return jsonify({"sent": sent, "sonic_pi": sonic_pi_adapter.status()}), 200 if sent else 503

    @app.errorhandler(404)
    def not_found(_error): return jsonify({"error": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled backend error: %s", error)
        return jsonify({"error": "Internal server error"}), 500

    app.config["AIOT_DB_PATH"] = str(DB_PATH)
    app.config["AIOT_PI_GATEWAY_ENABLED"] = PI_GATEWAY_ENABLED
    app.config["AIOT_PI_GATEWAY"] = f"{PI_GATEWAY_HOST}:{PI_GATEWAY_PORT}"
    return app


app = create_app()
atexit.register(pi_gateway.stop)
atexit.register(sonic_pi_adapter.stop)

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1").lower() in {"1", "true", "yes", "on"}
    app.run(host="0.0.0.0", port=int(os.getenv("FLASK_PORT", "5000")), debug=debug, use_reloader=False)
