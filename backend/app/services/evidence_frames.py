from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.services.video import extract_precise_frames_at_timestamps


EVIDENCE_SCHEMA_VERSION = "evidence_frames.v1"
CORE_MOMENT_BY_PHASE = {"takeoff": "T", "air": "A", "landing": "L"}
REQUIRED_PHASES = {
    "jump": ("takeoff", "air", "landing"),
    "spin": ("spin_entry", "spin_main", "spin_exit"),
    "spiral": ("spiral_entry", "spiral_hold", "spiral_exit"),
    "step": ("step_sequence",),
}


@dataclass(frozen=True, slots=True)
class EvidenceFrame:
    """A timestamped evidence request retained independently for each source."""

    timestamp: float
    source: str
    phase: str | None
    confidence: float | None
    selection_reason: str
    frame_id: str | None = None
    group_id: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "timestamp": round(self.timestamp, 3),
            "source": self.source,
            "phase": self.phase,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "selection_reason": self.selection_reason,
            "frame_id": self.frame_id,
            "group_id": self.group_id or self.source,
        }


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _profile(value: object) -> str:
    return str(value or "").strip().lower()


def _phase_for_moment(key: str) -> str | None:
    return {"T_takeoff_sec": "takeoff", "A_air_sec": "air", "L_landing_sec": "landing"}.get(key)


def _record_from_mapping(
    item: dict[str, Any],
    *,
    source: str,
    reason: str,
    group_id: str | None = None,
) -> EvidenceFrame | None:
    timestamp = _number(item.get("timestamp"))
    if timestamp is None or timestamp < 0:
        return None
    confidence = _number(item.get("confidence"))
    phase = str(item.get("phase_code") or item.get("phase") or "").strip() or None
    return EvidenceFrame(
        timestamp=timestamp,
        source=source,
        phase=phase,
        confidence=confidence,
        selection_reason=reason,
        frame_id=str(item.get("frame_id") or "").strip() or None,
        group_id=group_id,
    )


def _neighbors(center: float, *, source_fps: float, radius_frames: int = 1) -> Iterable[float]:
    interval = 1 / max(source_fps, 1.0)
    for offset in range(-radius_frames, radius_frames + 1):
        yield max(0.0, center + offset * interval)


def _temporal_evidence(video_temporal: dict[str, Any] | None, *, source_fps: float) -> list[EvidenceFrame]:
    if not isinstance(video_temporal, dict):
        return []
    evidence: list[EvidenceFrame] = []
    confidence = _number(video_temporal.get("confidence"))
    for segment in video_temporal.get("phase_segments", []):
        if not isinstance(segment, dict):
            continue
        phase = str(segment.get("phase_code") or "").strip() or None
        center = _number(segment.get("key_frame_hint"))
        if center is None:
            start, end = _number(segment.get("time_start")), _number(segment.get("time_end"))
            center = (start + end) / 2 if start is not None and end is not None else None
        if center is None or center < 0:
            continue
        item_confidence = _number(segment.get("confidence")) or confidence
        for timestamp in _neighbors(center, source_fps=source_fps):
            evidence.append(EvidenceFrame(timestamp, "mimo_phase", phase, item_confidence, "mimo_phase_window", group_id="mimo"))
    key_moments = video_temporal.get("key_moments")
    if isinstance(key_moments, dict):
        for key in ("T_takeoff_sec", "A_air_sec", "L_landing_sec"):
            center = _number(key_moments.get(key))
            if center is None or center < 0:
                continue
            for timestamp in _neighbors(center, source_fps=source_fps):
                evidence.append(EvidenceFrame(timestamp, "mimo_key_moment", _phase_for_moment(key), confidence, "mimo_key_moment_window", group_id="mimo"))
    retry = video_temporal.get("retry_attempt")
    if isinstance(retry, dict):
        for item in _temporal_evidence(retry, source_fps=source_fps):
            evidence.append(EvidenceFrame(item.timestamp, "mimo_retry", item.phase, item.confidence, item.selection_reason, group_id="mimo_retry"))
    return evidence


def _pose_evidence(bio_data: dict[str, Any] | None) -> list[EvidenceFrame]:
    candidates = bio_data.get("key_frame_candidates") if isinstance(bio_data, dict) else None
    if not isinstance(candidates, dict):
        return []
    evidence: list[EvidenceFrame] = []
    for key, phase in (("T", "takeoff"), ("A", "air"), ("L", "landing")):
        candidate = candidates.get(key)
        if not isinstance(candidate, dict):
            continue
        timestamp = _number(candidate.get("timestamp"))
        if timestamp is None or timestamp < 0:
            continue
        evidence.append(
            EvidenceFrame(
                timestamp,
                "pose_candidate",
                phase,
                _number(candidate.get("confidence")),
                "pose_tal_candidate",
                str(candidate.get("frame_id") or "").strip() or None,
                "pose",
            )
        )
    return evidence


