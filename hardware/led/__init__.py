"""LED control layer: WS2812B via rpi_ws281x."""

try:
    from .controller import LedController
except ImportError:
    LedController = None  # type: ignore

__all__ = ["LedController"]
