from __future__ import annotations

from typing import Any

from app.services.auto_eval import build_auto_eval_payload
from app.services.provider_specialties import load_provider_specialty
from app.services.vision_quality import evaluate_vision_payload_quality


FUSION_VERSION = "v3_weighted_router"

UNKNOWN_PHASE = "\u4e0d\u53ef\u5206\u6790"
VALID_PHASES = {
    "\u51c6\u5907",
    "\u8d77\u8df3",
    "\u817e\u7a7a",
    "\u843d\u51b0",
    "\u6ed1\u51fa",
    "\u65cb\u8f6c\u5165",
    "\u65cb\u8f6c\u4e2d",
    "\u65cb\u8f6c\u51fa",
    "\u6b65\u6cd5",
    UNKNOWN_PHASE,
}

DATA_QUALITY_FACTORS = {
    "good": 1.0,
    "partial": 0.75,
    "poor": 0.45,
}

PROFILE_SPECIALTY_KEYS = {
    "jump": ("frame_phase_weight", "jump_subtype_weight", "blade_edge_weight"),
    "spin": ("frame_phase_weight", "video_temporal_weight"),
    "step": ("frame_phase_weight", "video_temporal_weight"),
    "spiral": ("frame_phase_weight", "child_motion_weight"),
}

CONFLICT_LEVEL_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def fuse_vision_results_weighted(
    model_results: list[dict[str, Any]],
    bio_data: dict[str, Any] | None,
    analysis_profile: str | None,
) -> dict[str, Any]:
    """Fuse multi-model vision results with confidence, quality, and rule weights."""
    profile = str(analysis_profile or "jump").strip().lower() or "jump"
    evaluated_results = [
        _evaluate_model_result(result, index, bio_data, profile)
        for index, result in enumerate(model_results)
        if isinstance(result, dict)
    ]

    frame_ids = _ordered_frame_ids(evaluated_results)
    repeatability = _repeatability_by_model_frame(evaluated_results, frame_ids)

    final_frames: list[dict[str, Any]] = []
    fusion_decisions: list[dict[str, Any]] = []
    frame_conflict_levels: list[str] = []

    for frame_id in frame_ids:
        decision = _fuse_frame(frame_id, evaluated_results, repeatability)
        fusion_decisions.append(_public_decision(decision))
        frame_conflict_levels.append(decision["conflict_level"])
        final_frames.append(_final_frame_from_decision(decision))

    detected_phases = _detected_phases(final_frames)
    conflict_level = _max_conflict_level(frame_conflict_levels)
    if _has_any_rule_conflict(evaluated_results):
        conflict_level = _max_conflict_level([conflict_level, "high"])

    return {
        "fusion_version": FUSION_VERSION,
        "final_frame_analysis": final_frames,
        "model_results": [
            _public_model_result(evaluated)
            for evaluated in evaluated_results
        ],
        "fusion_decisions": fusion_decisions,
        "conflict_level": conflict_level,
        "action_phase_summary": {
            "detected_phases": detected_phases,
            "weakest_phase": final_frames[-1]["phase"] if final_frames else UNKNOWN_PHASE,
            "strongest_phase": final_frames[0]["phase"] if final_frames else UNKNOWN_PHASE,
        },
    }


def _evaluate_model_result(
    result: dict[str, Any],
    index: int,
    bio_data: dict[str, Any] | None,
    analysis_profile: str,
) -> dict[str, Any]:
    provider = _provider_name(result, index)
    quality = evaluate_vision_payload_quality(result)
    auto_eval = build_auto_eval_payload(bio_data, result, None, analysis_profile)
    specialty_weights = load_provider_specialty(provider)

    provider_base_weight = _factor(result.get("provider_base_weight"), default=1.0)
    model_confidence = _model_confidence(result)
    json_validity_factor = _factor(
        result.get("json_validity_factor"),
        default=_factor(quality.get("json_validity_factor"), default=0.5),
    )
    data_quality_factor = _data_quality_factor(result)
    specialty_factor = _specialty_factor(specialty_weights, analysis_profile)
    rule_consistency_factor = _rule_consistency_factor(auto_eval)

    return {
        "index": index,
        "provider": provider,
        "model": str(result.get("model") or result.get("model_id") or "").strip(),
        "payload": result,
        "frames_by_id": _frames_by_id(result),
        "quality": quality,
        "auto_eval": auto_eval,
        "specialty_weights": specialty_weights,
        "base_factors": {
            "provider_base_weight": provider_base_weight,
            "model_confidence": model_confidence,
            "json_validity_factor": json_validity_factor,
            "data_quality_factor": data_quality_factor,
            "specialty_factor": specialty_factor,
            "rule_consistency_factor": rule_consistency_factor,
        },
        "rule_conflict_frame_ids": _rule_conflict_frame_ids(auto_eval),
        "rule_violation_frame_ids": _rule_violation_frame_ids(auto_eval),
    }


