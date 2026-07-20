"""Fusion engine: orchestrates sensor data into fused_frame messages.

The FusionEngine receives samples from all sensor sources (BLE micro:bits
and camera), buffers them in a time-sorted ring buffer, aligns BLE data to
camera timestamps, and produces fused_frame dicts.
"""

import logging
import time
from collections import deque

from .ring_buffer import RingBuffer, TimestampedSample
from .aligner import TimeAligner, AlignResult

logger = logging.getLogger(__name__)


class FusionEngine:
    """Central orchestrator for multi-sensor fusion.

    Receives samples from sensors, buffers them, and fuses them into
    fused_frame messages aligned to camera timestamps.

    Args:
        config: Fusion configuration dict (from config.yaml fusion section).
    """

    def __init__(self, config: dict):
        buffer_maxlen = config.get("buffer_maxlen", 500)
        buffer_max_age_s = config.get("buffer_max_age_s", 10.0)

        self._ring_buffer = RingBuffer(
            maxlen=buffer_maxlen,
            max_age_ns=int(buffer_max_age_s * 1_000_000_000),
        )

        self._aligner = TimeAligner(
            max_bracket_span_ms=config.get("max_bracket_span_ms", 100),
            max_sample_age_ms=config.get("max_sample_age_ms", 120),
            timestamp_alignment_tolerance_ms=config.get(
                "timestamp_alignment_tolerance_ms", 50
            ),
        )

        # Per-device tracking
        self._device_ids: list[str] = []
        self._device_hands: dict[str, str] = {}  # device_id -> hand

        # Camera state
        self._latest_camera_frame: dict | None = None
        self._frame_sequence: int = 0

        # Callback for fused frames
        self._on_fused_frame = None

    # ---- Public API ----

    def register_device(self, device_id: str, hand: str) -> None:
        """Register a micro:bit device for fusion.

        Args:
            device_id: Logical device ID (MB_LEFT, etc.)
            hand: Hand label ("left" or "right").
        """
        if device_id not in self._device_ids:
            self._device_ids.append(device_id)
        self._device_hands[device_id] = hand
        logger.info("Registered device: %s (hand=%s)", device_id, hand)

    def set_fused_frame_callback(self, callback) -> None:
        """Set callback for fused_frame dicts.

        Args:
            callback: Callable(fused_frame_dict) called when a frame is fused.
        """
        self._on_fused_frame = callback

    def on_microbit_sample(self, sample_dict: dict) -> None:
        """Handle an incoming micro:bit sample.

        Called after packet parsing, cleaning, and clock mapping.

        Args:
            sample_dict: Dict with keys: device_id, hand, sequence,
                device_timestamp_ms, pi_receive_timestamp_ns,
                pi_aligned_timestamp_ns, ax_mg, ay_mg, az_mg,
                pitch_deg, roll_deg, flags, clock_ready, etc.
        """
        device_id = sample_dict["device_id"]
        timestamp_ns = sample_dict.get("pi_aligned_timestamp_ns", 0)
        hand = sample_dict.get("hand", "unknown")

        source = f"microbit_{hand}"

        ts_sample = TimestampedSample(
            timestamp_ns=timestamp_ns,
            source=source,
            device_id=device_id,
            data=sample_dict,
        )

        self._ring_buffer.push(ts_sample)

    def on_camera_frame(self, camera_dict: dict) -> dict | None:
        """Handle an incoming camera frame and trigger fusion.

        This is the main entry point for the fusion pipeline. When a camera
        frame arrives, it becomes the fusion target, and all BLE data is
        interpolated to its timestamp.

        Args:
            camera_dict: Dict with keys: frame_id, sensor_timestamp_ns,
                width, height, fps, hands (list of hand dicts),
                processing_latency_ms.

        Returns:
            A fused_frame dict if fusion was successful, or None if
            no camera data is available.
        """
        device_id = "camera"
        target_ns = camera_dict.get("sensor_timestamp_ns", 0)

        # Store camera frame in ring buffer
        ts_sample = TimestampedSample(
            timestamp_ns=target_ns,
            source="camera",
            device_id=device_id,
            data=camera_dict,
        )
        self._ring_buffer.push(ts_sample)
        self._latest_camera_frame = camera_dict

        # Fuse with micro:bit data
        fused = self._fuse(target_ns, camera_dict)

        if fused is not None and self._on_fused_frame is not None:
            self._on_fused_frame(fused)

        return fused

    def get_status(self) -> dict:
        """Return current fusion engine status.

        Returns:
            Dict with buffer stats and device statuses.
        """
        return {
            "buffer_total_samples": len(self._ring_buffer),
            "buffer_samples_by_device": {
                did: self._ring_buffer.count(did) for did in self._device_ids
            },
            "buffer_camera_samples": self._ring_buffer.count("camera"),
            "registered_devices": self._device_ids,
        }

    # ---- Internal ----

    def _fuse(self, target_ns: int, camera_dict: dict) -> dict:
        """Build a fused_frame dict for the given camera target timestamp.

        Args:
            target_ns: Camera SensorTimestamp as Pi monotonic_ns.
            camera_dict: The camera frame data.

        Returns:
            A fused_frame dict following the document schema.
        """
        # Build microbits array
        microbits_data = []
        left_valid = False
        right_valid = False

        for device_id in self._device_ids:
            hand = self._device_hands.get(device_id, "unknown")
            align_result = self._aligner.align(device_id, target_ns, self._ring_buffer)

            device_entry = self._build_microbit_entry(device_id, hand, align_result)

            if align_result.valid:
                if hand == "left":
                    left_valid = True
                elif hand == "right":
                    right_valid = True

            microbits_data.append(device_entry)

        # Camera hands data
        camera_hands = camera_dict.get("hands", [])
        camera_valid = len(camera_hands) > 0 and any(
            h.get("valid", True) for h in camera_hands
        )

        # Fusion validity
        fusion_valid = camera_valid and (left_valid or right_valid)

        # Build cross-modal features (basic for now)
        cross_modal = self._compute_cross_modal(
            camera_hands, microbits_data, camera_valid, left_valid, right_valid
        )

        # Assemble fused_frame
        self._frame_sequence += 1
        fused = {
            "message_type": "fused_frame",
            "timestamps": {
                "fusion_target_timestamp_ns": target_ns,
            },
            "camera": {
                "source": "camera",
                "frame_id": camera_dict.get("frame_id", 0),
                "sensor_timestamp_ns": target_ns,
                "width": camera_dict.get("width", 640),
                "height": camera_dict.get("height", 480),
                "configured_fps": camera_dict.get("fps", 30),
                "processing_latency_ms": camera_dict.get("processing_latency_ms", 0),
                "hands": camera_hands,
            },
            "microbits": microbits_data,
            "fusion": {
                "valid": fusion_valid,
                "alignment_method": "camera_timestamp_target",
                "camera_valid": camera_valid,
                "left_microbit_valid": left_valid,
                "right_microbit_valid": right_valid,
                "cross_modal_features": cross_modal,
            },
        }

        return fused

    def _build_microbit_entry(
        self, device_id: str, hand: str, align_result: AlignResult
    ) -> dict:
        """Build a microbit entry for the fused_frame.

        Args:
            device_id: Logical device ID.
            hand: Hand label.
            align_result: Result from TimeAligner.align().

        Returns:
            Dict following the fused_frame.microbits[] schema.
        """
        # Gather data from bracket samples
        t0 = align_result.bracket_samples[0] if len(align_result.bracket_samples) > 0 else None
        t1 = align_result.bracket_samples[1] if len(align_result.bracket_samples) > 1 else None

        entry = {
            "source": "microbit_ble",
            "device_id": device_id,
            "hand": hand,
            "ble_address": t0.data.get("ble_address", "") if t0 else "",
            "valid": align_result.valid,
            "timestamps": {
                "device_timestamp_ms": t0.data.get("device_timestamp_ms", 0) if t0 else 0,
                "pi_receive_timestamp_ns": t0.data.get("pi_receive_timestamp_ns", 0) if t0 else 0,
                "pi_aligned_timestamp_ns": t0.timestamp_ns if t0 else 0,
            },
            "raw_interpolated": align_result.interpolated
            if align_result.valid and align_result.interpolated
            else {},
            "instant_features": {},
            "ble": {
                "rssi_dbm": 0,
                "notification_sequence": t0.data.get("sequence", 0) if t0 else 0,
                "recent_loss_ratio": t0.data.get("recent_loss_ratio", 0) if t0 else 0,
                "connection_interval_ms": 30,
            },
            "sync": {
                "method": "ble_clock_mapping_and_interpolation",
                "nearest_sample_error_ms": align_result.nearest_sample_error_ms,
                "bracket_span_ms": align_result.bracket_span_ms,
                "sync_rtt_ms": 0,
                "clock_ready": align_result.valid,
            },
        }

        if not align_result.valid and align_result.reason:
            entry["sync"]["_invalid_reason"] = align_result.reason

        return entry

    def _compute_cross_modal(
        self,
        camera_hands: list[dict],
        microbits_data: list[dict],
        camera_valid: bool,
        left_valid: bool,
        right_valid: bool,
    ) -> dict:
        """Compute basic cross-modal features.

        In Phase 1, this is a placeholder. Full implementation comes in Phase 4
        with the InstantFeatureComputer and SlidingWindowComputer.

        Args:
            camera_hands: List of hand dicts from camera.
            microbits_data: List of micro:bit entries.
            camera_valid: Whether camera data is valid.
            left_valid: Whether left micro:bit is valid.
            right_valid: Whether right micro:bit is valid.

        Returns:
            Cross-modal features dict.
        """
        return {
            "beat_candidate": False,
            "beat_strength": 0.0,
            "vision_imu_consistency": 0.0,
            "combined_motion_intensity": 0.0,
        }
