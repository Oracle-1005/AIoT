"""Flask backend for the AIoT Smart Conducting System.

This implementation follows the original INTERFACE_CONTRACT.md:
- Interface ③: model is imported and called in the same process.
- Interface ④: frontend reads REST endpoints.
- Interface ⑤: history is persisted in SQLite.
- Interface ⑥: accepted predictions are published over MQTT.
"""

from __future__ import annotations

import atexit
import os

from flask import Flask, jsonify, request
from flask_cors import CORS

from database import DB_PATH, get_prediction_history, init_db
from model_service import model_service
from mqtt_client import MQTT_ENABLED, MQTT_HOST, MQTT_PORT, mqtt_client
from state import live_state


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    init_db()
    model_service.load()
    mqtt_client.start()

    @app.get("/api/status")
    def status():
        return jsonify(
            {
                "status": "ok",
                "camera_connected": live_state.camera_connected,
                "microbit_left": live_state.microbit_left_connected,
                "microbit_right": live_state.microbit_right_connected,
                "model_loaded": model_service.loaded,
                "uptime_seconds": live_state.uptime_seconds(),
            }
        )

    @app.get("/api/gesture/current")
    def gesture_current():
        return jsonify(live_state.get_prediction())

    @app.get("/api/gesture/history")
    def gesture_history():
        try:
            limit = int(request.args.get("limit", 20))
            since_raw = request.args.get("since")
            since = float(since_raw) if since_raw not in (None, "") else None
        except ValueError:
            return jsonify({"error": "`limit` must be int and `since` must be float"}), 400

        records = get_prediction_history(limit=limit, since=since)
        return jsonify({"count": len(records), "records": records})

    @app.get("/api/sensors/live")
    def sensors_live():
        return jsonify(live_state.get_sensors())

    @app.get("/api/music/state")
    def music_state():
        return jsonify(live_state.get_music())

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled backend error: %s", error)
        return jsonify({"error": "Internal server error"}), 500

    app.config["AIOT_DB_PATH"] = str(DB_PATH)
    app.config["AIOT_MQTT_ENABLED"] = MQTT_ENABLED
    app.config["AIOT_MQTT_BROKER"] = f"{MQTT_HOST}:{MQTT_PORT}"
    return app


app = create_app()
atexit.register(mqtt_client.stop)


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1").lower() in {"1", "true", "yes", "on"}
    # Disable the reloader because it otherwise initializes MQTT twice.
    app.run(host="0.0.0.0", port=5000, debug=debug, use_reloader=False)
