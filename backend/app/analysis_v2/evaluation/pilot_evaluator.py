from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis_v2.evaluation.golden_schema import GoldenDatasetV2, NormalizedBBox


EVALUATOR_VERSION = "golden-pilot-evaluator.v1"
PTS_TOLERANCE_SEC = 0.001
EvaluationMask = Literal["tracking", "action", "key_moments", "rotation", "pose"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PredictionFrameKey(_StrictModel):
    source_frame_index: int = Field(ge=0)
    pts: float = Field(ge=0)


class TrackPrediction(PredictionFrameKey):
    state: Literal["confirmed", "uncertain", "lost"]
    identity: Literal["target", "wrong_person", "unknown"] = "unknown"
    bbox: NormalizedBBox | None = None
    false_relock: bool = False

    @model_validator(mode="after")
    def confirmed_requires_box(self) -> "TrackPrediction":
        if self.state == "confirmed" and self.bbox is None:
            raise ValueError("confirmed tracking predictions require a bbox")
        return self


class MomentPrediction(PredictionFrameKey):
    key: str = Field(min_length=1, max_length=64)
    observability: Literal["observable", "uncertain", "unobservable"] = "observable"


class RotationPrediction(_StrictModel):
    turns: float | None = Field(default=None, ge=0, le=12)
    rotation_class: str | None = Field(default=None, max_length=64)
    observability: Literal["observable", "uncertain", "unobservable"]
    confidence: float = Field(ge=0, le=1)
    refusal_reason: str | None = Field(default=None, max_length=160)


class PoseJointPrediction(_StrictModel):
    joint: str = Field(min_length=1, max_length=64)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    source: Literal["measured", "smoothed", "interpolated", "missing"]


class PosePrediction(PredictionFrameKey):
    identity: Literal["target", "wrong_person", "unknown"] = "unknown"
    joints: list[PoseJointPrediction] = Field(default_factory=list, max_length=64)


class EventPrediction(_StrictModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str = Field(min_length=1, max_length=128)
    proposal_start_pts: float | None = Field(default=None, ge=0)
    proposal_end_pts: float | None = Field(default=None, ge=0)
    predicted_profile: Literal["jump", "spin", "step", "spiral", "unknown"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    tracks: list[TrackPrediction] = Field(default_factory=list, max_length=100_000)
    moments: list[MomentPrediction] = Field(default_factory=list, max_length=32)
    rotation: RotationPrediction | None = None
    poses: list[PosePrediction] = Field(default_factory=list, max_length=10_000)
    input_fields: list[str] = Field(default_factory=list, max_length=256)
    input_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def proposal_is_ordered(self) -> "EventPrediction":
        if (self.proposal_start_pts is None) != (self.proposal_end_pts is None):
            raise ValueError("proposal start and end must be provided together")
        if self.proposal_start_pts is not None and self.proposal_end_pts <= self.proposal_start_pts:
            raise ValueError("proposal end must follow proposal start")
        return self


class PilotPredictionBundle(_StrictModel):
    schema_version: Literal["golden-pilot-predictions.v1"] = "golden-pilot-predictions.v1"
    pipeline_fingerprint: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]+$")
    evaluation_masks: list[EvaluationMask] = Field(min_length=1, max_length=5)
    predictions: list[EventPrediction] = Field(default_factory=list, max_length=2_000)

    @model_validator(mode="after")
    def masks_and_events_are_unique(self) -> "PilotPredictionBundle":
        if len(self.evaluation_masks) != len(set(self.evaluation_masks)):
            raise ValueError("evaluation masks must be unique")
        keys = [(item.source_sha256, item.event_id) for item in self.predictions]
        if len(keys) != len(set(keys)):
            raise ValueError("prediction event identities must be unique")
        return self


class EvaluationLeakageError(ValueError):
    def __init__(self, fields: list[str]) -> None:
        super().__init__("Golden fields under evaluation were present in prediction inputs")
        self.fields = fields


def canonical_fingerprint(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def wilson_interval(numerator: int, denominator: int) -> list[float] | None:
    if denominator <= 0:
        return None
    z = 1.959963984540054
    p = numerator / denominator
    scale = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / scale
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * denominator)) / denominator) / scale
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
        "confidence_interval_95": wilson_interval(numerator, denominator),
    }


