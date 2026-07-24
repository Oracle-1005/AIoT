"""Model inference package — backend 同进程调用入口（契约见 INTERFACE_CONTRACT §4.3）。"""

from .gesture_classifier import (
    CANONICAL_GESTURES,
    FEATURE_NAMES,
    FEATURE_VERSION,
    GESTURE_IDS,
    GestureClassifier,
)

__all__ = [
    "GestureClassifier",
    "CANONICAL_GESTURES",
    "GESTURE_IDS",
    "FEATURE_VERSION",
    "FEATURE_NAMES",
]
