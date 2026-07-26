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

PHASE_ORDERS: dict[str, list[str]] = {
    "jump": ["准备", "起跳", "腾空", "落冰", "滑出"],
    "spin": ["旋转入", "旋转中", "旋转出"],
    "spiral": ["准备", "步法"],
    "step": ["步法"],
}
UNKNOWN_PHASE = "不可分析"


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
            normalized = {
                **frame,
                "phase": prev_phase,
                "phase_corrected": True,
                "phase_correction_source": "phase_transition_state_machine",
                "phase_correction_reason": f"illegal_transition:{prev_phase}->{current_phase}",
            }
        else:
            normalized = {**frame, "phase_corrected": False}
        smoothed.append(normalized)
        prev_phase = normalized["phase"]

    return smoothed


def evaluate_phase_consistency(
    frame_analysis: list[dict],
    analysis_profile: str,
    bio_data: dict | None = None,
) -> dict:
    """
    Strictly validate phase order and return corrected frames with quality flags.

    `smooth_phases()` remains the compatibility helper that returns only frames.
    This function adds an auditable state-machine layer for quality scoring.
    """
    profile = str(analysis_profile or "").strip().lower()
    phase_order = PHASE_ORDERS.get(profile)
    if not phase_order:
        return {
            "frame_analysis": frame_analysis,
            "phase_consistency_flags": [
                {
                    "flag": "phase_consistency_unknown_profile",
                    "reason": f"unknown_profile:{analysis_profile}",
                }
            ],
            "phase_consistency_score": 0.0,
            "phase_consistency_valid": False,
        }

    frame_ids = [str(frame.get("frame_id", "")).removesuffix(".jpg") for frame in frame_analysis]
    key_overrides = _key_frame_phase_overrides(bio_data) if profile == "jump" else {}
    phase_rank = {phase: index for index, phase in enumerate(phase_order)}

    corrected_frames: list[dict] = []
    flags: list[dict] = []
    max_rank = -1
    previous_phase = UNKNOWN_PHASE

    for index, frame in enumerate(frame_analysis):
        raw_phase = str(frame.get("phase", UNKNOWN_PHASE) or UNKNOWN_PHASE)
        phase = raw_phase if raw_phase in phase_rank or raw_phase == UNKNOWN_PHASE else UNKNOWN_PHASE

        override_phase = _near_key_frame_override(index, frame_ids, key_overrides) if _is_vote_split(frame) else None
        if override_phase and override_phase in phase_rank:
            phase = override_phase
            corrected = {
                **frame,
                "phase": override_phase,
                "phase_corrected": True,
                "phase_correction_source": "biomechanics_key_frame",
                "phase_correction_reason": "vote_split_near_biomechanics_key_frame",
            }
            corrected_frames.append(corrected)
            rank = phase_rank[override_phase]
            max_rank = max(max_rank, rank)
            previous_phase = override_phase
            flags.append(
                {
                    "frame_id": frame.get("frame_id"),
                    "flag": "phase_corrected_by_biomechanics_key_frame",
                    "from_phase": raw_phase,
                    "to_phase": override_phase,
                    "reason": "vote_split_near_biomechanics_key_frame",
                }
            )
            continue

        if phase == UNKNOWN_PHASE:
            corrected_frames.append({**frame, "phase": phase, "phase_corrected": False})
            previous_phase = phase
            continue

        rank = phase_rank[phase]
        expected_rank = min(max_rank + 1, len(phase_order) - 1)
        if rank < max_rank:
            corrected_phase = previous_phase if previous_phase in phase_rank else phase_order[max_rank]
            reason = f"phase_backward:{phase}->{corrected_phase}"
            corrected_frames.append(
                {
                    **frame,
                    "phase": corrected_phase,
                    "phase_corrected": True,
                    "phase_correction_source": "phase_state_machine",
                    "phase_correction_reason": reason,
                }
            )
            flags.append(
                {
                    "frame_id": frame.get("frame_id"),
                    "flag": "phase_backward_corrected",
                    "from_phase": phase,
                    "to_phase": corrected_phase,
                    "reason": reason,
                }
            )
            previous_phase = corrected_phase
            continue

        if rank > expected_rank:
            corrected_phase = phase_order[expected_rank]
            skipped = phase_order[expected_rank:rank]
            reason = f"phase_skip:{'|'.join(skipped)}_before_{phase}"
            corrected_frames.append(
                {
                    **frame,
                    "phase": corrected_phase,
                    "phase_corrected": True,
                    "phase_correction_source": "phase_state_machine",
                    "phase_correction_reason": reason,
                }
            )
            flags.append(
                {
                    "frame_id": frame.get("frame_id"),
                    "flag": "phase_skip_corrected",
                    "from_phase": phase,
                    "to_phase": corrected_phase,
                    "reason": reason,
                    "missing_phases": skipped,
                }
            )
            max_rank = max(max_rank, expected_rank)
            previous_phase = corrected_phase
            continue

        corrected_frames.append({**frame, "phase": phase, "phase_corrected": bool(frame.get("phase_corrected", False))})
        max_rank = max(max_rank, rank)
        previous_phase = phase

    missing_required = _missing_required_phases(corrected_frames, phase_order, profile)
    for phase in missing_required:
        flags.append(
            {
                "flag": "phase_required_phase_missing",
                "phase": phase,
                "reason": f"required_phase_missing:{phase}",
            }
        )

    score = round(max(0.0, 1.0 - len(flags) / max(1, len(frame_analysis))), 3)
    return {
        "frame_analysis": corrected_frames,
        "phase_consistency_flags": flags,
        "phase_consistency_score": score,
        "phase_consistency_valid": len(flags) == 0,
    }


def _missing_required_phases(frame_analysis: list[dict], phase_order: list[str], profile: str) -> list[str]:
    if profile not in {"jump", "spin"}:
        return []
    observed = {str(frame.get("phase", "")) for frame in frame_analysis}
    if profile == "jump":
        required = ["起跳", "腾空", "落冰"]
    else:
        required = phase_order
    return [phase for phase in required if phase not in observed]
