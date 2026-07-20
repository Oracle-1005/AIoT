"""Micro:bit BLE sensor implementation.

Wraps BleManager and ClockSync for a single micro:bit device, producing
MicrobitSample objects that flow into the fusion pipeline.

Data flow per packet:
  Raw BLE bytes → PacketParser → NoiseFilter → DataCleaner → ClockSync → MicrobitSample
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from sensors.base import SensorSource
from ble.ble_manager import BleManager
from ble.packet_parser import PacketParser, ParsedPacket
from ble.clock_sync import ClockSync
from fusion.cleaner import DataCleaner
from fusion.noise_filter import MicrobitNoiseFilter, FilteredIMUData

logger = logging.getLogger(__name__)


@dataclass
class MicrobitSample:
    """A fully processed micro:bit sample ready for fusion."""

    device_id: str
    hand: str
    sequence: int
    device_timestamp_ms: int
    pi_receive_timestamp_ns: int
    pi_aligned_timestamp_ns: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    pitch_deg: int
    roll_deg: int
    flags: int
    clock_ready: bool
    recent_loss_ratio: float = 0.0
    is_interpolated: bool = False

    def to_dict(self) -> dict:
        """Convert to a plain dict for the fusion pipeline."""
        return {
            "device_id": self.device_id,
            "hand": self.hand,
            "sequence": self.sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "pi_receive_timestamp_ns": self.pi_receive_timestamp_ns,
            "pi_aligned_timestamp_ns": self.pi_aligned_timestamp_ns,
            "ax_mg": self.ax_mg,
            "ay_mg": self.ay_mg,
            "az_mg": self.az_mg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "flags": self.flags,
            "clock_ready": self.clock_ready,
            "recent_loss_ratio": self.recent_loss_ratio,
            "is_interpolated": self.is_interpolated,
        }


class MicrobitSensor(SensorSource):
    """Single micro:bit BLE sensor.

    Handles BLE connection lifecycle, clock synchronization, packet parsing,
    and data cleaning for one micro:bit device.

    Args:
        device_id: Logical device ID (MB_LEFT, MB_RIGHT, etc.)
        hand: Hand label ("left", "right").
        address: BLE MAC address.
        ble_manager: Shared BleManager instance.
        on_sample: Callback(MicrobitSample) invoked for each valid sample.
        sync_config: Clock sync parameters.
        loss_window_size: Number of recent samples for loss ratio.
    """

    def __init__(
        self,
        device_id: str,
        hand: str,
        address: str,
        ble_manager: BleManager,
        on_sample: Callable[[MicrobitSample], None],
        sync_config: dict | None = None,
        loss_window_size: int = 100,
    ):
        self.device_id = device_id
        self.hand = hand
        self.address = address
        self._ble_manager = ble_manager
        self._on_sample = on_sample

        sync_config = sync_config or {}
        self._clock_sync = ClockSync(
            device_id=device_id,
            min_sync_points=sync_config.get("min_sync_points", 5),
            max_sync_points=sync_config.get("max_sync_points", 20),
            outlier_rtt_factor=sync_config.get("sync_outlier_rtt_factor", 2.0),
        )

        self._cleaner = DataCleaner(loss_window_size=loss_window_size)
        self._running = False
        self._resync_interval_s = sync_config.get("resync_interval_s", 15)
        self._resync_task: asyncio.Task | None = None
        self._sync_id_counter = 0

        # Noise filter: applied immediately after parsing
        noise_cfg = sync_config.get("noise_filter", {})
        self._noise_filter = MicrobitNoiseFilter(
            device_id=device_id,
            ema_alpha_accel=noise_cfg.get("ema_alpha_accel", 0.85),
            ema_alpha_orientation=noise_cfg.get("ema_alpha_orientation", 0.90),
            median_window=noise_cfg.get("median_window", 5),
            outlier_threshold_mg=noise_cfg.get("outlier_threshold_mg", 500.0),
        )

        # Pre-sync sample cache
        self._pre_sync_cache: deque[ParsedPacket] = deque(maxlen=500)

    # ---- SensorSource interface ----

    async def start(self) -> bool:
        """Connect BLE, run clock sync, and begin data flow.

        Returns:
            True if started successfully.
        """
        self._running = True

        # Perform initial clock synchronization
        logger.info("[%s] Starting initial clock sync (%d rounds)...",
                     self.device_id, self._clock_sync._min_points)
        initial_rounds = max(self._clock_sync._min_points, 15)
        await self.run_initial_sync(initial_rounds)

        if not self._clock_sync.clock_ready:
            logger.warning(
                "[%s] Initial sync incomplete (got %d/%d points). "
                "Will continue collecting sync points while running.",
                self.device_id,
                self._clock_sync.point_count,
                self._clock_sync._min_points,
            )

        # Send START command to begin data streaming
        await self._ble_manager.send_command(self.device_id, "START")
        logger.info("[%s] Sent START command.", self.device_id)

        # Start periodic re-sync
        self._resync_task = asyncio.create_task(self._periodic_resync())

        # Flush pre-sync cache into the pipeline
        self._flush_pre_sync_cache()

        self._running = True
        return True

    async def stop(self) -> None:
        """Stop data acquisition."""
        self._running = False

        if self._resync_task:
            self._resync_task.cancel()
            try:
                await self._resync_task
            except asyncio.CancelledError:
                pass

        await self._ble_manager.send_command(self.device_id, "STOP")
        logger.info("[%s] Stopped.", self.device_id)

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        """Return status dict for the status message."""
        connected = self._ble_manager.is_connected(self.device_id)
        rssi = self._ble_manager.get_rssi(self.device_id)

        return {
            "device_id": self.device_id,
            "hand": self.hand,
            "transport": "ble",
            "connected": connected,
            "rssi_dbm": rssi if rssi is not None else 0,
            "sample_rate_hz": 0,  # Will be computed by status monitor
            "recent_loss_ratio": self._cleaner.get_recent_loss_ratio(self.device_id),
            "clock_ready": self._clock_sync.clock_ready,
            "sync_rtt_ms": self._clock_sync.latest_rtt_ms or 0,
            "last_sample_age_ms": 0,  # Will be computed by status monitor
        }

    # ---- Clock sync ----

    async def run_initial_sync(self, num_rounds: int) -> bool:
        """Perform multiple SYNC/SYNC_ACK exchanges for initial sync.

        Args:
            num_rounds: Number of sync rounds to perform.

        Returns:
            True if clock_ready after sync.
        """
        for _ in range(num_rounds):
            if not self._running:
                break

            success = await self._do_one_sync_round()
            if not success:
                await asyncio.sleep(0.5)  # Brief pause before retry

            if self._clock_sync.clock_ready and self._clock_sync.point_count >= 10:
                # We have enough points, can stop early
                break

        logger.info(
            "[%s] Initial sync complete: %d points, ready=%s, a=%.6f, b=%d",
            self.device_id,
            self._clock_sync.point_count,
            self._clock_sync.clock_ready,
            self._clock_sync.slope,
            int(self._clock_sync.intercept_ns),
        )
        return self._clock_sync.clock_ready

    async def _do_one_sync_round(self) -> bool:
        """Execute one SYNC/SYNC_ACK round-trip.

        Returns:
            True if sync point was successfully recorded.
        """
        self._sync_id_counter += 1
        sync_id = self._sync_id_counter

        t0_ns = time.monotonic_ns()
        cmd = f"SYNC,{sync_id}"
        sent = await self._ble_manager.send_command(self.device_id, cmd)

        if not sent:
            logger.debug("[%s] SYNC command failed to send.", self.device_id)
            return False

        # Wait for the SYNC_ACK notification. The ACK arrives as a BLE notification
        # and is processed by the packet parser. For now, we use a simple wait.
        # In a real implementation, the SYNC_ACK would need to be captured from
        # the notification stream. For the initial sync, we use the round-trip
        # time as an approximation.
        #
        # The SYNC_ACK arrives as a text notification over the same UART RX
        # characteristic. Format: "SYNC_ACK,<sync_id>,<device_timestamp_ms>"
        # Since we set up raw binary notification, the ACK comes through our
        # binary handler. The micro:bit firmware should send the ACK as a
        # separate UART TX message.
        #
        # We wait up to 500ms for the ACK to arrive.
        await asyncio.sleep(0.2)  # Give BLE time to round-trip

        t2_ns = time.monotonic_ns()

        # Without capturing the actual device_timestamp_ms from the SYNC_ACK,
        # we can't create a proper sync point yet. The actual implementation
        # requires the SYNC_ACK data to be captured from the notification.
        #
        # For now, this is a placeholder that logs the RTT.
        rtt_ms = (t2_ns - t0_ns) / 1_000_000.0
        logger.debug("[%s] SYNC round RTT=%.1fms (need SYNC_ACK capture)", self.device_id, rtt_ms)

        return False  # Until SYNC_ACK capture is implemented

    async def _periodic_resync(self) -> None:
        """Background task: periodically re-sync clock to maintain accuracy."""
        while self._running:
            try:
                await asyncio.sleep(self._resync_interval_s)
                if not self._running:
                    break

                current_ns = time.monotonic_ns()
                if self._clock_sync.should_resync(current_ns, self._resync_interval_s):
                    logger.debug("[%s] Periodic re-sync triggered.", self.device_id)
                    await self._do_one_sync_round()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[%s] Re-sync error: %s", self.device_id, e)

    # ---- Packet handling ----

    def handle_raw_packet(self, raw_data: bytearray, pi_receive_ns: int) -> None:
        """Process a raw BLE notification.

        Called by BleManager's on_packet callback. Full processing chain:
          1. Parse binary packet
          2. Apply noise filter (EMA + outlier rejection)
          3. Detect packet loss via sequence gap
          4. Map device timestamp to Pi clock
          5. Build and emit MicrobitSample

        Args:
            raw_data: Raw bytearray from BLE notification.
            pi_receive_ns: Pi monotonic_ns when notification arrived.
        """
        # Step 1: Parse
        parsed = PacketParser.parse(
            self.device_id, self.hand, raw_data, pi_receive_ns
        )
        if parsed is None:
            return  # Parse error already logged

        # Step 2: Apply noise filter (NEW — EMA + median outlier rejection)
        filtered = self._noise_filter.filter(
            ax_mg=parsed.ax_mg,
            ay_mg=parsed.ay_mg,
            az_mg=parsed.az_mg,
            pitch_deg=parsed.pitch_deg,
            roll_deg=parsed.roll_deg,
        )

        # Step 3: Detect packet loss
        loss_report = self._cleaner.check_sample(
            self.device_id, parsed.sequence, pi_receive_ns
        )
        recent_loss_ratio = self._cleaner.get_recent_loss_ratio(self.device_id)

        # Step 4: Clock mapping
        clock_ready = self._clock_sync.clock_ready
        if clock_ready:
            aligned_ns = self._clock_sync.device_to_pi_ns(parsed.device_timestamp_ms)
        else:
            # Cache in pre-sync buffer (store parsed packet for later processing)
            self._pre_sync_cache.append(parsed)
            logger.debug(
                "[%s] Clock not ready, caching sample seq=%d. Cache size=%d",
                self.device_id,
                parsed.sequence,
                len(self._pre_sync_cache),
            )
            return

        # Step 5: Build sample (using noise-filtered values)
        sample = MicrobitSample(
            device_id=parsed.device_id,
            hand=parsed.hand,
            sequence=parsed.sequence,
            device_timestamp_ms=parsed.device_timestamp_ms,
            pi_receive_timestamp_ns=parsed.pi_receive_timestamp_ns,
            pi_aligned_timestamp_ns=aligned_ns,
            ax_mg=int(round(filtered.ax_mg)),
            ay_mg=int(round(filtered.ay_mg)),
            az_mg=int(round(filtered.az_mg)),
            pitch_deg=filtered.pitch_deg,
            roll_deg=filtered.roll_deg,
            flags=parsed.flags,
            clock_ready=clock_ready,
            recent_loss_ratio=recent_loss_ratio,
            is_interpolated=False,
        )

        # Step 5: Emit
        try:
            self._on_sample(sample)
        except Exception as e:
            logger.error("[%s] on_sample callback error: %s", self.device_id, e, exc_info=True)

        # Log loss if detected
        if loss_report is not None:
            logger.info(
                "[%s] Packet loss detected: seq %d->%d, lost %d, recent_ratio=%.3f",
                self.device_id,
                loss_report.expected_sequence,
                loss_report.received_sequence,
                loss_report.lost_count,
                recent_loss_ratio,
            )

    def _flush_pre_sync_cache(self) -> None:
        """Process all cached pre-sync samples now that clock is ready."""
        if not self._clock_sync.clock_ready:
            logger.debug("[%s] Cannot flush cache: clock still not ready.", self.device_id)
            return

        count = len(self._pre_sync_cache)
        if count == 0:
            return

        logger.info("[%s] Flushing %d cached pre-sync samples...", self.device_id, count)

        while self._pre_sync_cache:
            parsed = self._pre_sync_cache.popleft()
            aligned_ns = self._clock_sync.device_to_pi_ns(parsed.device_timestamp_ms)
            recent_loss_ratio = self._cleaner.get_recent_loss_ratio(self.device_id)

            sample = MicrobitSample(
                device_id=parsed.device_id,
                hand=parsed.hand,
                sequence=parsed.sequence,
                device_timestamp_ms=parsed.device_timestamp_ms,
                pi_receive_timestamp_ns=parsed.pi_receive_timestamp_ns,
                pi_aligned_timestamp_ns=aligned_ns,
                ax_mg=parsed.ax_mg,
                ay_mg=parsed.ay_mg,
                az_mg=parsed.az_mg,
                pitch_deg=parsed.pitch_deg,
                roll_deg=parsed.roll_deg,
                flags=parsed.flags,
                clock_ready=True,
                recent_loss_ratio=recent_loss_ratio,
                is_interpolated=False,
            )

            try:
                self._on_sample(sample)
            except Exception:
                pass

        logger.info("[%s] Cache flush complete.", self.device_id)

    @property
    def clock_ready(self) -> bool:
        return self._clock_sync.clock_ready