def evaluate_pilot(dataset: GoldenDatasetV2, bundle: PilotPredictionBundle) -> tuple[dict[str, Any], dict[str, Any]]:
    leaked = _leakage_fields(bundle)
    if leaked:
        raise EvaluationLeakageError(leaked)

    masks = set(bundle.evaluation_masks)
    events = sorted(dataset.events, key=lambda item: (item.source_sha256, item.event_id))
    predictions = {(item.source_sha256, item.event_id): item for item in bundle.predictions}
    tracks_by_event: dict[tuple[str, str], list[Any]] = defaultdict(list)
    poses_by_event: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for item in dataset.tracks:
        tracks_by_event[(item.source_sha256, item.event_id)].append(item)
    for item in dataset.poses:
        poses_by_event[(item.source_sha256, item.event_id)].append(item)

    diagnostics: list[dict[str, Any]] = []
    for event in events:
        key = (event.source_sha256, event.event_id)
        prediction = predictions.get(key)
        metrics: dict[str, Any] = {}
        failures: list[str] = []
        if "tracking" in masks:
            metrics["tracking"] = _tracking_metrics(tracks_by_event[key], prediction)
            failures.extend(metrics["tracking"].pop("failure_codes"))
        if "action" in masks:
            metrics["action"] = _action_metrics(event, prediction)
            failures.extend(metrics["action"].pop("failure_codes"))
        if "key_moments" in masks:
            metrics["key_moments"] = _moment_metrics(event, prediction)
            failures.extend(metrics["key_moments"].pop("failure_codes"))
        if "rotation" in masks:
            metrics["rotation"] = _rotation_metrics(event, prediction)
            failures.extend(metrics["rotation"].pop("failure_codes"))
        if "pose" in masks:
            metrics["pose"] = _pose_metrics(poses_by_event[key], tracks_by_event[key], prediction)
            failures.extend(metrics["pose"].pop("failure_codes"))
        diagnostics.append(
            {
                "source_sha256": event.source_sha256,
                "event_id": event.event_id,
                "source_pts": event.start_pts,
                "profile": event.profile,
                "strata": sorted(set(event.strata)) or ["unspecified"],
                "metrics": metrics,
                "failure_codes": sorted(set(failures)),
            }
        )

    aggregate = _aggregate(diagnostics, masks)
    dataset_fingerprint = canonical_fingerprint(_canonical_dataset(dataset))
    result_fingerprint = canonical_fingerprint(
        {
            "evaluator_version": EVALUATOR_VERSION,
            "dataset_fingerprint": dataset_fingerprint,
            "pipeline_fingerprint": bundle.pipeline_fingerprint,
            "evaluation_masks": sorted(masks),
            "aggregate": aggregate,
            "diagnostics": diagnostics,
        }
    )
    private = {
        "schema_version": "golden-pilot-private-report.v1",
        "evaluator_version": EVALUATOR_VERSION,
        "dataset_fingerprint": dataset_fingerprint,
        "pipeline_fingerprint": bundle.pipeline_fingerprint,
        "evaluation_masks": sorted(masks),
        "deterministic_fingerprint": result_fingerprint,
        "repeatability": {"deterministic": True, "fingerprint": result_fingerprint},
        "aggregate": aggregate,
        "events": diagnostics,
    }
    aliases = {item["event_id"]: f"event-{index:03d}" for index, item in enumerate(diagnostics, 1)}
    public_diagnostics = [
        {**item, "strata": sorted({_public_stratum(value) for value in item["strata"]})}
        for item in diagnostics
    ]
    sanitized_aggregate = _aggregate(public_diagnostics, masks)
    sanitized = {
        "schema_version": "golden-pilot-sanitized-report.v1",
        "evaluator_version": EVALUATOR_VERSION,
        "dataset_id": dataset.dataset_id,
        "dataset_fingerprint": dataset_fingerprint,
        "pipeline_fingerprint": bundle.pipeline_fingerprint,
        "evaluation_masks": sorted(masks),
        "diagnostic_only": True,
        "release_claim": False,
        "deterministic_fingerprint": result_fingerprint,
        "repeatability": {"deterministic": True, "fingerprint": result_fingerprint},
        "aggregate": sanitized_aggregate,
        "failed_events": [
            {
                "alias": aliases[item["event_id"]],
                "profile": item["profile"],
                "strata": item["strata"],
                "failure_codes": item["failure_codes"],
            }
            for item in public_diagnostics
            if item["failure_codes"]
        ],
    }
    return private, sanitized


