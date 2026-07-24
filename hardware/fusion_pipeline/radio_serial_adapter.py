"""micro:bit Radio USB serial transport for the existing fusion pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - only used for PC-side unit tests
    termios = None
    tty = None

from esp32_gateway_receiver.gateway_frame import GatewayFrame
from microbit_receiver.protocol import Hand

from fusion_pipeline.gateway_adapter import GatewayAdapter, MicrobitSample

logger = logging.getLogger(__name__)

PROTOCOL_TAG = "GW1"
VALID_PAYLOAD_LENGTHS = {11, 17}
MAX_BUFFER_BYTES = 4096


class RadioSerialAdapter(GatewayAdapter):
    """Read GW1 lines from a USB-connected micro:bit Radio gateway.

    The class only replaces the transport. Decoding, sequence tracking, event
    deduplication, noise filtering and callback output remain implemented by
    :class:`GatewayAdapter`.
    """

    def __init__(
        self,
        *,
        device: str,
        baud_rate: int = 115200,
        reconnect_delay_s: float = 1.0,
        allowed_hands: set[Hand] | None = None,
        event_dedup_ttl_s: float = 10.0,
        noise_filter_config: dict | None = None,
        on_raw_sensor_state: Callable[[dict], None] | None = None,
        on_sensor_state: Callable[[MicrobitSample], None] | None = None,
        on_control_event: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(
            allowed_hands=allowed_hands,
            event_dedup_ttl_s=event_dedup_ttl_s,
            noise_filter_config=noise_filter_config,
            on_raw_sensor_state=on_raw_sensor_state,
            on_sensor_state=on_sensor_state,
            on_control_event=on_control_event,
        )
        self._device = device
        self._baud_rate = baud_rate
        self._reconnect_delay_s = reconnect_delay_s
        self._fd: int | None = None
        self._reader_task: asyncio.Task | None = None
        self._running = False
        self._buffer = bytearray()
        self._gateway_sequence = 0
        self._serial_connected = False
        self._received_lines = 0
        self._parse_errors = 0
        self._last_gateway_rx_ms = 0

    async def start(self) -> None:
        self._running = True
        self._reader_task = asyncio.create_task(
            self._read_loop(),
            name="microbit-radio-serial",
        )
        logger.info(
            "RadioSerialAdapter starting on %s at %d baud",
            self._device,
            self._baud_rate,
        )

    async def stop(self) -> None:
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        self._close_device()
        logger.info("RadioSerialAdapter stopped.")

    def get_status(self) -> dict:
        status = super().get_status()
        status.update(
            {
                "transport": "microbit_radio_usb",
                "serial_device": self._device,
                "serial_connected": self._serial_connected,
                "serial_received_lines": self._received_lines,
                "serial_parse_errors": self._parse_errors,
                "gateway_rx_ms": self._last_gateway_rx_ms,
            }
        )
        return status

    async def _read_loop(self) -> None:
        while self._running:
            if self._fd is None:
                try:
                    self._open_device()
                except OSError as exc:
                    self._serial_connected = False
                    logger.warning(
                        "Cannot open Radio gateway %s: %s; retrying in %.1fs",
                        self._device,
                        exc,
                        self._reconnect_delay_s,
                    )
                    await asyncio.sleep(self._reconnect_delay_s)
                    continue

            try:
                chunk = os.read(self._fd, 512)
            except BlockingIOError:
                await asyncio.sleep(0.005)
                continue
            except OSError as exc:
                logger.warning("Radio gateway read failed: %s", exc)
                self._close_device()
                await asyncio.sleep(self._reconnect_delay_s)
                continue

            if not chunk:
                await asyncio.sleep(0.005)
                continue

            self._buffer.extend(chunk)
            if len(self._buffer) > MAX_BUFFER_BYTES:
                self._buffer.clear()
                self._parse_errors += 1
                logger.warning("Radio gateway serial buffer overflow; cleared")
                continue

            while b"\n" in self._buffer:
                raw_line, _, remainder = self._buffer.partition(b"\n")
                self._buffer = bytearray(remainder)
                self._handle_serial_line(raw_line)

    def _open_device(self) -> None:
        if termios is None or tty is None:
            raise OSError("Radio USB serial transport requires a POSIX system")
        fd = os.open(
            self._device,
            os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK,
        )
        try:
            tty.setraw(fd, when=termios.TCSANOW)
            attrs = termios.tcgetattr(fd)
            speed = getattr(termios, f"B{self._baud_rate}", termios.B115200)
            attrs[4] = speed
            attrs[5] = speed
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:
            os.close(fd)
            raise
        self._fd = fd
        self._serial_connected = True
        self._buffer.clear()
        logger.info("Radio gateway serial connected: %s", self._device)

    def _close_device(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
        self._fd = None
        self._serial_connected = False
        self._buffer.clear()

    def _handle_serial_line(self, raw_line: bytes) -> None:
        line = raw_line.lstrip(b"\x00").decode("ascii", errors="replace").strip()
        if not line:
            return

        parts = line.split(",", 4)
        if parts[0] != PROTOCOL_TAG:
            self._record_parse_error("unexpected tag", line)
            return

        if len(parts) >= 2 and parts[1] == "READY":
            logger.info("Radio gateway ready: %s", line)
            return
        if len(parts) >= 2 and parts[1] == "STATUS":
            logger.info("Radio gateway status: %s", line)
            return
        if len(parts) != 5:
            self._record_parse_error("wrong field count", line)
            return

        try:
            gateway_rx_ms = int(parts[1])
            rssi = int(parts[2])
            sender_serial = int(parts[3])
            payload = bytes.fromhex(parts[4])
        except (ValueError, OverflowError):
            self._record_parse_error("invalid numeric or hex field", line)
            return

        if len(payload) not in VALID_PAYLOAD_LENGTHS:
            self._record_parse_error(
                f"payload length {len(payload)} is not 11 or 17",
                line,
            )
            return
        if not -128 <= rssi <= 0:
            self._record_parse_error(f"RSSI out of range: {rssi}", line)
            return

        self._received_lines += 1
        self._last_gateway_rx_ms = gateway_rx_ms
        self._gateway_sequence = (self._gateway_sequence + 1) & 0xFFFF_FFFF
        pi_rx_ns = time.monotonic_ns()

        frame = GatewayFrame(
            gateway_sequence=self._gateway_sequence,
            esp_rx_micros=(gateway_rx_ms * 1000) & 0xFFFF_FFFF,
            conn_index=0,
            ble_rssi=rssi,
            flags=1,
            payload=payload,
        )
        self._handle_gateway_frame(
            frame,
            ("usb_serial", 0),
            pi_rx_ns,
            transport_name="microbit_radio_usb",
            gateway_metadata={
                "gateway_rx_ms": gateway_rx_ms,
                "sender_serial": sender_serial,
                "radio_rssi": rssi,
                "serial_device": self._device,
            },
        )

    def _record_parse_error(self, reason: str, line: str) -> None:
        self._parse_errors += 1
        logger.debug("Bad Radio gateway line (%s): %s", reason, line[:200])
