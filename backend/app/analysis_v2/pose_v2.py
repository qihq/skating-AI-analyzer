"""Identity-authorized Pose V2 primitives.

This module deliberately does not replace ``app.services.pose``.  The legacy
extractor remains the whole-record adapter for historical analyses; V2 uses
these typed helpers so target authorization, timing and provenance cannot be
lost in a loosely typed payload.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from app.analysis_v2.contracts import (
    JointObservation,
    PoseAvailabilitySummary,
    PoseObservation,
    PoseJointProvenance,
    TrackState,
)


@dataclass(frozen=True)
class TargetCrop:
    left: int
    top: int
    right: int
    bottom: int
    clipped: bool
    context_margin: float

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def normalized(self, image_size: tuple[int, int]) -> tuple[float, float, float, float]:
        width, height = image_size
        return (self.left / width, self.top / height, self.right / width, self.bottom / height)


def build_target_crop(track_state: TrackState, *, image_size: tuple[int, int], context_margin: float = 0.08) -> TargetCrop | None:
    """Expand a confirmed measured target box by a bounded source-image margin."""
    if track_state.state != "confirmed" or track_state.bbox is None or track_state.bbox_source != "measured":
        return None
    if context_margin < 0 or context_margin > 0.5:
        raise ValueError("context_margin must be between 0 and 0.5")
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image_size must be positive")
    left, top, right, bottom = track_state.bbox
    raw = (
        math.floor(left * image_width - context_margin * image_width),
        math.floor(top * image_height - context_margin * image_height),
        math.ceil(right * image_width + context_margin * image_width),
        math.ceil(bottom * image_height + context_margin * image_height),
    )
    clipped = raw[0] < 0 or raw[1] < 0 or raw[2] > image_width or raw[3] > image_height
    return TargetCrop(
        left=max(0, min(image_width - 1, raw[0])),
        top=max(0, min(image_height - 1, raw[1])),
        right=max(1, min(image_width, raw[2])),
        bottom=max(1, min(image_height, raw[3])),
        clipped=clipped,
        context_margin=context_margin,
    )


@dataclass(frozen=True)
class PoseProviderConfig:
    num_poses: int = 4
    task_model_path: str | None = None
    context_margin: float = 0.08
    provider_version: str = "pose-provider.v2"
    model_hash: str | None = None

    def __post_init__(self) -> None:
        if self.num_poses < 1:
            raise ValueError("num_poses must be positive")
        if not 0 <= self.context_margin <= 0.5:
            raise ValueError("context_margin must be between 0 and 0.5")

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "PoseProviderConfig":
        values = env or os.environ
        raw_num = values.get("POSE_NUM_POSES", "4")
        try:
            num_poses = max(1, int(raw_num))
        except ValueError:
            num_poses = 4
        margin_raw = values.get("POSE_CONTEXT_MARGIN", "0.08")
        try:
            margin = float(margin_raw)
        except ValueError:
            margin = 0.08
        path = values.get("MEDIAPIPE_POSE_TASK_PATH", "").strip() or None
        resolved = resolve_task_model_path(path)
        return cls(num_poses=num_poses, task_model_path=str(resolved) if resolved else path, context_margin=margin, model_hash=hash_model_file(resolved))

    def fingerprint(self) -> str:
        payload = {
            "provider_version": self.provider_version,
            "num_poses": self.num_poses,
            "task_model_path": self.task_model_path,
            "context_margin": self.context_margin,
            "model_hash": self.model_hash,
        }
        return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @property
    def mode(self) -> str:
        return "task_multi_pose" if self.task_model_path and Path(self.task_model_path).exists() else "fallback_single_pose"


def resolve_task_model_path(task_model_path: str | None, *, project_root: Path | None = None) -> Path | None:
    if not task_model_path:
        return None
    configured = Path(task_model_path)
    root = project_root or Path(__file__).resolve().parents[3]
    candidates = [configured]
    if configured.is_absolute():
        candidates.append(root / str(configured).lstrip("/\\"))
    else:
        candidates.append(root / configured)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[-1].resolve()


def hash_model_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


class PoseInference(Protocol):
    def __call__(self, crop: TargetCrop, *, source_frame_index: int, pts_sec: float) -> Mapping[str, Any] | None: ...


class PoseProvider(Protocol):
    config: PoseProviderConfig

    def observe(self, *, track_state: TrackState, image_size: tuple[int, int], source_frame_index: int, pts_sec: float, infer: PoseInference) -> PoseObservation: ...


def _blocked_pose(*, source_video_hash: str, source_frame_index: int, pts_sec: float, track_state: TrackState, source_method: str, model_fingerprint: str | None, reason: str) -> PoseObservation:
    return PoseObservation(
        source_video_hash=source_video_hash,
        source_frame_index=source_frame_index,
        pts_sec=pts_sec,
        track_state=track_state,
        identity_state=track_state.state,
        joints={"nose": JointObservation(x=0, y=0, confidence=0, visibility=0, provenance="identity-blocked", source="identity-blocked")},
        pose_quality=0,
        authoritative=False,
        source_method=source_method,
        model_fingerprint=model_fingerprint,
        smoothing_break_reason=reason,
    )


class TargetOnlyPoseProvider:
    """Provider adapter that refuses to infer without a confirmed target crop."""

    def __init__(self, config: PoseProviderConfig | None = None, *, source_video_hash: str = "unknown") -> None:
        self.config = config or PoseProviderConfig.from_environment()
        self.source_video_hash = source_video_hash

    def observe(self, *, track_state: TrackState, image_size: tuple[int, int], source_frame_index: int, pts_sec: float, infer: PoseInference) -> PoseObservation:
        crop = build_target_crop(track_state, image_size=image_size, context_margin=self.config.context_margin)
        if crop is None:
            return _blocked_pose(source_video_hash=self.source_video_hash, source_frame_index=source_frame_index, pts_sec=pts_sec, track_state=track_state, source_method=self.config.mode, model_fingerprint=self.config.fingerprint(), reason="identity_not_confirmed")
        raw = infer(crop, source_frame_index=source_frame_index, pts_sec=pts_sec)
        if not raw or not isinstance(raw.get("joints"), Mapping):
            return PoseObservation(
                source_video_hash=self.source_video_hash,
                source_frame_index=source_frame_index,
                pts_sec=pts_sec,
                track_state=track_state,
                identity_state="confirmed",
                joints={"nose": JointObservation(x=0, y=0, confidence=0, visibility=0, provenance="missing", source="missing")},
                pose_quality=0,
                authoritative=True,
                source_method=self.config.mode,
                model_fingerprint=self.config.fingerprint(),
                crop_bbox=crop.normalized(image_size),
                crop_context_margin=self.config.context_margin,
                crop_clipped=crop.clipped,
            )
        joints: dict[str, JointObservation] = {}
        crop_width, crop_height = max(1, crop.width), max(1, crop.height)
        for name, value in raw["joints"].items():
            if not isinstance(value, Mapping):
                continue
            # Inference coordinates are normalized within the target crop.
            cx, cy = float(value.get("x", 0)), float(value.get("y", 0))
            source_x = (crop.left + cx * crop_width) / image_size[0]
            source_y = (crop.top + cy * crop_height) / image_size[1]
            confidence = max(0.0, min(1.0, float(value.get("confidence", value.get("visibility", 0)))))
            visibility = max(0.0, min(1.0, float(value.get("visibility", confidence))))
            provenance: PoseJointProvenance = "clipped" if crop.clipped else "measured"
            joints[str(name)] = JointObservation(x=source_x, y=source_y, confidence=confidence, visibility=visibility, provenance=provenance, source="measured", coordinate_space="normalized", raw_x=source_x, raw_y=source_y, raw_confidence=confidence, raw_visibility=visibility, crop_clipped=crop.clipped)
        if not joints:
            joints["nose"] = JointObservation(x=0, y=0, confidence=0, visibility=0, provenance="missing", source="missing")
        return PoseObservation(
            source_video_hash=self.source_video_hash,
            source_frame_index=source_frame_index,
            pts_sec=pts_sec,
            track_state=track_state,
            identity_state="confirmed",
            joints=joints,
            person_scale=float(raw.get("person_scale", 1.0)) if raw.get("person_scale") else None,
            pose_quality=max(0.0, min(1.0, float(raw.get("pose_quality", 0.0)))) if raw.get("pose_quality") is not None else None,
            authoritative=True,
            source_method=str(raw.get("source_method", self.config.mode)),
            model_fingerprint=self.config.fingerprint(),
            crop_bbox=crop.normalized(image_size),
            crop_context_margin=self.config.context_margin,
            crop_clipped=crop.clipped,
            usable_joint_mask={name: joint.is_authoritative and joint.visibility > 0 for name, joint in joints.items()},
        )


def _copy_joint(joint: JointObservation, **changes: Any) -> JointObservation:
    return joint.model_copy(update=changes)


def smooth_pose_observations(observations: Sequence[PoseObservation], *, max_gap_sec: float = 0.25, smoothing_tau_sec: float = 0.12) -> list[PoseObservation]:
    """PTS-aware EMA smoothing over confirmed measured observations only."""
    output: list[PoseObservation] = []
    previous_pts: float | None = None
    previous_state: str | None = None
    previous_values: dict[str, tuple[float, float]] = {}
    for observation in observations:
        current = observation
        gap = 0 if previous_pts is None else max(0.0, observation.pts_sec - previous_pts)
        state = observation.identity_state or observation.track_state.state
        can_smooth = (
            observation.authoritative
            and state == "confirmed"
            and previous_state == "confirmed"
            and previous_pts is not None
            and gap <= max_gap_sec
            and not observation.scene_cut
        )
        joints: dict[str, JointObservation] = {}
        for name, joint in observation.joints.items():
            if not joint.is_authoritative or joint.raw_x is None or joint.raw_y is None:
                joints[name] = joint
                continue
            if can_smooth and name in previous_values:
                alpha = 1.0 - math.exp(-max(gap, 1e-6) / max(smoothing_tau_sec, 1e-6))
                prior_x, prior_y = previous_values[name]
                x = prior_x + alpha * (joint.x - prior_x)
                y = prior_y + alpha * (joint.y - prior_y)
                joints[name] = _copy_joint(joint, x=x, y=y, provenance="smoothed", source="measured", raw_x=joint.x, raw_y=joint.y, raw_confidence=joint.confidence, raw_visibility=joint.visibility)
                previous_values[name] = (x, y)
            else:
                joints[name] = joint
                previous_values[name] = (joint.x, joint.y)
        reason = None
        if previous_pts is not None and gap > max_gap_sec:
            reason = "large_time_gap"
        elif observation.scene_cut:
            reason = "scene_cut"
        elif previous_state != "confirmed" or state != "confirmed":
            reason = "identity_boundary"
        current = observation.model_copy(update={"joints": joints, "temporal_gap_sec": gap, "smoothing_break_reason": reason, "usable_joint_mask": {name: item.is_authoritative and item.visibility > 0 for name, item in joints.items()}})
        output.append(current)
        previous_pts = observation.pts_sec
        previous_state = state
        if reason is not None:
            previous_values = {name: (joint.x, joint.y) for name, joint in joints.items() if joint.is_authoritative}
    return output


def interpolate_pose_for_display(observations: Sequence[PoseObservation], *, max_gap_sec: float = 0.2) -> list[PoseObservation]:
    """Fill short missing intervals for rendering only; never marks them authoritative."""
    output = list(observations)
    for index, current in enumerate(observations):
        if current.authoritative and any(joint.is_authoritative for joint in current.joints.values()):
            continue
        if index == 0 or index == len(observations) - 1:
            continue
        before, after = observations[index - 1], observations[index + 1]
        if not before.authoritative or not after.authoritative or after.pts_sec - before.pts_sec > max_gap_sec:
            continue
        ratio = (current.pts_sec - before.pts_sec) / max(after.pts_sec - before.pts_sec, 1e-9)
        joints: dict[str, JointObservation] = {}
        for name, left in before.joints.items():
            right = after.joints.get(name)
            if right is None or not left.is_authoritative or not right.is_authoritative:
                joints[name] = current.joints.get(name, left)
                continue
            joints[name] = JointObservation(x=left.x + (right.x - left.x) * ratio, y=left.y + (right.y - left.y) * ratio, confidence=0, visibility=0, provenance="interpolated-display-only", source="interpolated-display-only", raw_x=None, raw_y=None)
        output[index] = current.model_copy(update={"joints": joints, "authoritative": False, "pose_quality": None, "usable_joint_mask": {name: False for name in joints}, "smoothing_break_reason": "display_interpolation_only"})
    return output


def summarize_pose_quality(observations: Iterable[PoseObservation], *, per_phase: Mapping[str, Sequence[int]] | None = None) -> PoseAvailabilitySummary:
    frames = list(observations)
    counts = {"measured": 0, "smoothed": 0, "interpolated-display-only": 0, "missing": 0, "identity-blocked": 0, "clipped": 0}
    mask: dict[str, bool] = {}
    for frame in frames:
        for name, joint in frame.joints.items():
            counts[joint.provenance] = counts.get(joint.provenance, 0) + 1
            mask[name] = mask.get(name, False) or (joint.is_authoritative and joint.visibility > 0)
    authoritative_frames = sum(frame.authoritative for frame in frames)
    blocked_frames = sum(any(joint.provenance == "identity-blocked" for joint in frame.joints.values()) for frame in frames)
    status = "available" if authoritative_frames == len(frames) and frames else "partial" if authoritative_frames else "blocked" if blocked_frames else "unavailable"
    phase_quality: dict[str, float | None] = {}
    if per_phase:
        for phase, indexes in per_phase.items():
            selected = [frames[i].pose_quality for i in indexes if 0 <= i < len(frames) and frames[i].pose_quality is not None]
            phase_quality[phase] = sum(selected) / len(selected) if selected else None
    return PoseAvailabilitySummary(status=status, frame_count=len(frames), authoritative_frame_count=authoritative_frames, measured_joint_count=counts["measured"], smoothed_joint_count=counts["smoothed"], interpolated_display_only_count=counts["interpolated-display-only"], missing_joint_count=counts["missing"], identity_blocked_frame_count=blocked_frames, clipped_joint_count=counts["clipped"], usable_joint_mask=mask, per_phase_quality=phase_quality, source_method=next((frame.source_method for frame in frames if frame.source_method), "unknown"), model_fingerprint=next((frame.model_fingerprint for frame in frames if frame.model_fingerprint), None))