def _public_stratum(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "normal": {"normal", "single", "single-skater", "clear"},
        "multi-skater": {"multi-skater", "crowd"},
        "crossing/occlusion": {"crossing", "occlusion", "crossing/occlusion"},
        "small/distant target": {"small", "distant", "small/distant", "small/distant target"},
        "pan/zoom": {"pan", "zoom", "pan/zoom"},
        "blur/compression": {"blur", "compression", "blur/compression"},
    }
    return next((key for key, values in aliases.items() if normalized in values), "other")


def _leakage_fields(bundle: PilotPredictionBundle) -> list[str]:
    forbidden = {
        "tracking": ("golden.track", "golden.bbox", "label.track", "label.bbox"),
        "action": ("golden.profile", "golden.event", "label.profile", "label.event"),
        "key_moments": ("golden.takeoff", "golden.apex", "golden.landing", "golden.t", "golden.a", "golden.l", "label.takeoff", "label.apex", "label.landing"),
        "rotation": ("golden.rotation", "golden.turn", "label.rotation", "label.turn"),
        "pose": ("golden.pose", "golden.joint", "label.pose", "label.joint"),
    }
    active = [needle for mask in bundle.evaluation_masks for needle in forbidden[mask]]
    hits: set[str] = set()
    for prediction in bundle.predictions:
        fields = [str(item).lower() for item in prediction.input_fields]
        fields.extend(_leaf_paths(prediction.input_payload))
        for field in fields:
            normalized = field.lower().replace("[", ".").replace("]", "")
            if any(normalized == needle or normalized.startswith(f"{needle}.") for needle in active):
                hits.add(field)
    return sorted(hits)


def _leaf_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_leaf_paths(child, path))
        return paths
    if isinstance(value, list):
        return [path for index, child in enumerate(value) for path in _leaf_paths(child, f"{prefix}.{index}")]
    return [prefix]


def _canonical_dataset(dataset: GoldenDatasetV2) -> dict[str, Any]:
    payload = dataset.model_dump(mode="json")
    payload["sources"] = sorted(payload["sources"], key=lambda item: item["source_sha256"])
    payload["events"] = sorted(payload["events"], key=lambda item: (item["source_sha256"], item["event_id"]))
    payload["tracks"] = sorted(
        payload["tracks"],
        key=lambda item: (item["source_sha256"], item["event_id"], item.get("source_frame_index", -1), item["pts"], item["label_id"]),
    )
    payload["poses"] = sorted(
        payload["poses"],
        key=lambda item: (item["source_sha256"], item["event_id"], item.get("source_frame_index", -1), item["pts"], item["label_id"]),
    )
    return payload


def _bbox_iou(left: NormalizedBBox, right: NormalizedBBox) -> float:
    ix1, iy1 = max(left.left, right.left), max(left.top, right.top)
    ix2, iy2 = min(left.right, right.right), min(left.bottom, right.bottom)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (left.right - left.left) * (left.bottom - left.top) + (right.right - right.left) * (right.bottom - right.top) - intersection
    return intersection / union if union else 0.0


