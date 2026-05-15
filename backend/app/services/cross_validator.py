from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SUBSCORE_KEYS = [
    "takeoff_power",
    "rotation_axis",
    "arm_coordination",
    "landing_absorption",
    "core_stability",
]

OBJECTIVE_FIELDS = {"rotation_axis", "core_stability"}

AGREE_THRESHOLD = {"objective": 6, "subjective": 10}
MINOR_THRESHOLD = {"objective": 15, "subjective": 22}
CONFLICT_LEVELS = {"none": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(slots=True)
class FieldValidation:
    field_name: str
    path_a_value: Any
    path_b_value: Any
    agreement: str
    confidence: float
    note: str = ""


@dataclass(slots=True)
class CrossValidationReport:
    overall_agreement_rate: float
    skeleton_reliability_signal: str
    field_validations: list[FieldValidation]
    high_confidence_fields: list[str]
    conflict_fields: list[str]
    recommended_path: str
    conflict_summary: str
    fusion_diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["field_validations"] = [asdict(v) for v in self.field_validations]
        return d


def _classify(field: str, diff: int) -> tuple[str, float]:
    kind = "objective" if field in OBJECTIVE_FIELDS else "subjective"
    if diff <= AGREE_THRESHOLD[kind]:
        return "agree", round(1.0 - diff / 100, 3)
    if diff <= MINOR_THRESHOLD[kind]:
        return "minor_conflict", round(max(0.0, 0.6 - diff / 100), 3)
    return "major_conflict", round(max(0.1, 0.4 - diff / 100), 3)


def _compare_phases(a: list[str], b: list[str]) -> FieldValidation:
    sa, sb = set(a), set(b)
    j = (len(sa & sb) / len(sa | sb)) if (sa | sb) else 1.0
    if j >= 0.7:
        agr, conf = "agree", j
    elif j >= 0.4:
        agr, conf = "minor_conflict", j * 0.7
    else:
        agr, conf = "major_conflict", j * 0.4
    return FieldValidation("detected_phases", a, b, agr, round(conf, 3), f"jaccard={j:.2f}")


def _compare_subscores(a: dict, b: dict) -> list[FieldValidation]:
    out: list[FieldValidation] = []
    for key in SUBSCORE_KEYS:
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            out.append(FieldValidation(key, av, bv, "missing", 0.5))
            continue
        try:
            diff = abs(int(av) - int(bv))
        except (TypeError, ValueError):
            out.append(FieldValidation(key, av, bv, "missing", 0.5, "non-numeric"))
            continue
        agr, conf = _classify(key, diff)
        out.append(FieldValidation(key, av, bv, agr, conf, f"diff={diff}"))
    return out


def _normalize_conflict_level(value: Any) -> str:
    level = str(value or "none").strip().lower()
    return level if level in CONFLICT_LEVELS else "none"


def _max_conflict_level(levels: list[str]) -> str:
    if not levels:
        return "none"
    return max((_normalize_conflict_level(level) for level in levels), key=lambda level: CONFLICT_LEVELS[level])


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _path_diagnostics(path_name: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    available = isinstance(payload, dict) and not payload.get("error")
    reasons: list[str] = []
    if not available:
        reasons.append(f"{path_name}_failed")
    if isinstance(payload, dict):
        if payload.get("fallback_used"):
            reasons.append(f"{path_name}_fallback_used")
        flags = payload.get("quality_flags")
        if isinstance(flags, list):
            for flag in flags:
                text = str(flag)
                if "fallback" in text or "low" in text or "failed" in text:
                    reasons.append(f"{path_name}_{text}")
    return {
        "available": available,
        "conflict_level": "high" if isinstance(payload, dict) and payload.get("error") else _normalize_conflict_level(payload.get("conflict_level") if isinstance(payload, dict) else None),
        "downgraded_reasons": _dedupe(reasons),
    }


def _fusion_source(path_a: dict[str, Any] | None, fusion_payload: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(fusion_payload, dict):
        return fusion_payload
    if isinstance(path_a, dict) and (
        path_a.get("fusion_version") or path_a.get("fusion_decisions") or path_a.get("fusion_model_results")
    ):
        return path_a
    return {}


def _auto_eval_payloads(fusion: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    auto_eval = fusion.get("auto_eval")
    if isinstance(auto_eval, dict):
        payloads.append(auto_eval)

    model_results = fusion.get("model_results")
    if not isinstance(model_results, list):
        model_results = fusion.get("fusion_model_results")
    if isinstance(model_results, list):
        for result in model_results:
            if isinstance(result, dict) and isinstance(result.get("auto_eval"), dict):
                payloads.append(result["auto_eval"])
    return payloads


def _fusion_downgraded_reasons(fusion: dict[str, Any]) -> tuple[list[str], bool]:
    reasons: list[str] = []
    key_frame_order_invalid = False

    vote_metadata = fusion.get("vote_metadata") if isinstance(fusion.get("vote_metadata"), dict) else {}
    conflict_level = _normalize_conflict_level(fusion.get("conflict_level") or vote_metadata.get("conflict_level"))
    if conflict_level == "high":
        reasons.append("weighted_fusion_high_conflict")
    elif conflict_level in {"low", "medium"}:
        reasons.append(f"weighted_fusion_{conflict_level}_conflict")

    decisions = fusion.get("fusion_decisions") if isinstance(fusion.get("fusion_decisions"), list) else []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        if _normalize_conflict_level(decision.get("conflict_level")) == "high":
            reasons.append(f"frame_{decision.get('frame_id', 'unknown')}_high_conflict")
        candidates = decision.get("candidates") if isinstance(decision.get("candidates"), list) else []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            flags = candidate.get("rule_flags") if isinstance(candidate.get("rule_flags"), list) else []
            reasons.extend(str(flag) for flag in flags if flag)

    for auto_eval in _auto_eval_payloads(fusion):
        if auto_eval.get("key_frame_order_valid") is False:
            key_frame_order_invalid = True
            reasons.append("key_frame_order_invalid")
        if auto_eval.get("phase_sequence_valid") is False:
            reasons.append("phase_sequence_invalid")
        if auto_eval.get("high_confidence_conflicts"):
            reasons.append("high_confidence_key_frame_conflict")

    return _dedupe(reasons), key_frame_order_invalid


def build_fusion_diagnostics(
    path_a: dict[str, Any] | None,
    path_b: dict[str, Any] | None,
    fusion_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fusion = _fusion_source(path_a, fusion_payload)
    path_a_diag = _path_diagnostics("path_a", path_a)
    path_b_diag = _path_diagnostics("path_b", path_b)
    fusion_reasons, key_frame_order_invalid = _fusion_downgraded_reasons(fusion)
    vote_metadata = fusion.get("vote_metadata") if isinstance(fusion.get("vote_metadata"), dict) else {}
    fusion_level = _normalize_conflict_level(fusion.get("conflict_level") or vote_metadata.get("conflict_level"))
    conflict_level = _max_conflict_level([path_a_diag["conflict_level"], path_b_diag["conflict_level"], fusion_level])
    downgraded_reasons = _dedupe(path_a_diag["downgraded_reasons"] + path_b_diag["downgraded_reasons"] + fusion_reasons)

    return {
        "path_a": path_a_diag,
        "path_b": path_b_diag,
        "weighted_fusion": {
            "available": bool(fusion),
            "fusion_version": fusion.get("fusion_version"),
            "conflict_level": fusion_level,
            "downgraded_reasons": fusion_reasons,
        },
        "conflict_level": conflict_level,
        "downgraded_reasons": downgraded_reasons,
        "key_frame_order_invalid": key_frame_order_invalid,
        "needs_human_review": conflict_level == "high" or key_frame_order_invalid,
    }


def _single_path_report(which: str, reason: str, diagnostics: dict[str, Any] | None = None) -> CrossValidationReport:
    if diagnostics is None:
        failed_path = "path_a" if which == "B" else "path_b"
        diagnostics = build_fusion_diagnostics(
            {"error": "single_path"} if failed_path == "path_a" else {},
            {"error": "single_path"} if failed_path == "path_b" else {},
        )
    return CrossValidationReport(
        overall_agreement_rate=0.5,
        skeleton_reliability_signal="unknown",
        field_validations=[],
        high_confidence_fields=[],
        conflict_fields=[],
        recommended_path=which,
        conflict_summary=reason,
        fusion_diagnostics=diagnostics or {},
    )


def cross_validate(
    path_a: dict[str, Any] | None,
    path_b: dict[str, Any] | None,
    fusion_payload: dict[str, Any] | None = None,
) -> CrossValidationReport:
    diagnostics = build_fusion_diagnostics(path_a, path_b, fusion_payload)
    a_ok = bool(path_a and not path_a.get("error"))
    b_ok = bool(path_b and not path_b.get("error"))

    if not a_ok and not b_ok:
        return CrossValidationReport(0.0, "unknown", [], [], [], "neither", "两路分析均失败。", diagnostics)
    if not a_ok:
        return _single_path_report("B", "Path A 失败，仅使用 Path B。", diagnostics)
    if not b_ok:
        return _single_path_report("A", "Path B 失败，仅使用 Path A。", diagnostics)

    validations: list[FieldValidation] = [
        _compare_phases(
            (path_a.get("action_phase_summary") or {}).get("detected_phases", []),
            (path_b.get("action_phase_summary") or {}).get("detected_phases", []),
        )
    ]
    validations.extend(
        _compare_subscores(
            path_a.get("pure_vision_subscores", {}) or {},
            path_b.get("subscores", {}) or {},
        )
    )

    weight = {"agree": 1.0, "minor_conflict": 0.5, "major_conflict": 0.0, "missing": 0.5}
    overall = sum(weight[v.agreement] for v in validations) / len(validations)

    objective_majors = sum(
        1 for v in validations if v.agreement == "major_conflict" and v.field_name in OBJECTIVE_FIELDS
    )
    total_majors = sum(1 for v in validations if v.agreement == "major_conflict")

    if objective_majors >= 2:
        skeleton = "likely_wrong"
    elif total_majors >= 3:
        skeleton = "uncertain"
    elif total_majors == 0:
        skeleton = "reliable"
    else:
        skeleton = "uncertain"

    if overall >= 0.75:
        recommended = "blend"
    elif skeleton == "likely_wrong":
        recommended = "A"
    elif skeleton == "reliable":
        recommended = "blend"
    else:
        recommended = "blend"

    conflict_fields = [v.field_name for v in validations if "conflict" in v.agreement]
    high_conf_fields = [v.field_name for v in validations if v.agreement == "agree"]

    signal_text = {
        "reliable": "骨架追踪可信。",
        "uncertain": f"骨架追踪存疑（{total_majors} 项严重分歧）。",
        "likely_wrong": f"客观维度严重分歧（{objective_majors} 项），建议重选 target_lock。",
    }[skeleton]
    summary = (
        f"两路一致率 {overall:.0%}。{signal_text}"
        + (f" 分歧维度：{', '.join(conflict_fields)}。" if conflict_fields else " 无明显分歧。")
    )

    return CrossValidationReport(
        overall_agreement_rate=round(overall, 3),
        skeleton_reliability_signal=skeleton,
        field_validations=validations,
        high_confidence_fields=high_conf_fields,
        conflict_fields=conflict_fields,
        recommended_path=recommended,
        conflict_summary=summary,
        fusion_diagnostics=diagnostics,
    )


def compute_blend_weights(v: CrossValidationReport) -> tuple[float, float]:
    """返回 (a_weight, b_weight)。和为 1.0。单路情形显式 (1.0,0) 或 (0,1.0)。"""
    if v.recommended_path == "A":
        return (1.0, 0.0)
    if v.recommended_path == "B":
        return (0.0, 1.0)
    if v.recommended_path == "neither":
        return (0.5, 0.5)

    base = {
        "reliable": (0.35, 0.65),
        "uncertain": (0.50, 0.50),
        "likely_wrong": (0.75, 0.25),
        "unknown": (0.50, 0.50),
    }[v.skeleton_reliability_signal]
    a, b = base
    bonus = (v.overall_agreement_rate - 0.5) * 0.2
    b = round(min(0.75, max(0.25, b + bonus)), 3)
    return round(1.0 - b, 3), b
