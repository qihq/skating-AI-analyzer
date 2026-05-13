from __future__ import annotations

from dataclasses import asdict, dataclass
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


def _single_path_report(which: str, reason: str) -> CrossValidationReport:
    return CrossValidationReport(
        overall_agreement_rate=0.5,
        skeleton_reliability_signal="unknown",
        field_validations=[],
        high_confidence_fields=[],
        conflict_fields=[],
        recommended_path=which,
        conflict_summary=reason,
    )


def cross_validate(
    path_a: dict[str, Any] | None,
    path_b: dict[str, Any] | None,
) -> CrossValidationReport:
    a_ok = bool(path_a and not path_a.get("error"))
    b_ok = bool(path_b and not path_b.get("error"))

    if not a_ok and not b_ok:
        return CrossValidationReport(0.0, "unknown", [], [], [], "neither", "两路分析均失败。")
    if not a_ok:
        return _single_path_report("B", "Path A 失败，仅使用 Path B。")
    if not b_ok:
        return _single_path_report("A", "Path B 失败，仅使用 Path A。")

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