def _fuse_frame(
    frame_id: str,
    evaluated_results: list[dict[str, Any]],
    repeatability: dict[tuple[int, str], float],
) -> dict[str, Any]:
    phase_scores: dict[str, float] = {}
    phase_votes: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []

    for evaluated in evaluated_results:
        frame = evaluated["frames_by_id"].get(frame_id)
        if not isinstance(frame, dict):
            continue

        phase = _valid_phase(frame.get("phase"))
        model_confidence = _frame_confidence(frame, evaluated["base_factors"]["model_confidence"])
        frame_rule_factor = _frame_rule_factor(evaluated, frame_id)
        repeatability_factor = repeatability.get((evaluated["index"], frame_id), 1.0)
        factors = {
            **evaluated["base_factors"],
            "model_confidence": model_confidence,
            "rule_consistency_factor": frame_rule_factor,
            "repeatability_factor": repeatability_factor,
        }
        effective_weight = _effective_weight(factors)

        phase_scores[phase] = phase_scores.get(phase, 0.0) + effective_weight
        phase_votes[phase] = phase_votes.get(phase, 0) + 1
        candidates.append(
            {
                "provider": evaluated["provider"],
                "model": evaluated["model"],
                "phase": phase,
                "frame_confidence": model_confidence,
                "effective_weight": round(effective_weight, 6),
                "factors": {key: round(value, 3) for key, value in factors.items()},
                "rule_flags": _candidate_rule_flags(evaluated, frame_id),
                "json_warnings": evaluated["quality"].get("warnings", []),
                "frame": frame,
            }
        )

    rounded_scores = {phase: round(score, 6) for phase, score in phase_scores.items()}
    selected_phase = _select_phase(phase_scores)
    selected_candidates = [
        candidate for candidate in candidates if candidate["phase"] == selected_phase
    ]
    selected_candidates.sort(key=lambda item: item["effective_weight"], reverse=True)
    conflict_level = _frame_conflict_level(phase_scores, candidates)

    return {
        "frame_id": frame_id,
        "selected_phase": selected_phase,
        "phase_scores": rounded_scores,
        "phase_votes": phase_votes,
        "candidates": [_public_candidate(candidate) for candidate in candidates],
        "selected_provider": selected_candidates[0]["provider"] if selected_candidates else "",
        "selected_model": selected_candidates[0]["model"] if selected_candidates else "",
        "selected_score": round(phase_scores.get(selected_phase, 0.0), 6),
        "score_margin": _score_margin(phase_scores),
        "confidence": _winner_confidence(phase_scores),
        "conflict_level": conflict_level,
        "evidence": _decision_evidence(selected_phase, phase_scores, selected_candidates, candidates),
        "_selected_candidates": selected_candidates,
    }


def _final_frame_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    selected_candidates = decision.get("_selected_candidates", [])
    observations: dict[str, str] = {}
    issues: list[Any] = []
    positives: list[Any] = []

    for candidate in selected_candidates:
        frame = candidate.get("frame")
        if not isinstance(frame, dict):
            continue
        raw_observations = frame.get("observations")
        if isinstance(raw_observations, dict):
            observations.update({str(key): str(value) for key, value in raw_observations.items()})
        if isinstance(frame.get("issues"), list):
            issues.extend(frame["issues"])
        if isinstance(frame.get("positives"), list):
            positives.extend(frame["positives"])

    return {
        "frame_id": decision["frame_id"],
        "phase": decision["selected_phase"],
        "phase_scores": decision["phase_scores"],
        "phase_votes": decision["phase_votes"],
        "confidence": decision["confidence"],
        "observations": observations,
        "issues": _dedupe_texts(issues),
        "positives": _dedupe_texts(positives),
        "fusion_evidence": decision["evidence"],
    }


def _provider_name(result: dict[str, Any], index: int) -> str:
    provider = str(
        result.get("provider")
        or result.get("provider_name")
        or result.get("provider_id")
        or ""
    ).strip()
    return provider or f"model_{index + 1}"


def _frames_by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    frames = result.get("frame_analysis")
    if not isinstance(frames, list):
        return {}
    return {
        str(frame.get("frame_id") or "").removesuffix(".jpg"): frame
        for frame in frames
        if isinstance(frame, dict) and str(frame.get("frame_id") or "").strip()
    }