def _match_by_frame(items: list[Any], frame_index: int | None, pts: float) -> Any | None:
    if frame_index is None:
        return None
    return next(
        (item for item in items if item.source_frame_index == frame_index and abs(item.pts - pts) <= PTS_TOLERANCE_SEC),
        None,
    )


def _tracking_metrics(labels: list[Any], prediction: EventPrediction | None) -> dict[str, Any]:
    predicted = prediction.tracks if prediction else []
    counts: Counter[str] = Counter()
    ious: list[float] = []
    missing_pts: list[float] = []
    for label in sorted(labels, key=lambda item: (item.pts, item.source_frame_index or -1)):
        item = _match_by_frame(predicted, label.source_frame_index, label.pts)
        if item is None:
            counts["lost"] += 1
            counts["missing_prediction"] += 1
            missing_pts.append(label.pts)
        elif item.false_relock or item.identity == "wrong_person":
            counts["wrong_person"] += 1
            if item.false_relock:
                counts["false_relock"] += 1
        elif item.state == "lost":
            counts["lost"] += 1
            missing_pts.append(label.pts)
        elif item.state == "uncertain" or item.identity == "unknown":
            counts["uncertain"] += 1
        else:
            iou = _bbox_iou(label.bbox, item.bbox)
            ious.append(iou)
            counts["confirmed"] += 1
            if iou >= 0.5:
                counts["correct"] += 1
            else:
                counts["low_iou"] += 1
    denominator = len(labels)
    failures = []
    if counts["missing_prediction"]:
        failures.append("tracking_missing_prediction")
    if counts["wrong_person"]:
        failures.append("tracking_wrong_person")
    if counts["false_relock"]:
        failures.append("tracking_false_relock")
    if counts["low_iou"]:
        failures.append("tracking_low_iou")
    return {
        "denominator": denominator,
        "confirmed_coverage": rate(counts["confirmed"], denominator),
        "uncertain_coverage": rate(counts["uncertain"], denominator),
        "lost_coverage": rate(counts["lost"], denominator),
        "correct_localization": rate(counts["correct"], denominator),
        "wrong_person": rate(counts["wrong_person"], denominator),
        "false_relock": rate(counts["false_relock"], denominator),
        "low_iou": rate(counts["low_iou"], denominator),
        "missing_predictions": counts["missing_prediction"],
        "mean_iou": round(statistics.fmean(ious), 6) if ious else None,
        "longest_missing_sec": _longest_gap(missing_pts),
        "failure_codes": failures,
    }


def _longest_gap(points: list[float]) -> float:
    if not points:
        return 0.0
    ordered = sorted(points)
    if len(ordered) == 1:
        return 0.0
    gaps = [ordered[index] - ordered[start] for start in range(len(ordered)) for index in range(start, len(ordered)) if all(ordered[n + 1] - ordered[n] <= 0.25 for n in range(start, index))]
    return round(max(gaps, default=0.0), 6)


def _action_metrics(event: Any, prediction: EventPrediction | None) -> dict[str, Any]:
    proposal = False
    if prediction and prediction.proposal_start_pts is not None:
        intersection = max(0.0, min(event.end_pts, prediction.proposal_end_pts) - max(event.start_pts, prediction.proposal_start_pts))
        proposal = intersection / max(event.end_pts - event.start_pts, 1e-9) >= 0.5
    predicted = prediction.predicted_profile if prediction and prediction.predicted_profile else "missing"
    correct = predicted == event.profile
    failures = []
    if not proposal:
        failures.append("action_proposal_missed")
    if not correct:
        failures.append("action_class_wrong" if predicted != "missing" else "action_prediction_missing")
    return {
        "proposal_recall": rate(int(proposal), 1),
        "class_accuracy": rate(int(correct), 1),
        "actual_profile": event.profile,
        "predicted_profile": predicted,
        "rejected": predicted in {"unknown", "missing"},
        "failure_codes": failures,
    }


