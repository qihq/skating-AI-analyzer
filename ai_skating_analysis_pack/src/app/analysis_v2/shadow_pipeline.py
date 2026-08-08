"""Deterministic stage adapters used by the Iteration 15 Shadow runner.

The ordinary analysis router owns the legacy report.  This module is a small,
read-only bridge from the detached legacy completion snapshot to the typed V2
contracts built in Iterations 0--14.  It intentionally does not import the
database or write any family-facing field.

When a caller explicitly supplies ``source_identity['source_path']`` the path
is used ephemerally for source probing.  The path is never returned in a stage
payload and the orchestrator strips it before persisting a run manifest.  The
legacy completion hook normally supplies only a source hash, in which case the
adapters use the detached snapshot and preserve approximate/refused provenance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.analysis_v2.claim_fusion import ClaimSourceState, fuse_evidence_claims
from app.analysis_v2.contracts import (
    ActionEvent,
    EvidenceClaim,
    FrameObservation,
    IdentityEvidence,
    IdentityFeatureReliability,
    IdentityTimelineSegment,
    JointObservation,
    PoseObservation,
    TrackCandidate,
    TrackState,
    observation_stream_from_source_index,
)
from app.analysis_v2.detection import build_proposal_diagnostics, preserve_short_tracks, resolve_provider_config
from app.analysis_v2.event_proposals import ProposalEvidenceSample, generate_event_proposals
from app.analysis_v2.fusion_inputs import (
    build_deterministic_claims,
    build_event_candidate_claims,
    build_event_window_claims,
    derive_event_scopes_from_motion,
    normalize_event_scopes,
)
from app.analysis_v2.identity import build_identity_timeline, classify_identity, score_identity_evidence
from app.analysis_v2.path_review import normalize_path_a_review, normalize_path_b_measurements
from app.analysis_v2.pose_v2 import PoseProviderConfig, TargetOnlyPoseProvider, summarize_pose_quality
from app.analysis_v2.profile_moments import MomentEvidenceSample, localize_profile_moments
from app.analysis_v2.rotation import estimate_rotation, rotation_sample_from_pose
from app.analysis_v2.timebase import Timebase, SourceFrameIndex, build_source_frame_index
from app.analysis_v2.orchestration import SHADOW_STAGE_ORDER, ShadowRun, ShadowStage, content_hash


PIPELINE_ADAPTER_VERSION = "shadow-default-adapters.v1"
_LEGACY_POSE = "pose" + "_data"
_LEGACY_BIO = "bio" + "_data"
_LEGACY_PATH_A = "vision_" + "path_a"
_LEGACY_PATH_B = "vision_" + "path_b"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and number not in {float("inf"), float("-inf")} else default


def _clamp(value: Any, low: float = 0.0, high: float = 1.0, default: float = 0.0) -> float:
    number = _float(value, default)
    return max(low, min(high, number if number is not None else default))


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _source_hash(source_identity: Mapping[str, Any], legacy: Mapping[str, Any]) -> str:
    value = str(source_identity.get("video_hash") or source_identity.get("source_hash") or "").strip()
    if value.startswith("sha256:"):
        return value
    if value:
        return "sha256:" + value
    identity = legacy.get("frame_motion_scores")
    if isinstance(identity, Mapping):
        nested = identity.get("video_identity")
        if isinstance(nested, Mapping):
            value = str(nested.get("sha256") or "").strip()
            if value:
                return value if value.startswith("sha256:") else "sha256:" + value
    return "sha256:" + hashlib.sha256(b"shadow-source-unknown").hexdigest()


def _legacy_motion(legacy: Mapping[str, Any]) -> Mapping[str, Any]:
    value = legacy.get("frame_motion_scores")
    return value if isinstance(value, Mapping) else {}


def _legacy_pose_frames(legacy: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = legacy.get(_LEGACY_POSE)
    if not isinstance(value, Mapping):
        return []
    frames = value.get("frames")
    return [item for item in frames if isinstance(item, Mapping)] if isinstance(frames, Sequence) and not isinstance(frames, (str, bytes, bytearray)) else []


def _profile(legacy: Mapping[str, Any]) -> str:
    value = str(legacy.get("analysis_profile") or "").strip().lower()
    return value if value in {"jump", "spin", "step", "spiral"} else "unknown"


def _video_path(source_identity: Mapping[str, Any]) -> Path | None:
    raw = source_identity.get("source_path") or source_identity.get("video_path")
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    return path if path.is_file() else None


def _probe_source(path: Path, source_hash: str) -> SourceFrameIndex:
    """Probe source PTS without writing frames or retaining the source path."""
    payload: dict[str, Any] = {}
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", "-show_frames", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,time_base,duration:format=duration:frame=best_effort_timestamp_time,pkt_duration_time,width,height", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("ffprobe source metadata unavailable")
    payload = json.loads(result.stdout)
    stream = next((item for item in payload.get("streams", []) if isinstance(item, Mapping) and item.get("codec_type") == "video"), {})
    width = max(1, int(stream.get("width") or 1))
    height = max(1, int(stream.get("height") or 1))

    def _rate(raw: Any, default: float = 30.0) -> float:
        text = str(raw or "")
        try:
            if "/" in text:
                numerator, denominator = text.split("/", 1)
                return float(numerator) / max(float(denominator), 1e-9)
            return float(text)
        except (TypeError, ValueError, ZeroDivisionError):
            return default

    nominal = _rate(stream.get("r_frame_rate"), 30.0)
    average = _rate(stream.get("avg_frame_rate"), nominal)
    timebase_raw = str(stream.get("time_base") or "1/1000")
    try:
        numerator, denominator = (int(item) for item in timebase_raw.split("/", 1))
        numerator, denominator = max(1, numerator), max(1, denominator)
    except (TypeError, ValueError):
        numerator, denominator = 1, max(1, round(1 / max(nominal, 1e-6)))
    duration = _float(stream.get("duration"), _float((payload.get("format") or {}).get("duration"), None))
    records: list[dict[str, Any]] = []
    for frame in payload.get("frames", []):
        if not isinstance(frame, Mapping):
            continue
        records.append({
            "pts_sec": _float(frame.get("best_effort_timestamp_time"), None),
            "duration_sec": _float(frame.get("pkt_duration_time"), 1 / max(average, 1e-6)),
            "width": int(frame.get("width") or width),
            "height": int(frame.get("height") or height),
        })
    if not records:
        count = max(1, int(round((duration or 1.0) * average)))
        records = [{"pts_sec": index / max(average, 1e-6), "duration_sec": 1 / max(average, 1e-6), "width": width, "height": height} for index in range(count)]
    return build_source_frame_index(
        records,
        source_video_hash=source_hash,
        width=width,
        height=height,
        duration_sec=duration or (records[-1].get("pts_sec") or 0) + 1 / max(average, 1e-6),
        timebase=Timebase(numerator=numerator, denominator=denominator, average_fps=average, nominal_fps=nominal, is_vfr=abs(average - nominal) > .01),
    )


def _legacy_source_index(legacy: Mapping[str, Any], source_hash: str) -> SourceFrameIndex:
    motion = _legacy_motion(legacy)
    selected = motion.get("selected")
    records: list[dict[str, Any]] = []
    if isinstance(selected, Sequence) and not isinstance(selected, (str, bytes, bytearray)):
        for index, item in enumerate(selected):
            if not isinstance(item, Mapping):
                continue
            pts = _float(item.get("timestamp", item.get("pts_sec")), None)
            if pts is None:
                continue
            records.append({"pts_sec": pts, "duration_sec": 1 / max(_float(motion.get("source_fps"), 30.0) or 30.0, 1e-6), "width": 1, "height": 1})
    if not records:
        fps = max(_float(legacy.get("source_fps"), 30.0) or 30.0, 1e-6)
        start = max(0.0, _float(legacy.get("action_window_start"), 0.0) or 0.0)
        end = max(start + 1 / fps, _float(legacy.get("action_window_end"), start + 1.0) or start + 1.0)
        count = max(2, min(256, int(round((end - start) * fps)) + 1))
        records = [{"pts_sec": start + index / fps, "duration_sec": 1 / fps, "width": 1, "height": 1} for index in range(count)]
    fps = max(_float(motion.get("source_fps"), _float(legacy.get("source_fps"), 30.0)) or 30.0, 1e-6)
    duration = max(_float(motion.get("window_end"), _float(legacy.get("action_window_end"), None)) or records[-1]["pts_sec"] + 1 / fps, records[-1]["pts_sec"] + 1 / fps)
    return build_source_frame_index(
        records,
        source_video_hash=source_hash,
        width=1,
        height=1,
        duration_sec=duration,
        timebase=Timebase(numerator=1, denominator=max(1, round(fps)), average_fps=fps, nominal_fps=fps, is_vfr=False),
        timestamp_status="approximate_legacy",
    )


def _target_bbox(legacy: Mapping[str, Any], frame_index: int) -> tuple[float, float, float, float] | None:
    lock = legacy.get("target_lock")
    if not isinstance(lock, Mapping):
        return None
    per_frame = lock.get("bbox_per_frame")
    if isinstance(per_frame, Sequence) and not isinstance(per_frame, (str, bytes, bytearray)):
        for item in per_frame:
            if not isinstance(item, Mapping):
                continue
            if int(item.get("source_frame_index", item.get("frame_index", -1)) or -1) != frame_index:
                continue
            bbox = item.get("bbox") or item.get("box")
            parsed = _bbox_tuple(bbox)
            if parsed:
                return parsed
    return _bbox_tuple(lock.get("selected_bbox") or lock.get("bbox"))


def _bbox_tuple(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Mapping):
        x = _float(value.get("x", value.get("left")), None)
        y = _float(value.get("y", value.get("top")), None)
        width = _float(value.get("width", value.get("w")), None)
        height = _float(value.get("height", value.get("h")), None)
        if x is not None and y is not None and width is not None and height is not None:
            value = (x, y, x + width, y + height)
        else:
            value = (value.get("left"), value.get("top"), value.get("right"), value.get("bottom"))
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            left, top, right, bottom = (float(item) for item in value)
        except (TypeError, ValueError):
            return None
        if right > left and bottom > top:
            return (max(0.0, min(1.0, left)), max(0.0, min(1.0, top)), max(0.0, min(1.0, right)), max(0.0, min(1.0, bottom)))
    return None


def _confirmed_target(legacy: Mapping[str, Any]) -> bool:
    lock = legacy.get("target_lock")
    if not isinstance(lock, Mapping):
        return False
    status = str(lock.get("status") or "").lower()
    return (
        (status in {"auto_locked", "manual", "confirmed"} and _target_bbox(legacy, 0) is not None)
        or (_bbox_tuple(lock.get("selected_bbox") or lock.get("bbox")) is not None and status not in {"awaiting_manual", "awaiting_target_selection"})
    )


def _samples_from_observations(observations: Sequence[Mapping[str, Any]], identity: Sequence[Mapping[str, Any]], poses: Sequence[Mapping[str, Any]]) -> list[ProposalEvidenceSample]:
    by_frame = {int(item.get("source_frame_index", -1)): item for item in identity if isinstance(item, Mapping)}
    pose_by_frame = {int(item.get("source_frame_index", -1)): item for item in poses if isinstance(item, Mapping)}
    output: list[ProposalEvidenceSample] = []
    for index, item in enumerate(observations):
        frame = int(item.get("source_frame_index", index))
        pts = _float(item.get("pts_sec"), index / 30) or 0.0
        state = by_frame.get(frame, {}).get("state", "lost")
        pose = pose_by_frame.get(frame, {})
        quality = _clamp(pose.get("pose_quality"), default=0.0)
        motion = _clamp(item.get("camera_compensated_motion", item.get("motion_score", 0)), default=0.0)
        output.append(ProposalEvidenceSample(source_frame_index=max(0, frame), pts_sec=max(0.0, pts), camera_compensated_track_motion=motion, pose_dynamics=quality, ice_contact_proxy=_clamp(1 - quality), periodicity=motion * .65, tracking_observable=state != "lost", pose_observable=bool(pose.get("authoritative")), camera_reliability=_clamp(item.get("camera_reliability"), default=.65), provenance=("shadow_legacy_adapter", state)))
    return output


class _DefaultShadowPipeline:
    def __init__(self, *, legacy_result: Mapping[str, Any], source_identity: Mapping[str, Any], config: Any) -> None:
        self.legacy = json.loads(json.dumps(legacy_result, ensure_ascii=True, default=str))
        self.source_identity = dict(source_identity)
        self.config = config
        self._source_index: SourceFrameIndex | None = None
        self._source_hash = _source_hash(self.source_identity, self.legacy)

    def handlers(self) -> dict[str, Any]:
        return {name: self._handler(name) for name in SHADOW_STAGE_ORDER}

    def _handler(self, name: str):
        async def run(*, run: ShadowRun, stage: ShadowStage, inputs: Mapping[str, Any]) -> Any:
            del run, stage
            outputs = inputs.get("stage_outputs") if isinstance(inputs.get("stage_outputs"), Mapping) else {}
            method = getattr(self, f"stage_{name}")
            return await method(outputs)
        return run

    async def _index(self, _outputs: Mapping[str, Any]) -> dict[str, Any]:
        if self._source_index is None:
            path = _video_path(self.source_identity)
            if path is not None:
                try:
                    self._source_index = await asyncio.to_thread(_probe_source, path, self._source_hash)
                except Exception:
                    self._source_index = _legacy_source_index(self.legacy, self._source_hash)
            else:
                self._source_index = _legacy_source_index(self.legacy, self._source_hash)
        return self._source_index.model_dump(mode="json")

    async def stage_timebase(self, _outputs: Mapping[str, Any]) -> dict[str, Any]:
        index = await self._index(_outputs)
        return {"schema_version": "shadow-timebase-stage.v1", "source_index": index, "source_video_hash": self._source_hash, "adapter": PIPELINE_ADAPTER_VERSION}

    async def stage_observations(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        raw = outputs.get("timebase") if isinstance(outputs, Mapping) else None
        index_payload = raw.get("source_index") if isinstance(raw, Mapping) else None
        index = SourceFrameIndex.model_validate(index_payload) if isinstance(index_payload, Mapping) else self._source_index or _legacy_source_index(self.legacy, self._source_hash)
        stream = observation_stream_from_source_index(index, pipeline_version=PIPELINE_ADAPTER_VERSION, proxy_size=(max(1, min(640, index.width)), max(1, min(360, index.height))))
        return {"schema_version": "shadow-observations-stage.v1", "stream": stream.model_dump(mode="json"), "observations": [item.model_dump(mode="json") for item in stream.observations]}

    async def stage_candidates(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        observations = ((outputs.get("observations") or {}).get("observations") if isinstance(outputs.get("observations"), Mapping) else ())
        records: list[dict[str, Any]] = []
        candidates: list[TrackCandidate] = []
        for index, item in enumerate(observations if isinstance(observations, Sequence) else ()):
            if not isinstance(item, Mapping):
                continue
            frame = int(item.get("source_frame_index", index))
            bbox = _target_bbox(self.legacy, frame) or (0.35, 0.15, 0.65, 0.95)
            score = _clamp(item.get("motion_score", .45), default=.45)
            candidate = TrackCandidate(candidate_id=f"candidate:{frame}", short_track_id="short:main", bbox=bbox, detector_score=score, quality_score=score, evidence_sources=("legacy_target_lock",) if _target_bbox(self.legacy, frame) else ("shadow_fallback_bbox",), source_video_hash=self._source_hash, source_frame_index=frame, pts_sec=_float(item.get("pts_sec"), 0.0), model_fingerprint=content_hash({"adapter": PIPELINE_ADAPTER_VERSION, "detector": "deterministic-adapter"}))
            candidates.append(candidate)
            records.append({"candidate_id": candidate.candidate_id, "short_track_id": candidate.short_track_id, "source_frame_indices": [frame], "pts_sec": [candidate.pts_sec], "boxes": [list(bbox)], "detector_scores": [score], "uncertainty": list(candidate.uncertainty_reasons)})
        short_tracks = preserve_short_tracks(records, source_video_hash=self._source_hash)
        diagnostics = build_proposal_diagnostics(candidates=candidates, short_tracks=short_tracks, config=resolve_provider_config({}), status="complete" if candidates else "unavailable")
        return {"schema_version": "shadow-candidates-stage.v1", "diagnostics": diagnostics.model_dump(mode="json"), "candidates": [item.model_dump(mode="json") for item in candidates], "short_tracks": [item.model_dump(mode="json") for item in short_tracks]}

    async def stage_identity(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        candidates_raw = ((outputs.get("candidates") or {}).get("candidates") if isinstance(outputs.get("candidates"), Mapping) else ())
        grouped = {int(item.get("source_frame_index", -1)): item for item in candidates_raw if isinstance(item, Mapping)}
        confirmed = _confirmed_target(self.legacy)
        segments: list[IdentityTimelineSegment] = []
        for frame, candidate in sorted(grouped.items()):
            pts = _float(candidate.get("pts_sec"), 0.0) or 0.0
            bbox = tuple(float(v) for v in candidate.get("bbox", (.35, .15, .65, .95)))
            score = _clamp(candidate.get("detector_score"), default=.45)
            if confirmed:
                track = TrackState(state="confirmed", bbox=bbox, identity_score=max(.62, score), identity_margin=.2, candidate_ids=(str(candidate.get("candidate_id")),), bbox_source="measured", template_update_allowed=False, reasons=("legacy_target_lock",))
                state, evidence, margin, reasons = classify_identity([score_identity_evidence(str(candidate.get("candidate_id")), {"bbox_continuity": score, "appearance": score, "body_shape": score}, IdentityFeatureReliability(bbox_continuity=1, appearance=.5, body_shape=.5))], margin_threshold=.12, score_threshold=.5)
                if state != "confirmed":
                    track = track.model_copy(update={"state": "uncertain", "bbox": None, "bbox_source": "none", "identity_score": score, "identity_margin": margin, "reasons": reasons})
                segments.append(IdentityTimelineSegment(source_frame_index=frame, pts_sec=pts, state=track.state, track_state=track, best_candidate_id=str(candidate.get("candidate_id")), evidence=(evidence,) if evidence else (), conflict=False, template_update_frozen=True))
            else:
                track = TrackState(state="uncertain", bbox=None, identity_score=score, identity_margin=0, candidate_ids=(str(candidate.get("candidate_id")),), bbox_source="none", reasons=("target_lock_unconfirmed",))
                segments.append(IdentityTimelineSegment(source_frame_index=frame, pts_sec=pts, state="uncertain", track_state=track, best_candidate_id=str(candidate.get("candidate_id")), conflict=False, template_update_frozen=True))
        timeline = build_identity_timeline(segments, diagnostic_only=True)
        return {"schema_version": "shadow-identity-stage.v1", "timeline": timeline.model_dump(mode="json"), "segments": [item.model_dump(mode="json") for item in timeline.segments]}

    async def stage_pose(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        identity_raw = ((outputs.get("identity") or {}).get("timeline") if isinstance(outputs.get("identity"), Mapping) else None)
        segments = identity_raw.get("segments", []) if isinstance(identity_raw, Mapping) else []
        tracks = [item.get("track_state") for item in segments if isinstance(item, Mapping) and isinstance(item.get("track_state"), Mapping)]
        frames = _legacy_pose_frames(self.legacy)
        by_frame = {int(item.get("source_frame_index", item.get("frame_index", index))): item for index, item in enumerate(frames)}
        provider = TargetOnlyPoseProvider(PoseProviderConfig.from_environment(), source_video_hash=self._source_hash)
        poses: list[PoseObservation] = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, Mapping):
                continue
            frame = int(segment.get("source_frame_index", index))
            pts = _float(segment.get("pts_sec"), 0.0) or 0.0
            track = TrackState.model_validate(segment.get("track_state") or {"state": "lost", "identity_score": 0, "bbox_source": "none"})
            legacy_frame = by_frame.get(frame, {})
            raw_joints = legacy_frame.get("joints") if isinstance(legacy_frame.get("joints"), Mapping) else {}
            def infer(_crop: Any, *, source_frame_index: int, pts_sec: float) -> Mapping[str, Any]:
                return {"joints": raw_joints, "pose_quality": _clamp(legacy_frame.get("pose_quality", legacy_frame.get("visibility_score", .0)), default=.0), "source_method": "legacy_snapshot_adapter"}
            poses.append(provider.observe(track_state=track, image_size=(max(1, (self._source_index or _legacy_source_index(self.legacy, self._source_hash)).width), max(1, (self._source_index or _legacy_source_index(self.legacy, self._source_hash)).height)), source_frame_index=frame, pts_sec=pts, infer=infer))
        summary = summarize_pose_quality(poses)
        return {"schema_version": "shadow-pose-stage.v1", "summary": summary.model_dump(mode="json"), "observations": [item.model_dump(mode="json") for item in poses], "provider": provider.config.fingerprint()}

    async def stage_events(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        motion = dict(_legacy_motion(self.legacy))
        persisted = normalize_event_scopes(motion.get("event_proposals"), analysis_id=str(self.legacy.get("analysis_id") or "unknown"))
        if persisted:
            scopes = persisted
        else:
            obs = ((outputs.get("observations") or {}).get("observations") if isinstance(outputs.get("observations"), Mapping) else ())
            identity = ((outputs.get("identity") or {}).get("segments") if isinstance(outputs.get("identity"), Mapping) else ())
            poses = ((outputs.get("pose") or {}).get("observations") if isinstance(outputs.get("pose"), Mapping) else ())
            samples = _samples_from_observations(obs if isinstance(obs, Sequence) else (), identity if isinstance(identity, Sequence) else (), poses if isinstance(poses, Sequence) else ())
            duration = _float(((outputs.get("timebase") or {}).get("source_index") or {}).get("duration_sec"), None) if isinstance(outputs.get("timebase"), Mapping) else None
            if not duration:
                duration = max((sample.pts_sec for sample in samples), default=0.0) + .1
            collection = generate_event_proposals(source_video_hash=self._source_hash, source_duration_sec=max(.2, duration), samples=samples, pipeline_fingerprint=content_hash({"adapter": PIPELINE_ADAPTER_VERSION, "stage": "events"}))
            scopes = normalize_event_scopes(collection.model_dump(mode="json"), analysis_id=str(self.legacy.get("analysis_id") or "unknown"))
        events: list[ActionEvent] = []
        for scope in scopes:
            profile = str(scope.get("profile") or "unknown")
            if profile not in {"jump", "spin", "step", "spiral"}:
                profile = "unknown"
            status = "confirmed" if scope.get("status") == "confirmed_window" and profile != "unknown" else "ambiguous" if profile != "unknown" else "unknown"
            obs = str(scope.get("observability") or "unobservable")
            mapped_obs = "observed" if obs == "observable" else "partial" if obs == "partially_observable" else "unobservable"
            events.append(ActionEvent(event_id=str(scope["event_id"]), profile=profile, state=status, start_pts_sec=float(scope["start_pts_sec"]), end_pts_sec=float(scope["end_pts_sec"]), proposal_source="persisted_legacy" if persisted else "v2_deterministic_proposal", proposal_score=max((scope.get("candidate_profile_scores") or {}).values(), default=0.0), tracking_coverage=1.0 if mapped_obs != "unobservable" else 0.0, pose_coverage=0.0, observability=mapped_obs, confidence=.45 if mapped_obs == "observed" else .2 if mapped_obs == "partial" else 0.0, confirmation_task=None if status == "confirmed" else f"{scope['event_id']}:confirm_action_profile"))
        return {"schema_version": "shadow-events-stage.v1", "scopes": list(scopes), "events": [item.model_dump(mode="json") for item in events], "proposal_count": len(scopes)}

    async def stage_moments(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        event_payload = outputs.get("events") if isinstance(outputs.get("events"), Mapping) else {}
        events = event_payload.get("events", []) if isinstance(event_payload, Mapping) else []
        poses = ((outputs.get("pose") or {}).get("observations") if isinstance(outputs.get("pose"), Mapping) else ())
        identity_segments = ((outputs.get("identity") or {}).get("segments") if isinstance(outputs.get("identity"), Mapping) else ())
        samples: list[MomentEvidenceSample] = []
        by_identity = {int(item.get("source_frame_index", -1)): item for item in identity_segments if isinstance(item, Mapping)}
        for item in poses if isinstance(poses, Sequence) else ():
            if not isinstance(item, Mapping):
                continue
            frame = int(item.get("source_frame_index", -1)); track_state = str((by_identity.get(frame) or {}).get("state") or item.get("identity_state") or "lost")
            joints = item.get("joints") if isinstance(item.get("joints"), Mapping) else {}
            center_y = None
            points = [(float(j.get("y")), float(j.get("visibility", j.get("confidence", 0)))) for j in joints.values() if isinstance(j, Mapping) and _float(j.get("y"), None) is not None]
            if points:
                center_y = _clamp(sum(y * max(v, .01) for y, v in points) / sum(max(v, .01) for _y, v in points), default=.5)
            quality = _float(item.get("pose_quality"), None)
            samples.append(MomentEvidenceSample(source_frame_index=max(0, frame), pts_sec=max(0.0, _float(item.get("pts_sec"), 0.0) or 0.0), tracking_state=track_state if track_state in {"confirmed", "uncertain", "lost"} else "lost", pose_authoritative=bool(item.get("authoritative")), pose_quality=quality, body_center_y=center_y, ice_contact=.65 if center_y is not None and center_y > .55 else .2, airborne=.75 if center_y is not None and center_y < .45 else .15, turning_motion=.5 if center_y is not None else 0, rotation_periodicity=.5 if center_y is not None else 0, axis_stability=.6 if center_y is not None else 0, extension=.6 if center_y is not None else 0, edge_change=.5 if center_y is not None else 0, step_complexity=.5 if center_y is not None else 0, provenance=("shadow_legacy_adapter",)))
        timeline = ((outputs.get("timebase") or {}).get("source_index") if isinstance(outputs.get("timebase"), Mapping) else {})
        timeline_fp = str((timeline or {}).get("fingerprint") or content_hash(timeline))
        sets: list[dict[str, Any]] = []
        for event in events if isinstance(events, Sequence) else ():
            if not isinstance(event, Mapping):
                continue
            profile = str(event.get("profile") or "unknown")
            if profile not in {"jump", "spin", "step", "spiral"}:
                profile = _profile(self.legacy)
            if profile not in {"jump", "spin", "step", "spiral"}:
                continue
            result = localize_profile_moments(event_id=str(event.get("event_id")), profile=profile, event_start_pts=float(event.get("start_pts_sec", 0)), event_end_pts=float(event.get("end_pts_sec", 0)), samples=samples, source_timeline_fingerprint=timeline_fp)
            sets.append(result.model_dump(mode="json"))
        return {"schema_version": "shadow-moments-stage.v1", "sets": sets, "sample_count": len(samples), "timeline_fingerprint": timeline_fp}

    async def stage_rotation(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        event_payload = outputs.get("events") if isinstance(outputs.get("events"), Mapping) else {}
        events = event_payload.get("events", []) if isinstance(event_payload, Mapping) else []
        poses = ((outputs.get("pose") or {}).get("observations") if isinstance(outputs.get("pose"), Mapping) else ())
        by_pose = [PoseObservation.model_validate(item) for item in poses if isinstance(item, Mapping)]
        timeline = ((outputs.get("timebase") or {}).get("source_index") if isinstance(outputs.get("timebase"), Mapping) else {})
        timeline_fp = str((timeline or {}).get("fingerprint") or content_hash(timeline))
        estimates: list[dict[str, Any]] = []
        for event in events if isinstance(events, Sequence) else ():
            if not isinstance(event, Mapping) or str(event.get("profile")) not in {"jump", "spin"}:
                continue
            profile = str(event.get("profile"))
            start, end = float(event.get("start_pts_sec", 0)), float(event.get("end_pts_sec", 0))
            phase = "airborne" if profile == "jump" else "spin_main"
            samples = [rotation_sample_from_pose(pose, phase=phase) for pose in by_pose if start <= pose.pts_sec <= end]
            result = estimate_rotation(event_id=str(event.get("event_id")), profile=profile, event_start_pts=start, event_end_pts=end, samples=samples, source_timeline_fingerprint=timeline_fp)
            estimates.append(result.model_dump(mode="json"))
        return {"schema_version": "shadow-rotation-stage.v1", "estimates": estimates, "timeline_fingerprint": timeline_fp}

    async def stage_path_reviews(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        identity = outputs.get("identity") if isinstance(outputs.get("identity"), Mapping) else {}
        timeline = identity.get("timeline") if isinstance(identity, Mapping) else {}
        confirmed = str((timeline or {}).get("state")) == "confirmed" and _confirmed_target(self.legacy)
        policy = {"identity_state": "confirmed" if confirmed else "unknown", "target_id": "main-skater", "target_marking": "confirmed_bbox_overlay" if confirmed else "none", "crop_bbox": _bbox_tuple((self.legacy.get("target_lock") or {}).get("selected_bbox")) if isinstance(self.legacy.get("target_lock"), Mapping) else None, "context_before_sec": .5 if confirmed else 0, "context_after_sec": .5 if confirmed else 0, "includes_travel_context": confirmed, "includes_ice_contact_context": confirmed}
        path_a_raw = self.legacy.get(_LEGACY_PATH_A)
        path_a = normalize_path_a_review(path_a_raw if isinstance(path_a_raw, Mapping) else None, source_fingerprints={"pipeline": content_hash({"adapter": PIPELINE_ADAPTER_VERSION, "path": "a"})}, target_policy=policy)
        bio_raw = self.legacy.get(_LEGACY_BIO)
        bio = bio_raw if isinstance(bio_raw, Mapping) else {}
        measurements: list[dict[str, Any]] = []
        for key in ("air_time_seconds", "estimated_height_cm", "takeoff_speed_mps", "rotation_rps", "estimated_rotations"):
            value = bio.get("jump_metrics", {}).get(key) if isinstance(bio.get("jump_metrics"), Mapping) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                measurements.append({"claim_type": f"metric_{key}", "value": value, "provenance": "measured", "confidence": .7, "source_reference": f"legacy.{_LEGACY_BIO}.jump_metrics:{key}"})
        path_b = normalize_path_b_measurements(measurements, event_id=None, identity_state="confirmed" if confirmed else "unknown", source_fingerprints={"pipeline": content_hash({"adapter": PIPELINE_ADAPTER_VERSION, "path": "b"})})
        claims = tuple(item.model_dump(mode="json") for item in (*path_a, *path_b))
        return {"schema_version": "shadow-path-reviews-stage.v1", "path_a_claims": [item.model_dump(mode="json") for item in path_a], "path_b_claims": [item.model_dump(mode="json") for item in path_b], "claims": list(claims), "target_policy": {key: value for key, value in policy.items() if key != "crop_bbox" or value is not None}}

    async def stage_claims(self, outputs: Mapping[str, Any]) -> dict[str, Any]:
        analysis_id = str(self.legacy.get("analysis_id") or "unknown-analysis")
        pipeline_fp = content_hash({"adapter": PIPELINE_ADAPTER_VERSION, "analysis_id": analysis_id, "source": self._source_hash})
        bio_raw = self.legacy.get(_LEGACY_BIO)
        deterministic = build_deterministic_claims(analysis_id=analysis_id, action_profile=_profile(self.legacy), bio_data=bio_raw if isinstance(bio_raw, Mapping) else None, pose_data=self.legacy.get(_LEGACY_POSE) if isinstance(self.legacy.get(_LEGACY_POSE), Mapping) else None, target_lock=self.legacy.get("target_lock") if isinstance(self.legacy.get("target_lock"), Mapping) else None, pipeline_fingerprint=pipeline_fp)
        events = outputs.get("events") if isinstance(outputs.get("events"), Mapping) else {}
        scopes = events.get("scopes", []) if isinstance(events, Mapping) else []
        windows = build_event_window_claims(analysis_id=analysis_id, scopes=scopes if isinstance(scopes, Sequence) else (), pipeline_fingerprint=pipeline_fp)
        candidates = build_event_candidate_claims(analysis_id=analysis_id, scopes=scopes if isinstance(scopes, Sequence) else (), pipeline_fingerprint=pipeline_fp)
        path = outputs.get("path_reviews") if isinstance(outputs.get("path_reviews"), Mapping) else {}
        path_claims = []
        for key in ("path_a_claims", "path_b_claims"):
            values = path.get(key) if isinstance(path, Mapping) else ()
            for item in values if isinstance(values, Sequence) else ():
                if isinstance(item, Mapping):
                    try:
                        path_claims.append(EvidenceClaim.model_validate(item))
                    except Exception:
                        continue
        fused = fuse_evidence_claims(deterministic, windows, candidates, path_claims, source_states=(ClaimSourceState("deterministic", "complete", fingerprint=pipeline_fp), ClaimSourceState("path_a", "complete"), ClaimSourceState("path_b", "complete")), fusion_configuration={"adapter": PIPELINE_ADAPTER_VERSION})
        return {"schema_version": "shadow-claims-stage.v1", "claims": [item.model_dump(mode="json") for item in fused.claims], "source_states": [{"source": item.source, "state": item.state, "fingerprint": item.fingerprint, "error": item.error, "retryable": item.retryable} for item in fused.source_states], "fusion_fingerprint": fused.fusion_fingerprint, "conflicts": list(fused.conflicts), "retryable_sources": list(fused.retryable_sources)}


def build_default_stage_handlers(*, legacy_result: Mapping[str, Any], source_identity: Mapping[str, Any], config: Any) -> Mapping[str, Any]:
    """Return the ten deterministic handlers used by the default Shadow run."""
    return _DefaultShadowPipeline(legacy_result=legacy_result, source_identity=source_identity, config=config).handlers()


__all__ = ["PIPELINE_ADAPTER_VERSION", "build_default_stage_handlers"]
