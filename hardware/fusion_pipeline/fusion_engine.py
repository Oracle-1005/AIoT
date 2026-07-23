"""Fusion engine with jitter buffer for micro:bit sample arrival latency.

Manages three time-sorted buffers (per the technical doc):
  - left_microbit_buffer
  - right_microbit_buffer
  - camera_frame_buffer

Plus a jitter buffer (deferred fusion window):
  Micro:bit BLE broadcast has no delivery guarantee — samples may arrive
  dozens to hundreds of milliseconds late due to BLE scan interval,
  Wi-Fi congestion, or UDP loss.  Rather than fusing immediately on each
  camera frame (where the corresponding micro:bit sample may not yet have
  arrived), the engine enqueues camera frames into a fixed-delay jitter
  buffer.  Each frame waits jitter_buffer_ms before fusion, giving late
  micro:bit samples time to land in the left/right buffers.

  Camera frame arrives ──→ enqueue(pending_frame)
    │                          arrival_ns + jitter_ms ≤ now ?
    │                            ├─ yes → pop, fuse, emit
    │                            └─ no  → keep waiting
    ▼
  micro:bit samples arrive ──→ push into left/right deque ──→ (pruned after 10s)

Control events bypass the fusion engine entirely (fast path).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field

from .schemas import (
    FUSED_FRAME_TEMPLATE,
    STATUS_TEMPLATE,
    DEFAULT_MAX_AGE_MS,
    DEFAULT_BUFFER_MAX_AGE_S,
)
from .time_aligner import TimeAligner

logger = logging.getLogger(__name__)

# Default jitter buffer delay — one full BLE sample period (200 ms) + 50 ms
# network/wifi headroom.  Empirically covers >95 % of late arrivals on a
# healthy BLE broadcast link.
DEFAULT_JITTER_BUFFER_MS = 250


@dataclass
class PendingFrame:
    """A camera frame waiting in the jitter buffer."""

    arrival_ns: int          # time.monotonic_ns() when the frame was enqueued
    camera_frame: dict       # dict from CameraAdapter.poll_frame()


class FusionEngine:
    """Camera-driven multi-sensor fusion with jitter-buffered time alignment.

    Wire-up in main.py::

        engine = FusionEngine(config)
        gateway_adapter = GatewayAdapter(
            ...,
            on_sensor_state=engine.push_microbit_sample,
        )
        # Main loop:
        for each camera frame:
            engine.enqueue_camera_frame(camera_frame)
        for fused in engine.drain_ready_frames():
            tcp_client.send(fused)

    Args:
        max_age_ms: Maximum age of micro:bit sample relative to camera
            target (default 120 ms).
        buffer_max_age_s: Maximum age of buffered samples before pruning
            (default 10 s).
        jitter_buffer_ms: Fixed delay each camera frame waits before
            fusion, allowing late micro:bit samples to arrive (default 250).
    """

    def __init__(
        self,
        *,
        max_age_ms: float = DEFAULT_MAX_AGE_MS,
        buffer_max_age_s: float = DEFAULT_BUFFER_MAX_AGE_S,
        jitter_buffer_ms: float = DEFAULT_JITTER_BUFFER_MS,
    ) -> None:
        # Three time-sorted micro:bit sample buffers (oldest at index 0)
        self._left_buffer: deque[dict] = deque()
        self._right_buffer: deque[dict] = deque()

        # Camera frame buffer (for pruning / stats, not for fusion directly)
        self._camera_buffer: deque[dict] = deque()

        self._buffer_max_age_ns = int(buffer_max_age_s * 1_000_000_000)

        # Jitter buffer — camera frames wait here before fusion
        self._jitter_ns = int(jitter_buffer_ms * 1_000_000)
        self._pending_frames: deque[PendingFrame] = deque()

        # Time aligner (shared, stateless — nearest-neighbour)
        self._aligner = TimeAligner(max_age_ms=max_age_ms)

        # Sequence counter
        self._fused_sequence: int = 0

        # Control event bypass queue (fast path)
        self._control_events: deque[dict] = deque()

        # Jitter buffer stats
        self._max_pending_depth: int = 0
        self._jitter_overflow_count: int = 0
        self._max_jitter_depth: int = 60  # hard cap to avoid unbounded growth

    # ── Public API ─────────────────────────────────────────────────────────

    def push_microbit_sample(self, sample) -> None:
        """Push a processed micro:bit sample into the appropriate buffer.

        Called by GatewayAdapter.on_sensor_state callback.  Samples stay in
        the buffer up to buffer_max_age_s (10 s), long enough to cover the
        jitter buffer delay + alignment window.

        Args:
            sample: MicrobitSample from gateway_adapter.
        """
        d = sample.to_dict()
        source = d["source"]

        if source == "left":
            self._left_buffer.append(d)
            self._prune(self._left_buffer)
        elif source == "right":
            self._right_buffer.append(d)
            self._prune(self._right_buffer)
        else:
            logger.debug("Unknown micro:bit source: %s", source)

    def enqueue_camera_frame(self, camera_frame: dict) -> None:
        """Enqueue a camera frame into the jitter buffer.

        The frame waits jitter_buffer_ms before being eligible for fusion,
        allowing late-arriving micro:bit samples to accumulate in the
        left/right buffers.

        Args:
            camera_frame: Dict from CameraAdapter.poll_frame() with keys:
                ts_ns, frame_id, width, height, hands, hands_detected,
                processing_latency_ms, clock_ready.
        """
        arrival_ns = time.monotonic_ns()

        # Hard cap: if the pending queue grows too large (consumer can't keep
        # up or system is overloaded), drop the oldest frame to bound latency.
        if len(self._pending_frames) >= self._max_jitter_depth:
            dropped = self._pending_frames.popleft()
            self._jitter_overflow_count += 1
            logger.warning(
                "Jitter buffer overflow (%d frames) — dropping oldest "
                "camera frame %s",
                self._max_jitter_depth,
                dropped.camera_frame.get("frame_id"),
            )

        self._pending_frames.append(PendingFrame(arrival_ns, camera_frame))
        current_depth = len(self._pending_frames)
        if current_depth > self._max_pending_depth:
            self._max_pending_depth = current_depth

    def drain_ready_frames(self) -> list[dict]:
        """Pop and fuse all jitter-buffer frames whose delay has expired.

        Returns:
            List of fused_frame dicts in arrival order (oldest first).
            May be empty if no frames have waited long enough.
        """
        now_ns = time.monotonic_ns()
        ready: list[dict] = []

        while self._pending_frames:
            head = self._pending_frames[0]
            waited_ns = now_ns - head.arrival_ns
            if waited_ns < self._jitter_ns:
                break  # Head of queue hasn't waited long enough yet

            self._pending_frames.popleft()
            fused = self._do_fuse(head.camera_frame)
            if fused is not None:
                ready.append(fused)

        return ready

    def push_control_event(self, event: dict) -> None:
        """Enqueue a control event for fast-path output (non-blocking).

        Called by GatewayAdapter.on_control_event callback.  Control events
        bypass the jitter buffer and fusion entirely — the main loop should
        drain and send them immediately.
        """
        self._control_events.append(event)

    def pop_control_events(self) -> list[dict]:
        """Drain and return all pending control events."""
        events = list(self._control_events)
        self._control_events.clear()
        return events

    def build_status(self, gateway_status: dict, camera_status: dict) -> dict:
        """Build a status message from gateway, camera, and jitter stats.

        Args:
            gateway_status: Dict from GatewayAdapter.get_status().
            camera_status: Dict from CameraAdapter.get_status().

        Returns:
            A status dict per the document schema.
        """
        status = deepcopy(STATUS_TEMPLATE)
        status["pi_timestamp_ns"] = time.monotonic_ns()
        status["microbits"] = {
            "left": {
                "connected": True,
                "age_ms": gateway_status.get("left_age_ms", 0.0),
                "rssi": gateway_status.get("left_rssi", 0),
                "missing_sample_count": gateway_status.get("left_missing_sample_count", 0),
            },
            "right": {
                "connected": True,
                "age_ms": gateway_status.get("right_age_ms", 0.0),
                "rssi": gateway_status.get("right_rssi", 0),
                "missing_sample_count": gateway_status.get("right_missing_sample_count", 0),
            },
        }
        status["camera"] = {
            "fps": camera_status.get("fps", 0.0),
            "hands_detected": camera_status.get("hands_detected", 0),
            "dropped_capture_frames": camera_status.get("dropped_capture_frames", 0),
            "clock_ready": camera_status.get("clock_ready", False),
        }
        # Jitter buffer stats
        status["jitter"] = {
            "configured_delay_ms": round(self._jitter_ns / 1_000_000.0, 1),
            "pending_frames": len(self._pending_frames),
            "max_pending_depth": self._max_pending_depth,
            "overflow_count": self._jitter_overflow_count,
        }
        return status

    # ── Internal: Fusion Logic ─────────────────────────────────────────────

    def _do_fuse(self, camera_frame: dict) -> dict | None:
        """Execute fusion for one camera frame (internal).

        Called by drain_ready_frames() after the jitter buffer delay has
        elapsed.  Uses the camera frame's **original** sensor timestamp as
        the fusion target, so time alignment is unaffected by the jitter
        buffer delay.
        """
        target_ns = camera_frame.get("ts_ns", 0)
        if target_ns == 0:
            logger.debug("Camera frame missing timestamp — skipping fusion")
            return None

        # ── Store camera frame ─────────────────────────────────────────
        self._camera_buffer.append(camera_frame)
        self._prune(self._camera_buffer)

        # ── Align micro:bit samples ────────────────────────────────────
        left_result = self._aligner.align(self._left_buffer, target_ns)
        right_result = self._aligner.align(self._right_buffer, target_ns)

        # ── Build fused_frame ──────────────────────────────────────────
        self._fused_sequence += 1

        left_entry = self._build_microbit_entry("left", left_result, target_ns)
        right_entry = self._build_microbit_entry("right", right_result, target_ns)
        microbits = [left_entry, right_entry]

        camera_entry = self._build_camera_entry(camera_frame, target_ns)
        quality = self._build_quality(left_result, right_result, camera_entry)

        fused = deepcopy(FUSED_FRAME_TEMPLATE)
        fused["fused_sequence"] = self._fused_sequence
        fused["pi_aligned_timestamp_ns"] = target_ns
        fused["microbits"] = microbits
        fused["camera"] = camera_entry
        fused["fusion_quality"] = quality

        return fused

    # ── Buffer helpers ─────────────────────────────────────────────────────

    def _prune(self, buffer: deque[dict]) -> int:
        """Remove samples older than buffer_max_age_s from the front."""
        if not buffer:
            return 0

        newest = buffer[-1].get("pi_rx_monotonic_ns", 0) or buffer[-1].get("ts_ns", 0)
        cutoff = newest - self._buffer_max_age_ns

        count = 0
        while buffer:
            ts = buffer[0].get("pi_rx_monotonic_ns", 0) or buffer[0].get("ts_ns", 0)
            if ts < cutoff:
                buffer.popleft()
                count += 1
            else:
                break
        return count

    # ── Entry builders ─────────────────────────────────────────────────────

    def _build_microbit_entry(self, hand: str, result, target_ns: int) -> dict:
        """Build a microbits[] entry for fused_frame."""
        if not result.available or result.sample is None:
            return {
                "hand": hand,
                "available": False,
                "sample_sequence": 0,
                "time_delta_ms": round(result.time_delta_ms, 1),
                "ax_mg": 0,
                "ay_mg": 0,
                "az_mg": 0,
                "pitch_deg": 0,
                "roll_deg": 0,
                "sequence_status": "",
                "missing_sample_count": 0,
            }

        s = result.sample
        sample_ts = s.get("pi_rx_monotonic_ns", 0)
        time_delta_ms = (sample_ts - target_ns) / 1_000_000.0

        return {
            "hand": hand,
            "available": True,
            "sample_sequence": s.get("sample_sequence", 0),
            "time_delta_ms": round(time_delta_ms, 1),
            "ax_mg": s.get("ax_mg", 0),
            "ay_mg": s.get("ay_mg", 0),
            "az_mg": s.get("az_mg", 0),
            "pitch_deg": s.get("pitch_deg", 0),
            "roll_deg": s.get("roll_deg", 0),
            "sequence_status": s.get("sequence_status", ""),
            "missing_sample_count": s.get("missing_sample_count", 0),
        }

    @staticmethod
    def _build_camera_entry(camera_frame: dict, target_ns: int) -> dict:
        """Build the camera entry for fused_frame."""
        return {
            "available": camera_frame.get("hands_detected", 0) > 0,
            "frame_sequence": camera_frame.get("frame_id", 0),
            "time_delta_ms": 0.0,  # Camera frame IS the time target
            "hands_detected": camera_frame.get("hands_detected", 0),
            "hands": camera_frame.get("hands", []),
        }

    @staticmethod
    def _build_quality(left_result, right_result, camera_entry: dict) -> dict:
        """Build the fusion_quality block."""
        max_delta = 0.0
        missing = []
        microbit_flags = []

        if not left_result.available:
            missing.append("left_microbit")
        else:
            max_delta = max(max_delta, abs(left_result.time_delta_ms))
            s = left_result.sample or {}
            if s.get("sequence_status") == "sequence_gap":
                microbit_flags.append("left_sequence_gap")

        if not right_result.available:
            missing.append("right_microbit")
        else:
            max_delta = max(max_delta, abs(right_result.time_delta_ms))
            s = right_result.sample or {}
            if s.get("sequence_status") == "sequence_gap":
                microbit_flags.append("right_sequence_gap")

        if not camera_entry["available"]:
            missing.append("camera")

        camera_flags: list[str] = []

        return {
            "max_time_delta_ms": round(max_delta, 1),
            "missing_sources": missing,
            "camera_quality_flags": camera_flags,
            "microbit_quality_flags": microbit_flags,
        }
