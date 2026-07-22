"""BLE clock synchronization using SYNC/SYNC_ACK protocol and linear regression.

Implements an NTP-style bidirectional clock synchronization:
  - Pi sends SYNC,<id>, records t0
  - micro:bit receives, records device time m1
  - micro:bit sends SYNC_ACK,<id>,<m1>
  - Pi receives, records t2
  - pi_mid = (t0+t2)/2  estimates when m1 was valid on Pi clock
  - Linear regression: pi_ns = a * (device_ms * 1e6) + b
"""

import logging
import numpy as np
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SyncPoint:
    """One round-trip measurement for clock sync."""

    t0_ns: int              # Pi send time (monotonic_ns)
    device_ms: int          # micro:bit device_timestamp_ms from SYNC_ACK
    t2_ns: int              # Pi receive time (monotonic_ns)
    rtt_ms: float           # Round-trip time in ms: (t2_ns - t0_ns) / 1e6
    pi_mid_ns: int          # Best estimate: (t0_ns + t2_ns) // 2


class ClockSync:
    """Per-device clock synchronization manager.

    Converts micro:bit's input.runningTime() to Raspberry Pi monotonic_ns
    using a linear mapping fitted from RTT-filtered sync points.
    """

    def __init__(
        self,
        device_id: str,
        min_sync_points: int = 5,
        max_sync_points: int = 20,
        outlier_rtt_factor: float = 2.0,
    ):
        """Initialize clock sync for one device.

        Args:
            device_id: Logical device ID (MB_LEFT, MB_RIGHT, etc.)
            min_sync_points: Minimum retained points before clock_ready=true
            max_sync_points: Maximum points to retain (oldest pruned first)
            outlier_rtt_factor: RTT > factor * median_rtt is an outlier
        """
        self.device_id = device_id
        self._min_points = min_sync_points
        self._max_points = max_sync_points
        self._outlier_factor = outlier_rtt_factor

        self._sync_points: list[SyncPoint] = []
        self._a: float = 1.0      # Clock scale (drift coefficient)
        self._b: float = 0.0      # Clock offset in nanoseconds
        self._ready: bool = False
        self._last_sync_time_ns: int = 0

    # ---- Public properties ----

    @property
    def clock_ready(self) -> bool:
        """Whether enough sync points have been collected for reliable mapping."""
        return self._ready

    @property
    def slope(self) -> float:
        """Fitted clock scale (a). device_ns * a + b = pi_ns."""
        return self._a

    @property
    def intercept_ns(self) -> float:
        """Fitted clock offset (b) in nanoseconds."""
        return self._b

    @property
    def latest_rtt_ms(self) -> float | None:
        """RTT of the most recent sync point in milliseconds, or None."""
        if self._sync_points:
            return self._sync_points[-1].rtt_ms
        return None

    @property
    def point_count(self) -> int:
        """Number of retained sync points."""
        return len(self._sync_points)

    # ---- Public methods ----

    def add_sync_point(self, t0_ns: int, device_ms: int, t2_ns: int) -> SyncPoint:
        """Record one SYNC/SYNC_ACK round-trip.

        Args:
            t0_ns: Pi monotonic_ns when SYNC was sent
            device_ms: micro:bit runningTime() returned in SYNC_ACK
            t2_ns: Pi monotonic_ns when SYNC_ACK was received

        Returns:
            The created SyncPoint (may be pruned later).
        """
        rtt_ms = (t2_ns - t0_ns) / 1_000_000.0
        pi_mid_ns = (t0_ns + t2_ns) // 2

        sp = SyncPoint(
            t0_ns=t0_ns,
            device_ms=device_ms,
            t2_ns=t2_ns,
            rtt_ms=rtt_ms,
            pi_mid_ns=pi_mid_ns,
        )

        self._sync_points.append(sp)
        self._last_sync_time_ns = t2_ns

        # Prune and refit
        self._prune_outliers()
        self._prune_oldest()
        self._refit()

        logger.debug(
            "[%s] Sync point added: RTT=%.1fms, device_ms=%d, pi_mid=%dns, "
            "retained=%d, ready=%s",
            self.device_id,
            rtt_ms,
            device_ms,
            pi_mid_ns,
            len(self._sync_points),
            self._ready,
        )

        return sp

    def device_to_pi_ns(self, device_timestamp_ms: int) -> int:
        """Convert a micro:bit runningTime() value to Pi monotonic_ns.

        Uses the fitted linear mapping: pi_ns = a * (device_ms * 1e6) + b

        If clock is not ready, falls back to the raw device_timestamp_ms
        converted at the nominal 1ms/1_000_000ns rate with offset b=0.
        Callers should check clock_ready to decide whether to trust the result.

        Args:
            device_timestamp_ms: micro:bit input.runningTime() value

        Returns:
            Estimated Pi monotonic_ns corresponding to the device timestamp.
        """
        if self._ready:
            return int(self._a * (device_timestamp_ms * 1_000_000) + self._b)
        else:
            # Fallback: assume 1:1 clock with no offset
            return device_timestamp_ms * 1_000_000

    def should_resync(self, current_time_ns: int, interval_s: float = 15.0) -> bool:
        """Check if periodic re-sync is due.

        Args:
            current_time_ns: Current Pi monotonic_ns
            interval_s: Re-sync interval in seconds

        Returns:
            True if (current - last_sync) > interval.
        """
        if self._last_sync_time_ns == 0:
            return True
        return (current_time_ns - self._last_sync_time_ns) > (interval_s * 1_000_000_000)

    def reset(self) -> None:
        """Clear all sync points. Called on BLE disconnect/reconnect."""
        self._sync_points.clear()
        self._a = 1.0
        self._b = 0.0
        self._ready = False
        self._last_sync_time_ns = 0
        logger.info("[%s] Clock sync reset.", self.device_id)

    # ---- Internal methods ----

    def _prune_outliers(self) -> None:
        """Remove sync points with RTT > outlier_factor * median RTT."""
        if len(self._sync_points) < 3:
            return  # Not enough data to identify outliers

        rtts = [sp.rtt_ms for sp in self._sync_points]
        median_rtt = float(np.median(rtts))
        threshold = self._outlier_factor * median_rtt

        before = len(self._sync_points)
        self._sync_points = [sp for sp in self._sync_points if sp.rtt_ms <= threshold]
        removed = before - len(self._sync_points)

        if removed > 0:
            logger.debug(
                "[%s] Pruned %d outlier sync point(s) (median RTT=%.1fms, threshold=%.1fms)",
                self.device_id,
                removed,
                median_rtt,
                threshold,
            )

    def _prune_oldest(self) -> None:
        """Keep at most max_sync_points, removing oldest first."""
        while len(self._sync_points) > self._max_points:
            removed = self._sync_points.pop(0)
            logger.debug("[%s] Pruned oldest sync point (RTT=%.1fms)", self.device_id, removed.rtt_ms)

    def _refit(self) -> bool:
        """Fit linear regression: pi_mid_ns = a * (device_ms * 1e6) + b.

        Uses numpy.polyfit (degree 1). Sets clock_ready if enough points retained.

        Returns:
            True if fit succeeded.
        """
        if len(self._sync_points) < 2:
            self._ready = False
            return False

        try:
            x = np.array([sp.device_ms * 1_000_000 for sp in self._sync_points], dtype=np.float64)
            y = np.array([sp.pi_mid_ns for sp in self._sync_points], dtype=np.float64)

            # polyfit returns [slope, intercept] for degree 1
            coeffs = np.polyfit(x, y, 1)
            self._a = float(coeffs[0])
            self._b = float(coeffs[1])

            self._ready = len(self._sync_points) >= self._min_points

            logger.debug(
                "[%s] Refit: a=%.6f, b=%d, points=%d, ready=%s",
                self.device_id,
                self._a,
                int(self._b),
                len(self._sync_points),
                self._ready,
            )
            return True

        except Exception as e:
            logger.warning("[%s] Linear fit failed: %s", self.device_id, e)
            self._ready = False
            return False
