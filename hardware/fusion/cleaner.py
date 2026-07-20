"""Packet loss detection and gap interpolation for BLE sensor data.

Detects lost packets via sequence number gap analysis on a per-device basis.
Supports linear interpolation for small gaps and provides sliding-window
loss ratio statistics.
"""

import logging
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LossReport:
    """Report of detected packet loss."""

    device_id: str
    expected_sequence: int
    received_sequence: int
    lost_count: int
    timestamp_ns: int
    total_received: int
    total_lost: int
    recent_loss_ratio: float


class DataCleaner:
    """Detects BLE packet loss and provides gap interpolation.

    Tracks sequence numbers per device, detects gaps (including uint16
    wraparound handling), maintains a sliding window of receive/loss history,
    and computes recent loss ratio.

    Args:
        loss_window_size: Number of recent sequence events to track for
            loss ratio calculation.
        max_gap_interpolate: Maximum number of consecutive missing samples
            to fill via linear interpolation. Larger gaps are left as is
            (marked invalid by the fusion engine).
    """

    def __init__(
        self,
        loss_window_size: int = 100,
        max_gap_interpolate: int = 3,
    ):
        self._loss_window_size = loss_window_size
        self._max_gap_interpolate = max_gap_interpolate

        # Per-device state
        self._last_seq: dict[str, int | None] = {}
        self._loss_history: dict[str, deque[bool]] = {}     # True=got, False=lost
        self._total_received: dict[str, int] = {}
        self._total_lost: dict[str, int] = {}

    def check_sample(
        self, device_id: str, sequence: int, timestamp_ns: int
    ) -> LossReport | None:
        """Check a sample's sequence number for gaps.

        Call this for every received BLE packet. It compares the sequence
        number to the expected next value and detects loss.

        Args:
            device_id: Logical device ID.
            sequence: The sequence number from the received packet (uint16).
            timestamp_ns: Pi receive timestamp for the sample.

        Returns:
            LossReport if loss was detected, None otherwise.
        """
        # Initialize state for new device
        if device_id not in self._last_seq or self._last_seq[device_id] is None:
            self._last_seq[device_id] = sequence
            self._loss_history.setdefault(device_id, deque(maxlen=self._loss_window_size))
            self._loss_history[device_id].append(True)
            self._total_received.setdefault(device_id, 0)
            self._total_received[device_id] += 1
            self._total_lost.setdefault(device_id, 0)
            return None

        last_seq = self._last_seq[device_id]
        expected = (last_seq + 1) & 0xFFFF

        if sequence == expected:
            # Normal case: no loss
            self._last_seq[device_id] = sequence
            self._loss_history[device_id].append(True)
            self._total_received[device_id] += 1
            return None

        # Calculate gap size, handling uint16 wraparound
        lost = (sequence - expected) & 0xFFFF

        # If the gap is larger than half the uint16 space, it's likely
        # a wraparound without actual loss, or a device reset.
        if lost > 32768:
            logger.debug(
                "[%s] Large seq gap (%d), treating as wraparound/reset. "
                "seq: %d -> %d",
                device_id,
                lost,
                last_seq,
                sequence,
            )
            self._last_seq[device_id] = sequence
            self._loss_history[device_id].append(True)
            self._total_received[device_id] += 1
            return None

        # Loss detected
        for _ in range(lost):
            self._loss_history[device_id].append(False)

        self._loss_history[device_id].append(True)  # Current sample received
        self._total_received[device_id] += 1
        self._total_lost[device_id] += lost
        self._last_seq[device_id] = sequence

        recent_loss_ratio = self.get_recent_loss_ratio(device_id)

        return LossReport(
            device_id=device_id,
            expected_sequence=expected,
            received_sequence=sequence,
            lost_count=lost,
            timestamp_ns=timestamp_ns,
            total_received=self._total_received[device_id],
            total_lost=self._total_lost[device_id],
            recent_loss_ratio=recent_loss_ratio,
        )

    def get_recent_loss_ratio(self, device_id: str) -> float:
        """Return the ratio of lost samples in the recent window.

        Args:
            device_id: Logical device ID.

        Returns:
            Float in [0, 1] representing loss/total ratio.
        """
        history = self._loss_history.get(device_id)
        if history is None or len(history) == 0:
            return 0.0

        lost_count = sum(1 for received in history if not received)
        return lost_count / len(history)

    def interpolate_gap(
        self,
        sample_before: dict,
        sample_after: dict,
        target_count: int,
    ) -> list[dict]:
        """Linearly interpolate missing samples between two known samples.

        Only called when target_count <= max_gap_interpolate.

        Args:
            sample_before: Dict with sensor values before the gap.
            sample_after: Dict with sensor values after the gap.
            target_count: Number of missing samples to generate.

        Returns:
            List of interpolated sample dicts, each marked is_interpolated=True.
        """
        if target_count <= 0 or target_count > self._max_gap_interpolate:
            return []

        result = []
        total_steps = target_count + 1

        # Fields to interpolate
        int_fields = ["ax_mg", "ay_mg", "az_mg", "pitch_deg", "roll_deg"]
        int_timestamp_fields = [
            "device_timestamp_ms",
            "pi_aligned_timestamp_ns",
        ]

        for k in range(1, total_steps):
            ratio = k / total_steps

            sample = {
                "device_id": sample_before.get("device_id", ""),
                "hand": sample_before.get("hand", ""),
                "sequence": sample_before.get("sequence", 0) + k,
                "flags": sample_before.get("flags", 0),
                "is_interpolated": True,
                "clock_ready": sample_before.get("clock_ready", False),
                "recent_loss_ratio": sample_before.get("recent_loss_ratio", 0),
            }

            # Interpolate sensor values
            for field in int_fields:
                v0 = sample_before.get(field, 0)
                v1 = sample_after.get(field, 0)
                if isinstance(v0, (int, float)) and isinstance(v1, (int, float)):
                    sample[field] = v0 + ratio * (v1 - v0)
                else:
                    sample[field] = v0

            # Interpolate timestamps
            for field in int_timestamp_fields:
                v0 = sample_before.get(field, 0)
                v1 = sample_after.get(field, 0)
                if isinstance(v0, (int, float)) and isinstance(v1, (int, float)):
                    sample[field] = int(v0 + ratio * (v1 - v0))
                else:
                    sample[field] = v0

            # pi_receive_timestamp_ns is not interpolated (it's a receive time)
            sample["pi_receive_timestamp_ns"] = sample_before.get("pi_receive_timestamp_ns", 0)

            result.append(sample)

        return result

    def reset_device(self, device_id: str) -> None:
        """Reset tracking state for a device (called on BLE reconnect).

        Args:
            device_id: Logical device ID to reset.
        """
        self._last_seq.pop(device_id, None)
        self._loss_history.pop(device_id, None)
        self._total_received.pop(device_id, None)
        self._total_lost.pop(device_id, None)
        logger.info("[%s] Data cleaner state reset.", device_id)

    def get_total_stats(self, device_id: str) -> dict:
        """Return total receive/loss stats for a device.

        Args:
            device_id: Logical device ID.

        Returns:
            Dict with total_received, total_lost, total_loss_ratio.
        """
        received = self._total_received.get(device_id, 0)
        lost = self._total_lost.get(device_id, 0)
        total = received + lost

        return {
            "total_received": received,
            "total_lost": lost,
            "total_loss_ratio": lost / total if total > 0 else 0.0,
        }
