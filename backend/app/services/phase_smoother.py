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


def _key_frame_phase_overrides(bio_data: dict | None) -> dict[str, str]:
    if not isinstance(bio_data, dict):
        return {}
    key_frames = bio_data.get("key_frames")
    if not isinstance(key_frames, dict):
        return {}

    overrides: dict[str, str] = {}
    for key, phase in {"takeoff": "起跳", "peak": "腾空", "landing": "落冰"}.items():
        frame_id = key_frames.get(key)
        if isinstance(frame_id, str) and frame_id:
            overrides[frame_id.removesuffix(".jpg")] = phase
    return overrides


def _near_key_frame_override(index: int, frame_ids: list[str], overrides: dict[str, str]) -> str | None:
    for offset in (-1, 0, 1):
        candidate_index = index + offset
        if 0 <= candidate_index < len(frame_ids):
            phase = overrides.get(frame_ids[candidate_index])
            if phase:
                return phase
    return None


def _is_vote_split(frame: dict) -> bool:
    votes = frame.get("phase_votes")
    if not isinstance(votes, dict) or len(votes) <= 1:
        return False
    values = [value for value in votes.values() if isinstance(value, int)]
    if not values:
        return False
    return values.count(max(values)) > 1 or max(values) < sum(values)


def smooth_phases(frame_analysis: list[dict], analysis_profile: str, bio_data: dict | None = None) -> list[dict]:
    """
    Validate and repair per-frame phase predictions with profile-specific
    transition constraints.
    """
    transitions = VALID_TRANSITIONS.get(analysis_profile, {})
    if not transitions:
        return frame_analysis

    frame_ids = [str(frame.get("frame_id", "")).removesuffix(".jpg") for frame in frame_analysis]
    key_overrides = _key_frame_phase_overrides(bio_data) if analysis_profile == "jump" else {}

    smoothed: list[dict] = []
    prev_phase = "不可分析"
    for index, frame in enumerate(frame_analysis):
        current_phase = frame.get("phase", "不可分析")
        override_phase = _near_key_frame_override(index, frame_ids, key_overrides) if _is_vote_split(frame) else None
        if override_phase:
            normalized = {
                **frame,
                "phase": override_phase,
                "phase_corrected": True,
                "phase_correction_source": "biomechanics_key_frame",
            }
            smoothed.append(normalized)
            prev_phase = normalized["phase"]
            continue

        allowed = transitions.get(prev_phase, set())
        if allowed and current_phase not in allowed:
            normalized = {**frame, "phase": prev_phase, "phase_corrected": True}
        else:
            normalized = {**frame, "phase_corrected": False}
        smoothed.append(normalized)
        prev_phase = normalized["phase"]

    return smoothed
