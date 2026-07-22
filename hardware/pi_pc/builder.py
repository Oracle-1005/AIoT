"""Message builder: constructs the 4 standard JSON message types.

Takes raw data from the fusion engine, feature extractors, and event
detectors and assembles full message dicts with common fields.
"""

import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageBuilder:
    """Builds JSON-serializable dicts for all 4 message types.

    Adds common fields (schema_version, session_id, packet_sequence, pi_id,
    timestamps) to every message. Maintains a global packet sequence counter.

    Args:
        schema_version: JSON schema version string.
        session_id: Unique session identifier. Auto-generated if None.
        pi_id: Identifier for this Raspberry Pi instance.
    """

    def __init__(
        self,
        schema_version: str = "1.1",
        session_id: str | None = None,
        pi_id: str = "raspberrypi-01",
    ):
        self._schema_version = schema_version
        self._session_id = session_id or self._generate_session_id()
        self._pi_id = pi_id
        self._packet_sequence = 0

    # ---- Public API ----

    def build_fused_frame(self, fusion_result: dict) -> dict:
        """Add common fields to a fused_frame dict from FusionEngine.

        Args:
            fusion_result: Dict from FusionEngine.fuse().

        Returns:
            Complete fused_frame message dict.
        """
        msg = self._common_fields("fused_frame")
        # Merge fusion target timestamp
        msg["timestamps"]["fusion_target_timestamp_ns"] = fusion_result.get(
            "timestamps", {}
        ).get("fusion_target_timestamp_ns", 0)

        msg["camera"] = fusion_result.get("camera", {})
        msg["microbits"] = fusion_result.get("microbits", [])
        msg["fusion"] = fusion_result.get("fusion", {})

        return msg

    def build_control_event(self, event_data: dict) -> dict:
        """Build a control_event message.

        Args:
            event_data: Dict with keys: event_id, event, music_control, led_control.

        Returns:
            Complete control_event message dict.
        """
        msg = self._common_fields("control_event")
        msg["event_id"] = event_data.get("event_id", "")
        msg["event"] = event_data.get("event", {})
        msg["music_control"] = event_data.get("music_control", {})
        msg["led_control"] = event_data.get("led_control", {})

        return msg

    def build_status(self, status_data: dict) -> dict:
        """Build a status message.

        Args:
            status_data: Dict with keys: camera, microbits, network, led.

        Returns:
            Complete status message dict.
        """
        msg = self._common_fields("status")
        msg["camera"] = status_data.get("camera", {})
        msg["microbits"] = status_data.get("microbits", {})
        msg["network"] = status_data.get("network", {})
        msg["led"] = status_data.get("led", {})

        return msg

    # ---- Properties ----

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def packet_sequence(self) -> int:
        return self._packet_sequence

    # ---- Internal ----

    def _common_fields(self, message_type: str) -> dict:
        """Return a dict with fields common to all message types.

        Increments the global packet sequence counter.

        Args:
            message_type: One of MESSAGE_TYPES.

        Returns:
            Dict with common fields populated.
        """
        self._packet_sequence += 1
        return {
            "schema_version": self._schema_version,
            "message_type": message_type,
            "session_id": self._session_id,
            "packet_sequence": self._packet_sequence,
            "pi_id": self._pi_id,
            "timestamps": {
                "pi_packet_created_mono_ns": time.monotonic_ns(),
                "pi_unix_time_ns": int(time.time() * 1e9),
            },
        }

    @staticmethod
    def _generate_session_id() -> str:
        """Generate a unique session ID based on the current datetime."""
        return f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