def _ordered_frame_ids(evaluated_results: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for evaluated in evaluated_results:
        for frame_id in evaluated["frames_by_id"]:
            if frame_id not in ordered:
                ordered.append(frame_id)
    return ordered


def _repeatability_by_model_frame(
    evaluated_results: list[dict[str, Any]],
    frame_ids: list[str],
) -> dict[tuple[int, str], float]:
    repeatability: dict[tuple[int, str], float] = {}
    for frame_id in frame_ids:
        phases: list[str] = []
        for evaluated in evaluated_results:
            frame = evaluated["frames_by_id"].get(frame_id)
            if isinstance(frame, dict):
                phases.append(_valid_phase(frame.get("phase")))
        total = len(phases)
        if total <= 1:
            for evaluated in evaluated_results:
                if frame_id in evaluated["frames_by_id"]:
                    repeatability[(evaluated["index"], frame_id)] = 1.0
            continue
        counts = {phase: phases.count(phase) for phase in set(phases)}
        for evaluated in evaluated_results:
            frame = evaluated["frames_by_id"].get(frame_id)
            if not isinstance(frame, dict):
                continue
            phase = _valid_phase(frame.get("phase"))
            agreement_ratio = counts.get(phase, 0) / total
            repeatability[(evaluated["index"], frame_id)] = round(0.7 + 0.3 * agreement_ratio, 3)
    return repeatability


def _model_confidence(result: dict[str, Any]) -> float:
    explicit = _to_float(result.get("model_confidence"))
    if explicit is not None:
        return _clamp(explicit)

    frames = result.get("frame_analysis")
    if not isinstance(frames, list):
        return 0.5
    confidences = [
        _frame_confidence(frame, 0.0)
        for frame in frames
        if isinstance(frame, dict) and (_to_float(frame.get("confidence")) is not None or _to_float(frame.get("phase_confidence")) is not None)
    ]
    if not confidences:
        return 0.5
    return _clamp(sum(confidences) / len(confidences))


def _frame_confidence(frame: dict[str, Any], default: float) -> float:
    confidence = _to_float(frame.get("phase_confidence"))
    if confidence is not None:
        return _clamp(confidence)
    confidence = _to_float(frame.get("confidence"))
    if confidence is not None:
        return _clamp(confidence)
    return _clamp(default)


def _data_quality_factor(result: dict[str, Any]) -> float:
    explicit = _to_float(result.get("data_quality_factor"))
    if explicit is not None:
        return _clamp(explicit)
    hint = str(result.get("data_quality_hint") or "").strip().lower()
    factor = DATA_QUALITY_FACTORS.get(hint, 0.65)
    flags = result.get("quality_flags")
    if isinstance(flags, list) and any("fallback" in str(flag) or "unavailable" in str(flag) for flag in flags):
        factor = min(factor, 0.35)
    return factor


def _specialty_factor(specialty_weights: dict[str, float], analysis_profile: str) -> float:
    keys = PROFILE_SPECIALTY_KEYS.get(analysis_profile, ("frame_phase_weight",))
    values = [_factor(specialty_weights.get(key), default=0.5) for key in keys]
    return _clamp(sum(values) / len(values)) if values else 0.5


def _rule_consistency_factor(auto_eval: dict[str, Any]) -> float:
    factor = 1.0
    if auto_eval.get("key_frame_order_valid") is False:
        factor = min(factor, 0.7)
    if auto_eval.get("phase_sequence_valid") is False:
        factor = min(factor, 0.65)
    if auto_eval.get("high_confidence_conflicts"):
        factor = min(factor, 0.45)
    return factor


def _frame_rule_factor(evaluated: dict[str, Any], frame_id: str) -> float:
    base = evaluated["base_factors"]["rule_consistency_factor"]
    if frame_id in evaluated["rule_conflict_frame_ids"]:
        return min(base, 0.35)
    if frame_id in evaluated["rule_violation_frame_ids"]:
        return min(base, 0.55)
    return base


def _candidate_rule_flags(evaluated: dict[str, Any], frame_id: str) -> list[str]:
    flags: list[str] = []
    if frame_id in evaluated["rule_conflict_frame_ids"]:
        flags.append("rule_high_confidence_key_frame_conflict")
    if frame_id in evaluated["rule_violation_frame_ids"]:
        flags.append("rule_phase_transition_violation")
    return flags


def _rule_conflict_frame_ids(auto_eval: dict[str, Any]) -> set[str]:
    conflicts = auto_eval.get("high_confidence_conflicts")
    if not isinstance(conflicts, list):
        return set()
    return {
        str(conflict.get("frame_id") or "").removesuffix(".jpg")
        for conflict in conflicts
        if isinstance(conflict, dict) and str(conflict.get("frame_id") or "").strip()
    }


def _rule_violation_frame_ids(auto_eval: dict[str, Any]) -> set[str]:
    violations = auto_eval.get("phase_transition_violations")
    if not isinstance(violations, list):
        return set()
    return {
        str(violation.get("frame_id") or "").removesuffix(".jpg")
        for violation in violations
        if isinstance(violation, dict) and str(violation.get("frame_id") or "").strip()
    }


def _effective_weight(factors: dict[str, float]) -> float:
    weight = 1.0
    for key in (
        "provider_base_weight",
        "model_confidence",
        "json_validity_factor",
        "data_quality_factor",
        "specialty_factor",
        "rule_consistency_factor",
        "repeatability_factor",
    ):
        weight *= _factor(factors.get(key), default=1.0)
    return _clamp(weight)


def _select_phase(phase_scores: dict[str, float]) -> str:
    if not phase_scores:
        return UNKNOWN_PHASE
    return sorted(phase_scores.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _score_margin(phase_scores: dict[str, float]) -> float:
    if not phase_scores:
        return 0.0
    ordered = sorted(phase_scores.values(), reverse=True)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    return round(ordered[0] - ordered[1], 6)


def _winner_confidence(phase_scores: dict[str, float]) -> float:
    total = sum(phase_scores.values())
    if total <= 0:
        return 0.0
    winner = max(phase_scores.values())
    return round(_clamp(winner / total), 3)


def _frame_conflict_level(phase_scores: dict[str, float], candidates: list[dict[str, Any]]) -> str:
    nonzero_phases = [phase for phase, score in phase_scores.items() if score > 0.0]
    if len(nonzero_phases) <= 1:
        if any(candidate.get("rule_flags") for candidate in candidates):
            return "high"
        return "none"
    if any(candidate.get("rule_flags") for candidate in candidates):
        return "high"

    total = sum(phase_scores.values())
    winner_share = max(phase_scores.values()) / total if total > 0 else 0.0
    if winner_share >= 0.75:
        return "low"
    if winner_share >= 0.6:
        return "medium"
    return "high"


def _decision_evidence(
    selected_phase: str,
    phase_scores: dict[str, float],
    selected_candidates: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "selected_phase": selected_phase,
        "winning_score": round(phase_scores.get(selected_phase, 0.0), 6),
        "total_score": round(sum(phase_scores.values()), 6),
        "winning_share": _winner_confidence(phase_scores),
        "supporting_providers": [candidate["provider"] for candidate in selected_candidates],
        "opposing_providers": [
            candidate["provider"]
            for candidate in candidates
            if candidate["phase"] != selected_phase
        ],
        "score_margin": _score_margin(phase_scores),
    }


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": candidate["provider"],
        "model": candidate["model"],
        "phase": candidate["phase"],
        "frame_confidence": candidate["frame_confidence"],
        "effective_weight": candidate["effective_weight"],
        "factors": candidate["factors"],
        "rule_flags": candidate["rule_flags"],
        "json_warnings": candidate["json_warnings"],
    }


def _public_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in decision.items()
        if not key.startswith("_")
    }


