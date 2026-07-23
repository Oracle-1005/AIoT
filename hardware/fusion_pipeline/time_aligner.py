"""Nearest-neighbor time alignment for micro:bit samples to camera timestamps.

Initial strategy per the technical document:
  - Find the micro:bit sample closest to the camera target timestamp
  - Accept if within max_age_ms (default 120 ms)
  - Mark available=false if no sample within threshold

Later upgrade path: linear interpolation between two bracketing samples.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AlignResult:
    """Result of nearest-neighbor alignment for one hand."""

    available: bool
    sample: dict | None = None
    time_delta_ms: float = 0.0


class TimeAligner:
    """Finds the nearest micro:bit sample to a target timestamp.

    Searches a deque of time-sorted sample dicts for the entry whose
    timestamp is closest to the target.  Applies a maximum-age threshold:
    if the nearest sample is older than max_age_ms, the result is
    available=False.

    Args:
        max_age_ms: Maximum allowed absolute time difference between the
            target timestamp and the nearest sample.  Default 120 ms.
    """

    def __init__(self, max_age_ms: float = 120.0) -> None:
        self._max_age_ns = int(max_age_ms * 1_000_000)

    def align(
        self, buffer: deque[dict], target_ns: int, ts_key: str = "pi_rx_monotonic_ns"
    ) -> AlignResult:
        """Find nearest sample in *buffer* to *target_ns*.

        Args:
            buffer: Time-sorted deque of sample dicts (oldest at index 0).
            target_ns: Fusion target timestamp in Pi monotonic nanoseconds.
            ts_key: Dict key holding the sample's Pi timestamp.

        Returns:
            AlignResult with available=True and the best-matching sample
            if one exists within the age threshold.
        """
        if not buffer:
            return AlignResult(available=False)

        best_sample: dict | None = None
        best_delta_ns: int = 2**63  # large sentinel

        for sample in buffer:
            ts = sample.get(ts_key, 0)
            delta_ns = abs(ts - target_ns)
            if delta_ns < best_delta_ns:
                best_delta_ns = delta_ns
                best_sample = sample

        if best_sample is None:
            return AlignResult(available=False)

        delta_ms = best_delta_ns / 1_000_000.0

        if best_delta_ns > self._max_age_ns:
            logger.debug(
                "Nearest sample delta %.1f ms exceeds threshold %.1f ms",
                delta_ms,
                self._max_age_ns / 1_000_000.0,
            )
            return AlignResult(available=False, sample=best_sample, time_delta_ms=delta_ms)

        return AlignResult(available=True, sample=best_sample, time_delta_ms=delta_ms)
