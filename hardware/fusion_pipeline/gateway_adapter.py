"""UDP gateway adapter: receive ESP32 MBGW frames, parse, filter, track.

Data flow per datagram:
  1. Receive UDP datagram → capture pi_rx_monotonic_ns
  2. Parse MBGW frame header → extract payload + gateway metadata
  3. Decode micro:bit packet header → hand + message_type
  4. Parse payload → SensorState or ControlEvent
  5. Sequence-track sensor states (gap detection, restart detection)
  6. Deduplicate control events (TTL-based)
  7. Apply noise filter (EMA + median outlier rejection) to sensor states
  8. Route:
     - Sensor states → callback to fusion engine buffers
     - Control events → immediate fast-path callback for TCP send
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

# Reused from existing hardware modules.
# Paths are set up by main.py before importing this module.
from esp32_gateway_receiver.gateway_frame import (
    GatewayFrame,
    GatewayFrameError,
    parse_gateway_frame,
)
from microbit_receiver.protocol import (
    ControlEvent,
    Hand,
    ProtocolError,
    SensorState,
    decode_header,
    parse_packet,
)
from microbit_receiver.tracking import EventDeduplicator, SequenceTracker
from pi_pc.noise_filter import MicrobitNoiseFilter, FilteredIMUData

logger = logging.getLogger(__name__)

CONTROL_EVENT_GESTURE_MAP = {
    "start_or_resume": "resume",
    "pause": "cutoff",
    "style_switch": "style_switch",
    "emergency_stop": "stop",
    "recalibrate": "gesture_start",
}


@dataclass
class MicrobitSample:
    """A fully processed micro:bit sensor sample, ready for fusion."""

    source: str                     # "left" or "right"
    sample_sequence: int
    device_timestamp_ms: int
    pi_rx_monotonic_ns: int         # UDP arrival time (time anchor for alignment)
    ax_mg: float
    ay_mg: float
    az_mg: float
    pitch_deg: float
    roll_deg: float
    sequence_status: str            # "in_order", "sequence_gap", "first_sample", "device_restart"
    missing_sample_count: int
    device_restarted: bool
    ble_rssi: int
    gateway_sequence: int
    filtered: bool = True
    outlier_detected: bool = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "sample_sequence": self.sample_sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "pi_rx_monotonic_ns": self.pi_rx_monotonic_ns,
            "ax_mg": self.ax_mg,
            "ay_mg": self.ay_mg,
            "az_mg": self.az_mg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "sequence_status": self.sequence_status,
            "missing_sample_count": self.missing_sample_count,
            "device_restarted": self.device_restarted,
            "ble_rssi": self.ble_rssi,
            "gateway_sequence": self.gateway_sequence,
            "filtered": self.filtered,
            "outlier_detected": self.outlier_detected,
        }


@dataclass
class GatewayStatus:
    """Latest gateway metadata for the periodic status message."""

    left_rssi: int = 0
    right_rssi: int = 0
    left_missing_sample_count: int = 0
    right_missing_sample_count: int = 0
    left_last_sample_ns: int = 0
    right_last_sample_ns: int = 0


# ── UDP Protocol ───────────────────────────────────────────────────────────

class _GatewayProtocol(asyncio.DatagramProtocol):
    """asyncio DatagramProtocol that feeds parsed data into GatewayAdapter."""

    def __init__(self, adapter: "GatewayAdapter") -> None:
        self._adapter = adapter

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._adapter._handle_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.warning("Gateway UDP socket error: %s", exc)


# ── GatewayAdapter ─────────────────────────────────────────────────────────

class GatewayAdapter:
    """Receives ESP32 MBGW UDP frames, processes them, and routes output.

    Args:
        listen_host: UDP bind address (default "0.0.0.0").
        listen_port: UDP bind port (default 17778).
        allowed_hands: Set of Hand values to accept.
        event_dedup_ttl_s: TTL for control event deduplication.
        noise_filter_config: Dict forwarded to MicrobitNoiseFilter factory.
        on_sensor_state: Callback(MicrobitSample) — push to fusion buffers.
        on_control_event: Callback(dict) — immediate fast-path TCP send.
    """

    def __init__(
        self,
        *,
        listen_host: str = "0.0.0.0",
        listen_port: int = 17778,
        allowed_hands: set[Hand] | None = None,
        event_dedup_ttl_s: float = 10.0,
        noise_filter_config: dict | None = None,
        on_raw_sensor_state: Callable[[dict], None] | None = None,
        on_sensor_state: Callable[[MicrobitSample], None] | None = None,
        on_control_event: Callable[[dict], None] | None = None,
    ) -> None:
        self._listen_host = listen_host
        self._listen_port = listen_port
        self._allowed_hands = allowed_hands or {Hand.LEFT, Hand.RIGHT}

        self._on_raw_sensor_state = on_raw_sensor_state
        self._on_sensor_state = on_sensor_state
        self._on_control_event = on_control_event

        # Per-hand tracking
        self._sequence_tracker = SequenceTracker()
        self._event_deduplicator = EventDeduplicator(event_dedup_ttl_s)

        # Noise filters (one per hand)
        nf_cfg = noise_filter_config or {}
        self._noise_filters: dict[Hand, MicrobitNoiseFilter] = {
            Hand.LEFT: MicrobitNoiseFilter(
                device_id="MB_LEFT",
                ema_alpha_accel=nf_cfg.get("ema_alpha_accel", 0.85),
                ema_alpha_orientation=nf_cfg.get("ema_alpha_orientation", 0.90),
                median_window=nf_cfg.get("median_window", 5),
                outlier_threshold_mg=nf_cfg.get("outlier_threshold_mg", 500.0),
            ),
            Hand.RIGHT: MicrobitNoiseFilter(
                device_id="MB_RIGHT",
                ema_alpha_accel=nf_cfg.get("ema_alpha_accel", 0.85),
                ema_alpha_orientation=nf_cfg.get("ema_alpha_orientation", 0.90),
                median_window=nf_cfg.get("median_window", 5),
                outlier_threshold_mg=nf_cfg.get("outlier_threshold_mg", 500.0),
            ),
        }

        # Gateway metadata for status
        self._status = GatewayStatus()

        # Transport handle
        self._transport: asyncio.DatagramTransport | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Bind UDP socket and begin receiving gateway frames."""
        loop = asyncio.get_running_loop()
        self._transport, _protocol = await loop.create_datagram_endpoint(
            lambda: _GatewayProtocol(self),
            local_addr=(self._listen_host, self._listen_port),
        )
        logger.info(
            "GatewayAdapter listening on %s:%d",
            self._listen_host,
            self._listen_port,
        )

    async def stop(self) -> None:
        """Close UDP socket."""
        if self._transport:
            self._transport.close()
            self._transport = None
        logger.info("GatewayAdapter stopped.")

    # ── Public API ─────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return gateway-side status for the periodic status message."""
        s = self._status
        now_ns = time.monotonic_ns()

        def _age_ms(last_ns: int) -> float:
            if last_ns == 0:
                return 0.0
            return (now_ns - last_ns) / 1_000_000.0

        return {
            "left_age_ms": round(_age_ms(s.left_last_sample_ns), 1),
            "right_age_ms": round(_age_ms(s.right_last_sample_ns), 1),
            "left_rssi": s.left_rssi,
            "right_rssi": s.right_rssi,
            "left_missing_sample_count": s.left_missing_sample_count,
            "right_missing_sample_count": s.right_missing_sample_count,
        }

    # ── Internal: Datagram Handler ─────────────────────────────────────

    def _handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        """Process one UDP datagram from the ESP32 gateway."""
        pi_rx_ns = time.monotonic_ns()

        try:
            frame = parse_gateway_frame(data)
        except GatewayFrameError as exc:
            logger.debug("Bad gateway frame from %s:%d: %s", *addr, exc)
            return

        self._handle_gateway_frame(
            frame,
            addr,
            pi_rx_ns,
            transport_name="esp32_udp_gateway",
        )

    def _handle_gateway_frame(
        self,
        frame: GatewayFrame,
        addr: tuple[str, int],
        pi_rx_ns: int,
        *,
        transport_name: str,
        gateway_metadata: dict | None = None,
    ) -> None:
        """Decode and process a normalized gateway frame.

        Transport adapters may construct ``GatewayFrame`` instances and enter
        the existing protocol, tracking and filtering path here.
        """
        try:
            message_type, hand = decode_header(frame.payload[0])
        except ProtocolError as exc:
            logger.debug("Bad packet header from %s:%d: %s", *addr, exc)
            return

        if hand not in self._allowed_hands:
            logger.debug("Ignoring hand %s (not in allowed_hands)", hand.label)
            return

        try:
            packet = parse_packet(
                frame.payload,
                expected_hand=hand,
                pi_rx_monotonic_ns=pi_rx_ns,
            )
        except ProtocolError as exc:
            logger.debug("Packet parse error from %s:%d: %s", *addr, exc)
            return

        if isinstance(packet, ControlEvent):
            self._handle_control_event(
                packet,
                frame,
                addr,
                transport_name=transport_name,
                gateway_metadata=gateway_metadata,
            )
        else:
            self._handle_sensor_state(
                packet,
                frame,
                addr,
                pi_rx_ns,
                transport_name=transport_name,
                gateway_metadata=gateway_metadata,
            )

    def _handle_sensor_state(
        self,
        packet: SensorState,
        frame: GatewayFrame,
        addr: tuple[str, int],
        pi_rx_ns: int,
        *,
        transport_name: str,
        gateway_metadata: dict | None = None,
    ) -> None:
        """Process a sensor_state packet through tracking + noise filter."""
        hand = packet.hand

        if self._on_raw_sensor_state:
            raw_item = packet.to_dict()
            raw_item["transport"] = transport_name
            raw_item["gateway"] = {
                "source_ip": addr[0],
                "source_port": addr[1],
                "gateway_sequence": frame.gateway_sequence,
                "esp_rx_micros": frame.esp_rx_micros,
                "conn_index": frame.conn_index,
                "ble_rssi": frame.ble_rssi,
                "flags": frame.flags,
            }
            if gateway_metadata:
                raw_item["gateway"].update(gateway_metadata)
            try:
                self._on_raw_sensor_state(raw_item)
            except Exception:
                logger.exception("on_raw_sensor_state callback failed")

        # ── Sequence tracking ──────────────────────────────────────────
        decision = self._sequence_tracker.observe(packet)
        if not decision.accept:
            logger.debug(
                "drop %s sensor seq=%d: %s",
                hand.label,
                packet.sample_sequence,
                decision.reason,
            )
            return

        # ── Noise filter ───────────────────────────────────────────────
        nf = self._noise_filters[hand]
        filtered: FilteredIMUData = nf.filter(
            ax_mg=packet.ax_mg,
            ay_mg=packet.ay_mg,
            az_mg=packet.az_mg,
            pitch_deg=packet.pitch_deg,
            roll_deg=packet.roll_deg,
        )

        # ── Clear event dedup cache on device restart ──────────────────
        if decision.device_restarted:
            self._event_deduplicator.clear(hand)

        # ── Build sample ───────────────────────────────────────────────
        sample = MicrobitSample(
            source=hand.label,
            sample_sequence=packet.sample_sequence,
            device_timestamp_ms=packet.device_timestamp_ms,
            pi_rx_monotonic_ns=pi_rx_ns,
            ax_mg=filtered.ax_mg,
            ay_mg=filtered.ay_mg,
            az_mg=filtered.az_mg,
            pitch_deg=filtered.pitch_deg,
            roll_deg=filtered.roll_deg,
            sequence_status=decision.reason,
            missing_sample_count=decision.missing_sample_count,
            device_restarted=decision.device_restarted,
            ble_rssi=frame.ble_rssi,
            gateway_sequence=frame.gateway_sequence,
            filtered=True,
            outlier_detected=filtered.outlier_detected,
        )

        # ── Update status ──────────────────────────────────────────────
        if hand is Hand.LEFT:
            self._status.left_rssi = frame.ble_rssi
            self._status.left_missing_sample_count += decision.missing_sample_count
            self._status.left_last_sample_ns = pi_rx_ns
        else:
            self._status.right_rssi = frame.ble_rssi
            self._status.right_missing_sample_count += decision.missing_sample_count
            self._status.right_last_sample_ns = pi_rx_ns

        # ── Emit ───────────────────────────────────────────────────────
        if self._on_sensor_state:
            try:
                self._on_sensor_state(sample)
            except Exception:
                logger.exception("on_sensor_state callback failed")

    def _handle_control_event(
        self,
        packet: ControlEvent,
        frame: GatewayFrame,
        addr: tuple[str, int],
        *,
        transport_name: str,
        gateway_metadata: dict | None = None,
    ) -> None:
        """Process a control_event packet — dedup and fast-path emit."""
        # Deduplicate
        duplicate = self._event_deduplicator.is_duplicate(packet)
        if duplicate:
            logger.debug(
                "Ignore duplicate control event %s/%d",
                packet.hand.label,
                packet.event_sequence,
            )
            return

        # Build backend-compatible event dict.
        raw_event = packet.to_dict(duplicate=False)
        gateway = {
            "source_ip": addr[0],
            "ble_rssi": frame.ble_rssi,
            "flags": frame.flags,
            "transport": transport_name,
        }
        if gateway_metadata:
            gateway.update(gateway_metadata)
        event = self._build_backend_control_event(raw_event, gateway)

        # Fast path: emit immediately via callback
        if self._on_control_event:
            try:
                self._on_control_event(event)
            except Exception:
                logger.exception("on_control_event callback failed")

    @staticmethod
    def _build_backend_control_event(raw_event: dict, gateway: dict) -> dict:
        """Convert the micro:bit protocol event into backend control_event.

        backend.message_router accepts "control_event" and state.py expects the
        gesture name at payload.event.type.
        """
        candidate = str(raw_event.get("mapped_candidate", "")).strip()
        gesture = CONTROL_EVENT_GESTURE_MAP.get(candidate, candidate)
        source = str(raw_event.get("source", "")).strip()

        return {
            "type": "control_event",
            "schema_version": "1.0",
            "source": source,
            "event_sequence": raw_event.get("event_sequence", 0),
            "pi_rx_monotonic_ns": raw_event.get("pi_rx_monotonic_ns", 0),
            "payload": {
                "event": {
                    "type": gesture,
                    "source": source,
                    "code": raw_event.get("event_code", ""),
                    "candidate": candidate,
                    "priority": raw_event.get("priority", 0),
                    "repeat_index": raw_event.get("repeat_index", 0),
                    "repeat_total": raw_event.get("repeat_total", 0),
                    "strength": 1.0,
                },
                "music_control": {},
                "microbit": raw_event,
                "gateway": gateway,
            },
        }
