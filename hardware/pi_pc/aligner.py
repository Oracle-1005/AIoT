"""Time alignment: interpolate micro:bit samples to camera target timestamps.

Aligns BLE sensor data to camera SensorTimestamp via bracket search and
linear interpolation. Produces aligned data dicts with validity flags.
"""

import logging
from dataclasses import dataclass, field

from .ring_buffer import RingBuffer

logger = logging.getLogger(__name__)


@dataclass
class AlignResult:
    """Result of time-aligning one sensor source to a target timestamp."""

    valid: bool
    reason: str | None = None
    nearest_sample_error_ms: float = 0.0
    bracket_span_ms: float = 0.0
    interpolated: dict | None = None
    bracket_samples: list = field(default_factory=list)


class TimeAligner:
    """Aligns micro:bit samples to a target timestamp via linear interpolation.

    For a given target timestamp (camera SensorTimestamp), finds the
    nearest bracketing BLE samples and linearly interpolates the sensor
    values (ax, ay, az, pitch, roll).

    Args:
        max_bracket_span_ms: Maximum allowed time between bracketing samples.
            If the span exceeds this, the alignment is marked invalid.
        max_sample_age_ms: Maximum allowed age of the nearest sample relative
            to the target. Older samples are considered stale.
    """

    INTERPOLATED_FIELDS = ["ax_mg", "ay_mg", "az_mg", "pitch_deg", "roll_deg"]

    def __init__(
        self,
        max_bracket_span_ms: float = 100.0,
        max_sample_age_ms: float = 120.0,
        timestamp_alignment_tolerance_ms: float = 50.0,
    ):
        self._max_bracket_ns = int(max_bracket_span_ms * 1_000_000)
        self._max_age_ns = int(max_sample_age_ms * 1_000_000)
        self._max_error_ns = int(timestamp_alignment_tolerance_ms * 1_000_000)

    def align(
        self,
        device_id: str,
        target_ns: int,
        ring_buffer: RingBuffer,
        require_clock_ready: bool = True,
    ) -> AlignResult:
        """Align micro:bit samples to a target camera timestamp.

        Args:
            device_id: Logical device ID (MB_LEFT, MB_RIGHT, etc.)
            target_ns: Target timestamp (camera SensorTimestamp) in Pi monotonic_ns.
            ring_buffer: The global time-sorted ring buffer.
            require_clock_ready: If True, samples with clock_ready=False are
                considered invalid.

        Returns:
            AlignResult with validity status and interpolated data.
        """
        t0_sample, t1_sample = ring_buffer.get_bracket(target_ns, device_id)

        # ---- Check 1: Bracket existence ----
        if t0_sample is None or t1_sample is None:
            reason = "no_bracket"
            return AlignResult(
                valid=False,
                reason=reason,
                bracket_samples=[s for s in (t0_sample, t1_sample) if s is not None],
            )

        t0_ns = t0_sample.timestamp_ns
        t1_ns = t1_sample.timestamp_ns

        # ---- Check 2: Clock readiness ----
        if require_clock_ready:
            t0_clock_ready = t0_sample.data.get("clock_ready", False)
            t1_clock_ready = t1_sample.data.get("clock_ready", False)
            if not t0_clock_ready or not t1_clock_ready:
                return AlignResult(
                    valid=False,
                    reason="clock_not_ready",
                    bracket_samples=[t0_sample, t1_sample],
                )

        # ---- Check 3: Bracket span too wide ----
        bracket_span_ns = t1_ns - t0_ns
        bracket_span_ms = bracket_span_ns / 1_000_000.0
        if bracket_span_ns > self._max_bracket_ns:
            return AlignResult(
                valid=False,
                reason="bracket_too_wide",
                bracket_span_ms=bracket_span_ms,
                bracket_samples=[t0_sample, t1_sample],
            )

        # ---- Check 4: Sample too old ----
        # The age of t0_sample relative to target
        sample_age_ns = target_ns - t0_ns
        if sample_age_ns > self._max_age_ns:
            return AlignResult(
                valid=False,
                reason="ble_sample_too_old",
                bracket_span_ms=bracket_span_ms,
                bracket_samples=[t0_sample, t1_sample],
            )

        # ---- Check 5: Nearest sample error (for quality metric, not a hard fail) ----
        nearest_error_ns = min(target_ns - t0_ns, t1_ns - target_ns)
        nearest_error_ms = nearest_error_ns / 1_000_000.0

        if nearest_error_ns > self._max_error_ns:
            logger.debug(
                "[%s] Sync error %.1fms exceeds tolerance %.1fms",
                device_id,
                nearest_error_ms,
                self._max_error_ns / 1_000_000.0,
            )

        # ---- Interpolation ----
        if bracket_span_ns == 0:
            # Exact match (unlikely but handle it)
            ratio = 0.0
        else:
            ratio = (target_ns - t0_ns) / bracket_span_ns

        interpolated = self._linear_interpolate(
            t0_sample.data, t1_sample.data, ratio
        )

        return AlignResult(
            valid=True,
            nearest_sample_error_ms=nearest_error_ms,
            bracket_span_ms=bracket_span_ms,
            interpolated=interpolated,
            bracket_samples=[t0_sample, t1_sample],
        )

    def _linear_interpolate(
        self, d0: dict, d1: dict, ratio: float
    ) -> dict:
        """Linearly interpolate sensor values between two samples.

        x(t) = x0 + ratio * (x1 - x0)

        Args:
            d0: Earlier sample data dict.
            d1: Later sample data dict.
            ratio: Interpolation ratio in [0, 1].

        Returns:
            Dict with interpolated values for each field.
        """
        result = {}
        for field in self.INTERPOLATED_FIELDS:
            v0 = d0.get(field, 0)
            v1 = d1.get(field, 0)
            if isinstance(v0, (int, float)) and isinstance(v1, (int, float)):
                result[field] = v0 + ratio * (v1 - v0)
            else:
                result[field] = 0

        result["_interpolated"] = True
        result["_interpolation_ratio"] = ratio
        return result
