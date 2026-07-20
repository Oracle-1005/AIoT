"""Feature extraction: per-frame instant features and sliding-window statistics."""

from .instant import InstantFeatureComputer
from .window import SlidingWindowComputer, WindowConfig

__all__ = [
    "InstantFeatureComputer",
    "SlidingWindowComputer",
    "WindowConfig",
]