def _golden_moments(event: Any) -> list[tuple[str, Any]]:
    if event.jump:
        return [(key, value) for key, value in (("takeoff", event.jump.takeoff), ("apex", event.jump.apex), ("landing", event.jump.landing)) if value]
    if event.spin:
        return [
            (key, type("Moment", (), {"pts": pts, "source_frame_index": None})())
            for key, pts in (
                ("entry_start", event.spin.entry.start_pts if event.spin.entry else None),
                ("main_start", event.spin.main.start_pts if event.spin.main else None),
                ("exit_end", event.spin.exit.end_pts if event.spin.exit else None),
            )
            if pts is not None
        ]
    detail = event.step or event.spiral
    return [("representative", detail.representative_moment)] if detail and detail.representative_moment else []


def _moment_metrics(event: Any, prediction: EventPrediction | None) -> dict[str, Any]:
    labels = _golden_moments(event)
    predicted = {item.key: item for item in prediction.moments} if prediction else {}
    errors: list[float] = []
    exact_frames = 0
    frame_denominator = 0
    missing = 0
    details: list[dict[str, Any]] = []
    for key, label in labels:
        item = predicted.get(key)
        if item is None:
            missing += 1
            details.append({"key": key, "error_sec": None, "source_frame_match": False})
            continue
        error = abs(item.pts - label.pts)
        errors.append(error)
        has_frame_identity = label.source_frame_index is not None
        frame_match = has_frame_identity and item.source_frame_index == label.source_frame_index
        frame_denominator += int(has_frame_identity)
        exact_frames += int(frame_match)
        details.append({"key": key, "error_sec": round(error, 6), "source_frame_match": frame_match})
    denominator = len(labels)
    return {
        "timing_coverage": rate(denominator - missing, denominator),
        "within_0_10_sec": rate(sum(value <= 0.10 for value in errors), denominator),
        "source_frame_accuracy": rate(exact_frames, frame_denominator),
        "mean_absolute_error_sec": round(statistics.fmean(errors), 6) if errors else None,
        "median_absolute_error_sec": round(statistics.median(errors), 6) if errors else None,
        "max_absolute_error_sec": round(max(errors), 6) if errors else None,
        "moments": details,
        "failure_codes": (["key_moment_prediction_missing"] if missing else []) + (["key_moment_timing_error"] if any(value > 0.25 for value in errors) else []),
    }


def _rotation_label(event: Any) -> Any | None:
    return event.jump.rotation if event.jump else event.spin.rotation if event.spin else None


def _rotation_class(turns: float | None) -> str | None:
    return None if turns is None else f"{round(turns * 2) / 2:g}"


def _rotation_metrics(event: Any, prediction: EventPrediction | None) -> dict[str, Any]:
    label = _rotation_label(event)
    if label is None:
        return {"applicable": False, "failure_codes": []}
    item = prediction.rotation if prediction else None
    observable = label.observability == "observable"
    refused = item is None or item.turns is None or item.observability != "observable"
    correct_refusal = not observable and refused
    reference = label.reported_turns if label.reported_turns is not None else (label.observed_turns_min + label.observed_turns_max) / 2
    error = abs(item.turns - reference) if observable and item and item.turns is not None else None
    expected_class = _rotation_class(reference)
    predicted_class = item.rotation_class or _rotation_class(item.turns) if item else None
    class_correct = observable and predicted_class == expected_class
    confidently_wrong = bool(observable and item and item.confidence >= 0.8 and (error is None or error > 0.25 or not class_correct))
    failures = []
    if observable and refused:
        failures.append("rotation_wrong_refusal")
    if confidently_wrong:
        failures.append("rotation_confidently_wrong")
    if not observable and item and item.turns is not None and item.confidence >= 0.8:
        failures.append("rotation_should_refuse")
    return {
        "applicable": True,
        "observable": observable,
        "prediction_coverage": rate(int(not refused), 1),
        "class_accuracy": rate(int(class_correct), 1 if observable else 0),
        "absolute_error_turns": round(error, 6) if error is not None else None,
        "confidently_wrong": rate(int(confidently_wrong), 1 if observable else 0),
        "refusal_quality": rate(int(correct_refusal), 1 if not observable else 0),
        "refused": refused,
        "failure_codes": failures,
    }


