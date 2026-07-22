from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .models import HandLandmarkObservation, Landmark3D, RawHandObservation


@dataclass(slots=True)
class QualityConfig:
    handedness_valid_threshold: float = 0.65
    min_in_bounds_ratio: float = 0.90
    ema_alpha: float = 0.45
    max_jump_norm_per_second: float = 5.0
    jump_base_allowance: float = 0.08
    max_missing_frames: int = 2
    hold_last_on_missing: bool = True
    reject_large_jumps: bool = True


@dataclass(slots=True)
class _TrackState:
    hand: HandLandmarkObservation
    timestamp_ns: int
    missing_frames: int = 0


class LandmarkNoiseProcessor:
    """Baseline landmark validation, EMA filtering and short-gap handling.

    This class is intentionally stateful and isolated from camera acquisition.
    A Kalman/One-Euro filter can replace it later while retaining the same
    process(raw_hands, timestamp_ns) interface.
    """

    def __init__(self, config: QualityConfig) -> None:
        if not 0.0 < config.ema_alpha <= 1.0:
            raise ValueError("ema_alpha must be in (0, 1]")
        self.config = config
        self._tracks: dict[str, _TrackState] = {}

    def process(
        self, raw_hands: list[RawHandObservation], timestamp_ns: int
    ) -> list[HandLandmarkObservation]:
        assigned = self._stabilize_labels(raw_hands)
        output: list[HandLandmarkObservation] = []
        seen_labels: set[str] = set()

        for raw in assigned:
            label = raw.hand_label
            if label in {"left", "right"}:
                seen_labels.add(label)
            processed = self._process_one(raw, timestamp_ns)
            output.append(processed)
            if label in {"left", "right"} and processed.source == "detected":
                self._tracks[label] = _TrackState(processed, timestamp_ns, 0)

        for label in ("left", "right"):
            if label in seen_labels or label not in self._tracks:
                continue
            held = self._handle_missing(label, timestamp_ns)
            if held is not None:
                output.append(held)

        output.sort(key=lambda hand: {"left": 0, "right": 1}.get(hand.hand_label, 2))
        return output

    def _stabilize_labels(
        self, raw_hands: list[RawHandObservation]
    ) -> list[RawHandObservation]:
        """Resolve low-confidence/duplicate labels using previous wrist positions."""
        result: list[RawHandObservation] = []
        used: set[str] = set()
        ordered = sorted(raw_hands, key=lambda h: h.handedness_score, reverse=True)

        for raw in ordered:
            label = raw.hand_label.lower()
            if label not in {"left", "right"}:
                label = "unknown"

            needs_reassignment = (
                label == "unknown"
                or label in used
                or raw.handedness_score < self.config.handedness_valid_threshold
            )
            if needs_reassignment:
                candidate = self._nearest_available_track(raw, used)
                if candidate is not None:
                    label = candidate

            if label in {"left", "right"}:
                used.add(label)

            result.append(
                RawHandObservation(
                    hand_label=label,
                    handedness_score=raw.handedness_score,
                    image_landmarks=raw.image_landmarks,
                    world_landmarks=raw.world_landmarks,
                )
            )
        return result

    def _nearest_available_track(
        self, raw: RawHandObservation, used: set[str]
    ) -> str | None:
        if len(raw.image_landmarks) != 21:
            return None
        wrist = raw.image_landmarks[0]
        candidates: list[tuple[float, str]] = []
        for label, state in self._tracks.items():
            if label in used or len(state.hand.image_landmarks) != 21:
                continue
            previous = state.hand.image_landmarks[0]
            candidates.append((math.hypot(wrist.x - previous.x, wrist.y - previous.y), label))
        return min(candidates)[1] if candidates else None

    def _process_one(
        self, raw: RawHandObservation, timestamp_ns: int
    ) -> HandLandmarkObservation:
        flags: list[str] = []
        valid_lengths = len(raw.image_landmarks) == 21 and len(raw.world_landmarks) == 21
        if not valid_lengths:
            flags.append("invalid_landmark_count")

        all_points = raw.image_landmarks + raw.world_landmarks
        finite = all(math.isfinite(v) for point in all_points for v in (point.x, point.y, point.z))
        if not finite:
            flags.append("non_finite_landmark")

        in_bounds_ratio = self._in_bounds_ratio(raw.image_landmarks)
        if in_bounds_ratio < self.config.min_in_bounds_ratio:
            flags.append("landmarks_out_of_frame")

        if raw.handedness_score < self.config.handedness_valid_threshold:
            flags.append("low_handedness_confidence")

        previous = self._tracks.get(raw.hand_label)
        jump_detected = False
        if previous is not None and valid_lengths:
            dt_s = max((timestamp_ns - previous.timestamp_ns) / 1_000_000_000.0, 1e-3)
            current_wrist = raw.image_landmarks[0]
            previous_wrist = previous.hand.image_landmarks[0]
            displacement = math.hypot(
                current_wrist.x - previous_wrist.x,
                current_wrist.y - previous_wrist.y,
            )
            allowed = (
                self.config.jump_base_allowance
                + self.config.max_jump_norm_per_second * dt_s
            )
            jump_detected = displacement > allowed
            if jump_detected:
                flags.append("abnormal_jump")

        detection_valid = (
            valid_lengths
            and finite
            and in_bounds_ratio >= self.config.min_in_bounds_ratio
            and raw.handedness_score >= self.config.handedness_valid_threshold
            and not (jump_detected and self.config.reject_large_jumps)
        )

        jump_penalty = 0.25 if jump_detected else 1.0
        quality_score = max(
            0.0,
            min(1.0, raw.handedness_score * in_bounds_ratio * jump_penalty),
        )

        if previous is not None and valid_lengths and finite:
            if jump_detected and self.config.reject_large_jumps:
                image_landmarks = list(previous.hand.image_landmarks)
                world_landmarks = list(previous.hand.world_landmarks)
                source = "jump_rejected"
            else:
                image_landmarks = self._ema_points(
                    previous.hand.image_landmarks, raw.image_landmarks
                )
                world_landmarks = self._ema_points(
                    previous.hand.world_landmarks, raw.world_landmarks
                )
                source = "detected"
        else:
            image_landmarks = list(raw.image_landmarks)
            world_landmarks = list(raw.world_landmarks)
            source = "detected"

        return HandLandmarkObservation(
            hand_label=raw.hand_label,
            handedness_score=raw.handedness_score,
            image_landmarks=image_landmarks,
            world_landmarks=world_landmarks,
            detection_valid=detection_valid,
            quality_score=quality_score,
            quality_flags=flags,
            source=source,
            missing_frames=0,
        )

    def _handle_missing(
        self, label: str, timestamp_ns: int
    ) -> HandLandmarkObservation | None:
        state = self._tracks[label]
        state.missing_frames += 1
        if (
            not self.config.hold_last_on_missing
            or state.missing_frames > self.config.max_missing_frames
        ):
            if state.missing_frames > self.config.max_missing_frames:
                del self._tracks[label]
            return None

        previous = state.hand
        held = HandLandmarkObservation(
            hand_label=label,
            handedness_score=previous.handedness_score,
            image_landmarks=list(previous.image_landmarks),
            world_landmarks=list(previous.world_landmarks),
            detection_valid=False,
            quality_score=max(0.0, previous.quality_score * 0.7),
            quality_flags=["short_gap_filled"],
            source="held",
            missing_frames=state.missing_frames,
        )
        state.timestamp_ns = timestamp_ns
        return held

    def _ema_points(
        self, previous: Iterable[Landmark3D], current: Iterable[Landmark3D]
    ) -> list[Landmark3D]:
        alpha = self.config.ema_alpha
        return [
            Landmark3D(
                x=alpha * cur.x + (1.0 - alpha) * prev.x,
                y=alpha * cur.y + (1.0 - alpha) * prev.y,
                z=alpha * cur.z + (1.0 - alpha) * prev.z,
            )
            for prev, cur in zip(previous, current, strict=True)
        ]

    @staticmethod
    def _in_bounds_ratio(points: list[Landmark3D]) -> float:
        if not points:
            return 0.0
        inside = sum(1 for point in points if 0.0 <= point.x <= 1.0 and 0.0 <= point.y <= 1.0)
        return inside / len(points)
