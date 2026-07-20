"""Abstract base class for pluggable sensor sources.

All sensor types (BLE micro:bit, camera, future sensors) implement this
interface, enabling uniform integration with the FusionEngine.
"""

from abc import ABC, abstractmethod


class SensorSource(ABC):
    """Abstract interface for any sensor that produces timestamped samples.

    Subclasses must implement start(), stop(), is_running(), and get_status().
    """

    @abstractmethod
    async def start(self) -> bool:
        """Initialize and start data acquisition.

        Returns:
            True if started successfully.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop data acquisition and release resources."""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """Return whether the sensor is actively producing data."""
        ...

    @abstractmethod
    def get_status(self) -> dict:
        """Return a status dict for the status monitoring message.

        The returned dict should contain at minimum:
        - connected: bool
        - Any sensor-specific health metrics.
        """
        ...
