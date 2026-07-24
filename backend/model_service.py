"""Adapter for Interface ③: backend imports the model in the same process.

This file intentionally does not introduce an HTTP inference endpoint.
When the model package is delivered, it should expose:

    from model.inference import GestureClassifier

and GestureClassifier.predict(window_data) should return the dictionary
defined in docs/INTERFACE_CONTRACT.md section 4.3.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# model/ 包在仓库根目录；以 `python backend/app.py` 方式启动时 sys.path[0]
# 是 backend/，需要把仓库根加进来才能 `from model.inference import ...`（幂等）。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_MODEL_PATH = PROJECT_ROOT / "model" / "models" / "gesture_classifier.pkl"
MODEL_PATH = os.getenv("AIOT_MODEL_PATH", str(DEFAULT_MODEL_PATH))


class ModelService:
    def __init__(self) -> None:
        self.classifier: Any | None = None
        self.load_error: str | None = None

    @property
    def loaded(self) -> bool:
        return self.classifier is not None

    def load(self) -> bool:
        """Try to import and initialize the model without crashing Flask."""
        try:
            from model.inference import GestureClassifier  # type: ignore

            self.classifier = GestureClassifier(model_path=MODEL_PATH)
            self.load_error = None
            print(f"[Model] Loaded classifier from {MODEL_PATH}")
            return True
        except (ImportError, FileNotFoundError, TypeError, ValueError) as exc:
            self.classifier = None
            self.load_error = str(exc)
            print(f"[Model] Not loaded yet: {exc}")
            return False

    def predict(self, window_data: Any) -> dict[str, Any]:
        """Call the model in-process and validate its result."""
        if self.classifier is None:
            raise RuntimeError(
                "Model is not loaded. Add model/inference and the model file, "
                "then restart the backend."
            )

        started = time.perf_counter()
        result = self.classifier.predict(window_data)
        latency_ms = (time.perf_counter() - started) * 1000.0

        if not isinstance(result, dict):
            raise TypeError("GestureClassifier.predict() must return a dict")

        required = {
            "gesture",
            "confidence",
            "gesture_id",
            "timestamp",
            "features_used",
            "all_probs",
        }
        missing = required.difference(result)
        if missing:
            raise ValueError(f"Model result missing fields: {sorted(missing)}")

        confidence = float(result["confidence"])
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Model confidence must be in the range 0–1")

        normalized = dict(result)
        normalized["latency_ms"] = round(latency_ms, 3)
        return normalized


model_service = ModelService()