def _pose_metrics(labels: list[Any], track_labels: list[Any], prediction: EventPrediction | None) -> dict[str, Any]:
    predicted = prediction.poses if prediction else []
    joint_denominator = 0
    available = 0
    pck = 0
    oks_values: list[float] = []
    provenance: Counter[str] = Counter()
    wrong_person = 0
    missing_frames = 0
    for label in sorted(labels, key=lambda item: (item.pts, item.source_frame_index or -1)):
        item = _match_by_frame(predicted, label.source_frame_index, label.pts)
        joint_denominator += len(label.joints)
        if item is None:
            missing_frames += 1
            provenance["missing"] += len(label.joints)
            continue
        if item.identity == "wrong_person":
            wrong_person += 1
            provenance.update(joint.source for joint in item.joints)
            continue
        by_name = {joint.joint: joint for joint in item.joints}
        track = next((track for track in track_labels if track.source_frame_index == label.source_frame_index), None)
        scale = max(track.bbox.right - track.bbox.left, track.bbox.bottom - track.bbox.top) if track else 1.0
        for expected in label.joints:
            actual = by_name.get(expected.joint)
            source = actual.source if actual else "missing"
            provenance[source] += 1
            if not actual or actual.x is None or actual.y is None or source == "missing":
                continue
            available += 1
            distance = math.hypot(actual.x - expected.x, actual.y - expected.y)
            pck += int(distance <= 0.2 * scale)
            sigma = max(0.1 * scale, 1e-9)
            oks_values.append(math.exp(-(distance * distance) / (2 * sigma * sigma)))
    frame_denominator = len(labels)
    failures = []
    if missing_frames:
        failures.append("pose_prediction_missing")
    if wrong_person:
        failures.append("pose_wrong_person_skeleton")
    return {
        "frame_denominator": frame_denominator,
        "joint_availability": rate(available, joint_denominator),
        "pck_at_0_2": rate(pck, joint_denominator),
        "oks": round(statistics.fmean(oks_values), 6) if oks_values else None,
        "wrong_person_skeleton": rate(wrong_person, frame_denominator),
        "missing_frames": missing_frames,
        "provenance": dict(sorted(provenance.items())),
        "failure_codes": failures,
    }