def _coverage_diagnostics(
    evidence: Sequence[EvidenceFrame],
    *,
    analysis_profile: str | None,
    window_start: float,
    window_end: float,
) -> dict[str, object]:
    required = REQUIRED_PHASES.get(_profile(analysis_profile), ())
    phase_records = {phase: [item for item in evidence if item.phase == phase] for phase in required}
    timestamps = sorted({round(item.timestamp, 3) for item in evidence if window_start <= item.timestamp <= window_end})
    duration = max(window_end - window_start, 0.001)
    largest_gap = max((right - left for left, right in zip([window_start, *timestamps], [*timestamps, window_end])), default=duration)
    # Coverage represents the span observed in the analyzed window; it avoids pretending that
    # three clustered T/A/L frames cover a long action window.
    coverage_ratio = (
        min(1.0, (max(timestamps) - min(timestamps)) / duration)
        if timestamps
        else 0.0
    )
    tal = {CORE_MOMENT_BY_PHASE[item.phase]: item.timestamp for item in evidence if item.phase in CORE_MOMENT_BY_PHASE}
    tal_ordered = all(key in tal for key in ("T", "A", "L")) and tal["T"] < tal["A"] < tal["L"]
    return {
        "analysis_window": {"start_sec": round(window_start, 3), "end_sec": round(window_end, 3)},
        "coverage_ratio": round(coverage_ratio, 3),
        "largest_time_gap_sec": round(largest_gap, 3),
        "required_stages": list(required),
        "required_stage_completeness": all(phase_records.values()) if required else True,
        "missing_stages": [phase for phase, records in phase_records.items() if not records],
        "per_stage_counts": {phase: len(records) for phase, records in phase_records.items()},
        "tal_ordered": tal_ordered,
        "source_diversity": len({item.source for item in evidence}),
    }


def build_evidence_frames(
    motion_scores: dict[str, Any] | None,
    *,
    video_temporal: dict[str, Any] | None,
    resolved_keyframes: dict[str, Any] | None,
    bio_data: dict[str, Any] | None,
    analysis_profile: str | None,
    source_fps: float,
) -> dict[str, object]:
    """Build a versioned, non-destructive evidence ledger for temporal diagnostics."""
    motion_scores = motion_scores if isinstance(motion_scores, dict) else {}
    evidence: list[EvidenceFrame] = []
    for item in motion_scores.get("selected", []):
        if isinstance(item, dict):
            record = _record_from_mapping(item, source="motion_sample", reason="base_motion_sample", group_id="motion")
            if record is not None:
                evidence.append(record)
    evidence.extend(_temporal_evidence(video_temporal, source_fps=source_fps))
    if isinstance(resolved_keyframes, dict):
        for item in resolved_keyframes.get("selected", []):
            if isinstance(item, dict):
                record = _record_from_mapping(item, source="resolved_semantic", reason="resolved_semantic_keyframe", group_id="resolved")
                if record is not None:
                    evidence.append(record)
        for item in resolved_keyframes.get("partial_selected", []):
            if isinstance(item, dict):
                record = _record_from_mapping(item, source="partial_semantic", reason="partial_semantic_keyframe", group_id="resolved")
                if record is not None:
                    evidence.append(record)
    evidence.extend(_pose_evidence(bio_data))

    window_start = _number(motion_scores.get("window_start")) or 0.0
    window_end = _number(motion_scores.get("window_end")) or window_start
    diagnostics = _coverage_diagnostics(evidence, analysis_profile=analysis_profile, window_start=window_start, window_end=window_end)
    # Missing phases receive one bounded three-frame retry window, preserving all original groups.
    retry_requests: list[EvidenceFrame] = []
    if diagnostics["missing_stages"]:
        for item in evidence:
            if item.source.startswith("mimo") and item.phase in diagnostics["missing_stages"]:
                for timestamp in _neighbors(item.timestamp, source_fps=source_fps, radius_frames=2):
                    retry_requests.append(EvidenceFrame(timestamp, "coverage_retry", item.phase, item.confidence, "missing_stage_expansion", group_id="coverage_retry"))
    evidence.extend(retry_requests)
    diagnostics = _coverage_diagnostics(evidence, analysis_profile=analysis_profile, window_start=window_start, window_end=window_end)
    diagnostics["stage_evidence_insufficient"] = bool(diagnostics["missing_stages"])
    diagnostics["supplemental_retry_requested"] = bool(retry_requests)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "dedupe_tolerance_sec": round(1 / max(source_fps, 1.0), 4),
        "records": [item.to_payload() for item in sorted(evidence, key=lambda record: (record.timestamp, record.source, record.phase or ""))],
        "diagnostics": diagnostics,
    }


async def materialize_supplemental_evidence_frames(
    video_path: Path,
    frames_dir: Path,
    evidence_payload: dict[str, object],
    *,
    base_records: Sequence[dict[str, object]],
    source_fps: float,
) -> list[dict[str, object]]:
    """Extract non-base temporal evidence once per timestamp into semantic_frames/."""
    raw_records = evidence_payload.get("records") if isinstance(evidence_payload.get("records"), list) else []
    tolerance = 1 / max(source_fps, 1.0)
    base_timestamps = {
        timestamp
        for item in base_records
        if isinstance(item, dict)
        for timestamp in [_number(item.get("timestamp"))]
        if timestamp is not None
    }
    requested: list[dict[str, object]] = []
    selected_timestamps: list[float] = []
    for item in raw_records:
        if not isinstance(item, dict) or str(item.get("source") or "") == "motion_sample":
            continue
        timestamp = _number(item.get("timestamp"))
        if timestamp is None or any(abs(timestamp - base) <= tolerance for base in base_timestamps):
            continue
        if any(abs(timestamp - selected) <= tolerance for selected in selected_timestamps):
            continue
        selected_timestamps.append(timestamp)
        requested.append(
            {
                "timestamp": round(timestamp, 3),
                "phase_code": item.get("phase"),
                "confidence": item.get("confidence"),
                "selection_reason": item.get("selection_reason"),
                "evidence_source": item.get("source"),
                "evidence_group_id": item.get("group_id"),
            }
        )
    if not requested:
        evidence_payload["supplemental_frames"] = []
        return []
    _, records = await extract_precise_frames_at_timestamps(video_path, frames_dir, requested, prefix="evidence")
    evidence_payload["supplemental_frames"] = records
    return records
