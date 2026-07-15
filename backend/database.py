"""SQLite persistence for the AIoT Smart Conducting backend.

The table schemas follow docs/INTERFACE_CONTRACT.md section 6.
"""

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
    """Open a SQLite connection with dictionary-like rows."""
    _ensure_parent_directory()
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    """Create all tables required by the interface contract."""
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
            """
        )


def insert_sensor_record(
    *,
    pc_ts: float,
    device_id: str,
    acc_x: float | None = None,
    acc_y: float | None = None,
    acc_z: float | None = None,
    hand_data: dict[str, Any] | list[Any] | None = None,
) -> int:
    """Insert one Micro:bit or camera record and return its ID."""
    hand_data_json = json.dumps(hand_data, ensure_ascii=False) if hand_data is not None else None
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO sensor_records
                (pc_ts, device_id, acc_x, acc_y, acc_z, hand_data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pc_ts, device_id, acc_x, acc_y, acc_z, hand_data_json),
        )
        return int(cursor.lastrowid)


def insert_prediction(
    result: dict[str, Any],
    *,
    latency_ms: float | None = None,
) -> int:
    """Store a model result matching Interface ③."""
    required = {"gesture", "confidence", "timestamp", "all_probs"}
    missing = required.difference(result)
    if missing:
        raise ValueError(f"Missing prediction fields: {sorted(missing)}")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO predictions
                (pc_ts, gesture, confidence, all_probs, features_used, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                float(result["timestamp"]),
                str(result["gesture"]),
                float(result["confidence"]),
                json.dumps(result["all_probs"], ensure_ascii=False),
                result.get("features_used"),
                latency_ms if latency_ms is not None else result.get("latency_ms"),
            ),
        )
        return int(cursor.lastrowid)


def get_latest_prediction() -> dict[str, Any] | None:
    """Return the most recent prediction."""
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, pc_ts, gesture, confidence, all_probs,
                   features_used, latency_ms, created_at
            FROM predictions
            ORDER BY pc_ts DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    return _prediction_row_to_dict(row) if row else None


def get_prediction_history(limit: int = 20, since: float | None = None) -> list[dict[str, Any]]:
    """Query recent predictions for GET /api/gesture/history."""
    safe_limit = max(1, min(int(limit), 500))

    query = """
        SELECT id, pc_ts, gesture, confidence, all_probs,
               features_used, latency_ms, created_at
        FROM predictions
    """
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
        "id": row["id"],
        "gesture": row["gesture"],
        "confidence": row["confidence"],
        "all_probs": json.loads(row["all_probs"]),
        "timestamp": row["pc_ts"],
        "features_used": row["features_used"],
        "latency_ms": row["latency_ms"],
        "created_at": row["created_at"],
    }


def database_self_test() -> dict[str, Any]:
    """Write and read one harmless test record."""
    init_db()
    test_id = insert_prediction(
        {
            "gesture": "idle",
            "confidence": 0.0,
            "gesture_id": 0,
            "timestamp": 0.0,
            "features_used": 0,
            "all_probs": {
                "idle": 1.0,
                "downbeat": 0.0,
                "crescendo": 0.0,
                "decrescendo": 0.0,
                "cutoff": 0.0,
                "style_switch": 0.0,
                "tempo_up": 0.0,
                "tempo_down": 0.0,
            },
        }
    )
    latest = get_latest_prediction()
    return {"inserted_id": test_id, "latest": latest, "database_path": str(DB_PATH)}


if __name__ == "__main__":
    print(json.dumps(database_self_test(), indent=2, ensure_ascii=False))