def _aggregate(diagnostics: list[dict[str, Any]], masks: set[str]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {"event_count": len(diagnostics)}
    if "tracking" in masks:
        aggregate["tracking"] = _sum_rate_metrics(diagnostics, "tracking", ["confirmed_coverage", "uncertain_coverage", "lost_coverage", "correct_localization", "wrong_person", "false_relock", "low_iou"])
        aggregate["tracking"]["longest_missing_sec"] = max((item["metrics"]["tracking"]["longest_missing_sec"] for item in diagnostics), default=0.0)
    if "action" in masks:
        aggregate["action"] = _sum_rate_metrics(diagnostics, "action", ["proposal_recall", "class_accuracy"])
        matrix: dict[str, Counter[str]] = defaultdict(Counter)
        for item in diagnostics:
            metric = item["metrics"]["action"]
            matrix[metric["actual_profile"]][metric["predicted_profile"]] += 1
        aggregate["action"]["confusion_matrix"] = {key: dict(sorted(value.items())) for key, value in sorted(matrix.items())}
        rejected = sum(item["metrics"]["action"]["rejected"] for item in diagnostics)
        aggregate["action"]["rejection"] = rate(rejected, len(diagnostics))
    if "key_moments" in masks:
        aggregate["key_moments"] = _sum_rate_metrics(diagnostics, "key_moments", ["timing_coverage", "within_0_10_sec", "source_frame_accuracy"])
        errors = [moment["error_sec"] for item in diagnostics for moment in item["metrics"]["key_moments"]["moments"] if moment["error_sec"] is not None]
        aggregate["key_moments"].update({"mean_absolute_error_sec": round(statistics.fmean(errors), 6) if errors else None, "median_absolute_error_sec": round(statistics.median(errors), 6) if errors else None, "p95_absolute_error_sec": _percentile(errors, 0.95)})
    if "rotation" in masks:
        applicable = [item for item in diagnostics if item["metrics"]["rotation"].get("applicable")]
        aggregate["rotation"] = _sum_rate_metrics(applicable, "rotation", ["prediction_coverage", "class_accuracy", "confidently_wrong", "refusal_quality"])
        errors = [item["metrics"]["rotation"]["absolute_error_turns"] for item in applicable if item["metrics"]["rotation"]["absolute_error_turns"] is not None]
        aggregate["rotation"]["mae_turns"] = round(statistics.fmean(errors), 6) if errors else None
    if "pose" in masks:
        aggregate["pose"] = _sum_rate_metrics(diagnostics, "pose", ["joint_availability", "pck_at_0_2", "wrong_person_skeleton"])
        oks = [item["metrics"]["pose"]["oks"] for item in diagnostics if item["metrics"]["pose"]["oks"] is not None]
        aggregate["pose"]["oks"] = round(statistics.fmean(oks), 6) if oks else None
        provenance: Counter[str] = Counter()
        for item in diagnostics:
            provenance.update(item["metrics"]["pose"]["provenance"])
        aggregate["pose"]["provenance"] = dict(sorted(provenance.items()))
    aggregate["strata"] = _strata_aggregate(diagnostics, masks)
    return aggregate


def _sum_rate_metrics(diagnostics: list[dict[str, Any]], section: str, fields: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        pairs = [item["metrics"][section].get(field) for item in diagnostics]
        numerator = sum(pair["numerator"] for pair in pairs if isinstance(pair, dict))
        denominator = sum(pair["denominator"] for pair in pairs if isinstance(pair, dict))
        result[field] = rate(numerator, denominator)
    return result


def _strata_aggregate(diagnostics: list[dict[str, Any]], masks: set[str]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in diagnostics:
        for stratum in item["strata"]:
            grouped[stratum].append(item)
    result: dict[str, Any] = {}
    for stratum, items in sorted(grouped.items()):
        entry: dict[str, Any] = {"event_count": len(items), "failed_events": sum(bool(item["failure_codes"]) for item in items)}
        if "tracking" in masks:
            entry["tracking_coverage"] = _sum_rate_metrics(items, "tracking", ["confirmed_coverage"])["confirmed_coverage"]
        if "action" in masks:
            entry["action_recall"] = _sum_rate_metrics(items, "action", ["proposal_recall"])["proposal_recall"]
            rejected = sum(item["metrics"]["action"]["rejected"] for item in items)
            entry["action_rejection"] = rate(rejected, len(items))
        if "key_moments" in masks:
            entry["moment_coverage"] = _sum_rate_metrics(items, "key_moments", ["timing_coverage"])["timing_coverage"]
        if "rotation" in masks:
            applicable = [item for item in items if item["metrics"]["rotation"].get("applicable")]
            entry["rotation_coverage"] = _sum_rate_metrics(applicable, "rotation", ["prediction_coverage"])["prediction_coverage"]
        if "pose" in masks:
            entry["pose_coverage"] = _sum_rate_metrics(items, "pose", ["joint_availability"])["joint_availability"]
        result[stratum] = entry
    return result


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 6)