def _public_model_result(evaluated: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": evaluated["provider"],
        "model": evaluated["model"],
        "base_factors": {
            key: round(value, 3)
            for key, value in evaluated["base_factors"].items()
        },
        "quality": evaluated["quality"],
        "auto_eval": evaluated["auto_eval"],
        "specialty_weights": evaluated["specialty_weights"],
        "frame_count": len(evaluated["frames_by_id"]),
    }


def _detected_phases(final_frames: list[dict[str, Any]]) -> list[str]:
    phases: list[str] = []
    for frame in final_frames:
        phase = str(frame.get("phase") or "")
        if phase and phase != UNKNOWN_PHASE and phase not in phases:
            phases.append(phase)
    return phases


def _has_any_rule_conflict(evaluated_results: list[dict[str, Any]]) -> bool:
    return any(evaluated["rule_conflict_frame_ids"] for evaluated in evaluated_results)


def _max_conflict_level(levels: list[str]) -> str:
    if not levels:
        return "none"
    return max(levels, key=lambda level: CONFLICT_LEVEL_ORDER.get(level, 0))


def _valid_phase(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in VALID_PHASES else UNKNOWN_PHASE


def _factor(value: Any, default: float) -> float:
    numeric = _to_float(value)
    return _clamp(numeric) if numeric is not None else default


def _to_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        return None
    return numeric


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _dedupe_texts(items: list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out
