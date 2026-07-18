"""SQLite persistence for backend history, predictions and Pi uplink data."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "aiot.db"
DB_PATH = Path(os.getenv("AIOT_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()


def _ensure_parent_directory() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    _ensure_parent_directory()
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sensor_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pc_ts REAL NOT NULL,
                device_id TEXT NOT NULL,
                acc_x REAL,
                acc_y REAL,
                acc_z REAL,
                hand_data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pc_ts REAL NOT NULL,
                gesture TEXT NOT NULL,
                confidence REAL NOT NULL,
                all_probs TEXT NOT NULL,
                features_used INTEGER,
                latency_ms REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT,
                total_predictions INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS pi_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at REAL NOT NULL,
                message_type TEXT NOT NULL,
                schema_version TEXT,
                session_id TEXT,
                packet_sequence INTEGER,
                pi_id TEXT,
                source_address TEXT,
                payload TEXT NOT NULL,
                raw_message TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_pi_messages_type_time
            ON pi_messages(message_type, received_at DESC);
            """
        )


def insert_pi_message(message: dict[str, Any]) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO pi_messages
                (received_at, message_type, schema_version, session_id,
                 packet_sequence, pi_id, source_address, payload, raw_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                float(message["received_at"]),
                str(message["message_type"]),
                message.get("schema_version"),
                message.get("session_id"),
                message.get("packet_sequence"),
                message.get("pi_id"),
                message.get("source_address"),
                json.dumps(message.get("payload", {}), ensure_ascii=False),
                json.dumps(message.get("raw", {}), ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid)


def get_pi_message_history(
    *, message_type: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    query = """
        SELECT id, received_at, message_type, schema_version, session_id,
               packet_sequence, pi_id, source_address, payload, created_at
        FROM pi_messages
    """
    params: list[Any] = []
    if message_type:
        query += " WHERE message_type = ?"
        params.append(message_type)
    query += " ORDER BY received_at DESC, id DESC LIMIT ?"
    params.append(safe_limit)
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "id": row["id"],
            "received_at": row["received_at"],
            "message_type": row["message_type"],
            "schema_version": row["schema_version"],
            "session_id": row["session_id"],
            "packet_sequence": row["packet_sequence"],
            "pi_id": row["pi_id"],
            "source_address": row["source_address"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def insert_sensor_record(*, pc_ts: float, device_id: str, acc_x: float | None = None,
                         acc_y: float | None = None, acc_z: float | None = None,
                         hand_data: dict[str, Any] | list[Any] | None = None) -> int:
    hand_data_json = json.dumps(hand_data, ensure_ascii=False) if hand_data is not None else None
    with get_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO sensor_records
               (pc_ts, device_id, acc_x, acc_y, acc_z, hand_data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pc_ts, device_id, acc_x, acc_y, acc_z, hand_data_json),
        )
        return int(cursor.lastrowid)


def insert_prediction(result: dict[str, Any], *, latency_ms: float | None = None) -> int:
    required = {"gesture", "confidence", "timestamp", "all_probs"}
    missing = required.difference(result)
    if missing:
        raise ValueError(f"Missing prediction fields: {sorted(missing)}")
    with get_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO predictions
               (pc_ts, gesture, confidence, all_probs, features_used, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (float(result["timestamp"]), str(result["gesture"]), float(result["confidence"]),
             json.dumps(result["all_probs"], ensure_ascii=False), result.get("features_used"),
             latency_ms if latency_ms is not None else result.get("latency_ms")),
        )
        return int(cursor.lastrowid)


def get_latest_prediction() -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT id, pc_ts, gesture, confidence, all_probs,
                      features_used, latency_ms, created_at
               FROM predictions ORDER BY pc_ts DESC, id DESC LIMIT 1"""
        ).fetchone()
    return _prediction_row_to_dict(row) if row else None


def get_prediction_history(limit: int = 20, since: float | None = None) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    query = """SELECT id, pc_ts, gesture, confidence, all_probs,
                      features_used, latency_ms, created_at FROM predictions"""
    params: list[Any] = []
    if since is not None:
        query += " WHERE pc_ts >= ?"
        params.append(float(since))
    query += " ORDER BY pc_ts DESC, id DESC LIMIT ?"
    params.append(safe_limit)
    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [_prediction_row_to_dict(row) for row in rows]


def _prediction_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "gesture": row["gesture"], "confidence": row["confidence"],
        "all_probs": json.loads(row["all_probs"]), "timestamp": row["pc_ts"],
        "features_used": row["features_used"], "latency_ms": row["latency_ms"],
        "created_at": row["created_at"],
    }


if __name__ == "__main__":
    init_db()
    print(json.dumps({"database_path": str(DB_PATH), "status": "ok"}, indent=2))
