from __future__ import annotations


VALID_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "jump": {
        "准备": {"准备", "起跳"},
        "起跳": {"起跳", "腾空"},
        "腾空": {"腾空", "落冰"},
        "落冰": {"落冰", "滑出", "不可分析"},
        "滑出": {"滑出", "不可分析"},
        "不可分析": {"准备", "起跳", "腾空", "落冰", "滑出", "不可分析"},
    },
    "spin": {
        "旋转入": {"旋转入", "旋转中"},
        "旋转中": {"旋转中", "旋转出"},
        "旋转出": {"旋转出", "不可分析"},
        "不可分析": {"旋转入", "旋转中", "旋转出", "不可分析"},
    },
    "spiral": {
        "准备": {"准备", "步法"},
        "步法": {"步法", "不可分析"},
        "不可分析": {"准备", "步法", "不可分析"},
    },
    "step": {
        "步法": {"步法", "不可分析"},
        "不可分析": {"步法", "不可分析"},
    },
}


def smooth_phases(frame_analysis: list[dict], analysis_profile: str) -> list[dict]:
    """
    Validate and repair per-frame phase predictions with profile-specific
    transition constraints.
    """
    transitions = VALID_TRANSITIONS.get(analysis_profile, {})
    if not transitions:
        return frame_analysis

    smoothed: list[dict] = []
    prev_phase = "不可分析"
    for frame in frame_analysis:
        current_phase = frame.get("phase", "不可分析")
        allowed = transitions.get(prev_phase, set())
        if allowed and current_phase not in allowed:
            normalized = {**frame, "phase": prev_phase, "phase_corrected": True}
        else:
            normalized = {**frame, "phase_corrected": False}
        smoothed.append(normalized)
        prev_phase = normalized["phase"]

    return smoothed
