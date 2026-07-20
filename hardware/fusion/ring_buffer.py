"""Time-sorted ring buffer for sensor samples.

Uses collections.deque with bisect-based insertion for maintaining
time-ordered samples from multiple sensor sources.
"""

import bisect
import logging
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TimestampedSample:
    """A single sample with unified timestamp for the fusion pipeline.

    All sensor data is normalized to this format before entering the ring buffer.
    The timestamp_ns is the pi_aligned_timestamp_ns (for BLE) or
    sensor_timestamp_ns (for camera).
    """

    timestamp_ns: int
    source: str             # "microbit_left", "microbit_right", "camera"
    device_id: str          # MB_LEFT, MB_RIGHT, or "camera"
    data: dict              # The actual sample data


class RingBuffer:
    """Bounded, time-sorted sample buffer with O(1) append on chronological data.

    Since BLE notifications and camera frames arrive in approximate chronological
    order, we optimize for the common case of appending to the end. For out-of-order
    arrivals, we fall back to bisect-based insertion.

    Args:
        maxlen: Maximum number of samples across all sources.
        max_age_ns: Maximum age of samples in nanoseconds. Older samples are
                    pruned on each push.
    """

    def __init__(self, maxlen: int = 500, max_age_ns: int = 10_000_000_000):
        self._buffer: deque[TimestampedSample] = deque(maxlen=maxlen)
        self._max_age_ns = max_age_ns

    def push(self, sample: TimestampedSample) -> None:
        """Insert a sample in time-sorted order.

        Optimized for mostly-chronological arrival: first tries to append
        (if timestamp >= last element), then falls back to bisect insert.

        Args:
            sample: The timestamped sample to insert.
        """
        # Prune expired samples first
        cutoff = sample.timestamp_ns - self._max_age_ns
        self.prune(cutoff)

        if not self._buffer:
            self._buffer.append(sample)
            return

        # Fast path: sample is newer than the last element
        if sample.timestamp_ns >= self._buffer[-1].timestamp_ns:
            self._buffer.append(sample)
            return

        # Slow path: insert in correct position via bisect
        # Build a list of timestamps for bisect
        timestamps = [s.timestamp_ns for s in self._buffer]
        idx = bisect.bisect_left(timestamps, sample.timestamp_ns)
        # deque doesn't support insertion at arbitrary position efficiently,
        # so we rebuild from the list
        as_list = list(self._buffer)
        as_list.insert(idx, sample)
        self._buffer = deque(as_list, maxlen=self._buffer.maxlen)

    def get_bracket(
        self, target_ns: int, device_id: str
    ) -> tuple["TimestampedSample | None", "TimestampedSample | None"]:
        """Find bracketing samples for a target timestamp.

        If target lies between two samples, returns (t0, t1) where
        t0 <= target_ns <= t1. If target is beyond the latest sample
        but within a reasonable extrapolation range, uses the two most
        recent samples as the bracket.

        Args:
            target_ns: The target timestamp (e.g., camera sensor timestamp).
            device_id: Device ID to filter by.

        Returns:
            Tuple of (t0_sample, t1_sample) where t0 <= target_ns.
            If target <= latest sample, t1 >= target_ns.
            If target > latest sample, t1 = latest (extrapolation).
            Either can be None if no suitable sample exists.
        """
        matching = [s for s in self._buffer if s.device_id == device_id]
        if len(matching) < 2:
            return (None, None)

        t0_sample = None
        t1_sample = None

        for s in matching:
            if s.timestamp_ns <= target_ns:
                # Track the closest sample before (or at) target
                if t0_sample is None or s.timestamp_ns > t0_sample.timestamp_ns:
                    t0_sample = s
            if s.timestamp_ns >= target_ns:
                # First sample at or after target is t1
                if t1_sample is None or s.timestamp_ns < t1_sample.timestamp_ns:
                    t1_sample = s
                break  # Time-sorted: first >= target is t1

        # ── Fallback: target beyond latest sample ─────────────────
        if t1_sample is None and t0_sample is not None:
            # Use the two most recent samples for extrapolation.
            # t0 = second-to-last, t1 = last sample
            if len(matching) >= 2:
                t1_sample = matching[-1]       # Latest sample
                t0_sample = matching[-2]       # Second-to-latest sample

        return (t0_sample, t1_sample)

    def get_samples_in_window(
        self, start_ns: int, end_ns: int, source: str | None = None
    ) -> list["TimestampedSample"]:
        """Return all samples within [start_ns, end_ns], optionally filtered by source.

        Args:
            start_ns: Start of the time window (inclusive).
            end_ns: End of the time window (inclusive).
            source: Optional source filter (e.g., "microbit_left").

        Returns:
            List of matching samples in time order.
        """
        result = []
        for s in self._buffer:
            if start_ns <= s.timestamp_ns <= end_ns:
                if source is None or s.source == source:
                    result.append(s)
        return result

    def prune(self, before_ns: int) -> int:
        """Remove all samples with timestamp_ns < before_ns.

        Args:
            before_ns: Cutoff timestamp. Samples older than this are removed.

        Returns:
            Number of samples pruned.
        """
        count = 0
        while self._buffer and self._buffer[0].timestamp_ns < before_ns:
            self._buffer.popleft()
            count += 1
        return count

    def latest_timestamp(self, device_id: str | None = None) -> int | None:
        """Return the most recent timestamp for given device_id.

        Args:
            device_id: Device to query. If None, returns global latest.

        Returns:
            The latest timestamp_ns, or None if no samples exist.
        """
        if device_id is not None:
            for s in reversed(self._buffer):
                if s.device_id == device_id:
                    return s.timestamp_ns
            return None

        if self._buffer:
            return self._buffer[-1].timestamp_ns
        return None

    def count(self, device_id: str | None = None) -> int:
        """Return number of samples, optionally filtered by device_id."""
        if device_id is None:
            return len(self._buffer)
        return sum(1 for s in self._buffer if s.device_id == device_id)

    def clear(self) -> None:
        """Remove all samples."""
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)
