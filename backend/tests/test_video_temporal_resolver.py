from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video_temporal import (
    normalize_video_temporal_payload,
    resolve_semantic_keyframes,
    semantic_keyframes_are_reliable,
    validate_video_temporal_payload,
)


def _video_payload(confidence: float = 0.86) -> dict[str, object]:
    return {
        "schema_version": "video_temporal_v1",
        "provider": "qwen",
        "model": "qwen3.6-plus",
        "action_confirmation": {
            "action_family": "jump",
            "confirmed_action": "Axel",
            "jump_type": "Axel",
            "confidence": confidence,
            "notes": "",
        },
        "phase_segments": [
            {"phase_code": "takeoff", "phase_label": "起跳", "time_start": 1.0, "time_end": 1.4, "key_frame_hint": 1.18, "confidence": 0.82},
            {"phase_code": "air", "phase_label": "腾空", "time_start": 1.4, "time_end": 1.8, "key_frame_hint": 1.6, "confidence": 0.84},
            {"phase_code": "landing", "phase_label": "落冰", "time_start": 1.8, "time_end": 2.2, "key_frame_hint": 1.96, "confidence": 0.83},
        ],
        "key_moments": {"T_takeoff_sec": 1.2, "A_air_sec": 1.6, "L_landing_sec": 2.0},
        "macro_assessment": {},
        "overall_impression": "ok",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": confidence,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": [],
    }


def _validated_video(confidence: float = 0.86) -> dict[str, object]:
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(_video_payload(confidence), "qwen", "qwen3.6-plus"),
        duration_sec=3.0,
    )


def _validated_moderate_fallback_video(confidence: float = 0.60) -> dict[str, object]:
    payload = _video_payload(confidence)
    payload["fallback_recommendation"] = "use_sampled_frames"
    payload["phase_segments"] = [
        {"phase_code": "takeoff", "phase_label": "èµ·è·³", "time_start": 1.0, "time_end": 1.4, "key_frame_hint": 1.2, "confidence": 0.6},
        {"phase_code": "air", "phase_label": "è…¾ç©º", "time_start": 1.4, "time_end": 1.8, "key_frame_hint": 1.6, "confidence": 0.5},
        {"phase_code": "landing", "phase_label": "è½å†°", "time_start": 1.8, "time_end": 2.2, "key_frame_hint": 2.0, "confidence": 0.6},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 1.2, "A_air_sec": 1.6, "L_landing_sec": 2.0}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=3.0,
    )


def _validated_latest_high_confidence_fallback_video() -> dict[str, object]:
    payload = _video_payload(0.85)
    payload["fallback_recommendation"] = "use_sampled_frames"
    payload["quality_flags"] = ["video_temporal_fallback_recommended"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.35, "key_frame_hint": 5.5, "confidence": 0.8},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.35, "time_end": 6.85, "key_frame_hint": 6.6, "confidence": 0.8},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.85, "time_end": 7.15, "key_frame_hint": 6.95, "confidence": 0.8},
        {"phase_code": "air", "phase_label": "air", "time_start": 7.15, "time_end": 7.55, "key_frame_hint": 7.35, "confidence": 0.75},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.55, "time_end": 7.85, "key_frame_hint": 7.65, "confidence": 0.85},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.85, "time_end": 9.25, "key_frame_hint": 8.5, "confidence": 0.8},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.95, "A_air_sec": 7.35, "L_landing_sec": 7.65}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_spiral_step_family_fallback_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "provider": "mimo",
        "model": "mimo-v2.5",
        "valid": False,
        "action_confirmation": {
            "action_family": "step",
            "confirmed_action": "spiral",
            "jump_type": "",
            "confidence": 0.9,
            "notes": "clear spiral hold",
        },
        "phase_segments": [
            {"phase_code": "spiral_entry", "phase_label": "spiral entry", "time_start": 5.3, "time_end": 6.5, "key_frame_hint": 5.8, "confidence": 0.8, "valid": False},
            {"phase_code": "spiral_hold", "phase_label": "spiral hold", "time_start": 6.5, "time_end": 9.0, "key_frame_hint": 7.5, "confidence": 0.85, "valid": False},
            {"phase_code": "spiral_exit", "phase_label": "spiral exit", "time_start": 9.0, "time_end": 10.2, "key_frame_hint": 9.5, "confidence": 0.8, "valid": False},
        ],
        "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
        "macro_assessment": {},
        "overall_impression": "spiral",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.8,
        "fallback_recommendation": "use_sampled_frames",
        "quality_flags": [
            "brief foreground occlusion",
            "video_temporal_phase_0_invalid_code",
            "video_temporal_phase_1_invalid_code",
            "video_temporal_phase_2_invalid_code",
        ],
        "validation": {
            "valid": False,
            "errors": [
                "video_temporal_phase_0_invalid_code",
                "video_temporal_phase_1_invalid_code",
                "video_temporal_phase_2_invalid_code",
            ],
            "warnings": [],
            "duration_sec": 11.235,
        },
    }
    return validate_video_temporal_payload(payload, duration_sec=12.0)


def _validated_spiral_with_extra_step_phase_video() -> dict[str, object]:
    payload = _validated_spiral_step_family_fallback_video()
    payload["action_confirmation"] = {
        "action_family": "spiral",
        "confirmed_action": "spiral",
        "jump_type": "",
        "confidence": 0.9,
        "notes": "clear spiral hold",
    }
    payload["phase_segments"] = [
        {"phase_code": "step_sequence", "phase_label": "step prep", "time_start": 0.5, "time_end": 2.0, "key_frame_hint": 1.3, "confidence": 0.85, "valid": False},
        {"phase_code": "spiral_entry", "phase_label": "spiral entry", "time_start": 2.0, "time_end": 3.0, "key_frame_hint": 2.5, "confidence": 0.9, "valid": True},
        {"phase_code": "spiral_hold", "phase_label": "spiral hold", "time_start": 3.0, "time_end": 6.0, "key_frame_hint": 4.0, "confidence": 0.95, "valid": True},
        {"phase_code": "spiral_exit", "phase_label": "spiral exit", "time_start": 6.0, "time_end": 7.0, "key_frame_hint": 6.5, "confidence": 0.85, "valid": True},
    ]
    payload["confidence"] = 0.9
    payload["fallback_recommendation"] = "use_sampled_frames"
    payload["quality_flags"] = ["video_temporal_phase_0_invalid_code"]
    payload["validation"] = {
        "valid": False,
        "errors": ["video_temporal_phase_0_invalid_code"],
        "warnings": [],
        "duration_sec": 8.5,
    }
    return payload


def _validated_requested_spiral_provider_step_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "provider": "mimo",
        "model": "mimo-v2.5",
        "valid": True,
        "action_confirmation": {
            "action_family": "step",
            "confirmed_action": "step_sequence",
            "jump_type": "",
            "confidence": 0.9,
            "notes": "provider found a step sequence rather than a spiral",
        },
        "phase_segments": [
            {"phase_code": "step_sequence", "phase_label": "step sequence", "time_start": 0.5, "time_end": 7.7, "key_frame_hint": 3.5, "confidence": 0.9, "valid": True},
        ],
        "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
        "macro_assessment": {},
        "overall_impression": "step sequence",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.85,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": [],
        "validation": {
            "valid": True,
            "errors": [],
            "warnings": [],
            "duration_sec": 8.5,
        },
    }
    return payload


def _validated_low_confidence_spiral_provider_step_video() -> dict[str, object]:
    payload = _validated_requested_spiral_provider_step_video()
    payload["valid"] = False
    payload["confidence"] = 0.50
    payload["fallback_recommendation"] = "manual_review"
    payload["data_quality_hint"] = "poor"
    payload["action_confirmation"]["confidence"] = 0.95
    payload["phase_segments"][0]["time_start"] = 4.0
    payload["phase_segments"][0]["time_end"] = 8.5
    payload["phase_segments"][0]["key_frame_hint"] = 7.5
    payload["phase_segments"][0]["confidence"] = 0.70
    payload["quality_flags"] = [
        "distant_view",
        "frequent_occlusion",
        "video_temporal_low_confidence",
        "video_temporal_not_high_confidence",
        "video_temporal_fallback_recommended",
    ]
    payload["validation"] = {
        "valid": False,
        "errors": [],
        "warnings": [
            "video_temporal_low_confidence",
            "video_temporal_not_high_confidence",
            "video_temporal_fallback_recommended",
        ],
        "duration_sec": 8.5,
    }
    return payload


def _validated_spin_without_exit_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "provider": "mimo",
        "model": "mimo-v2.5",
        "valid": True,
        "action_confirmation": {
            "action_family": "spin",
            "confirmed_action": "spin",
            "jump_type": "",
            "confidence": 0.85,
            "notes": "spin attempt stops without a labeled exit",
        },
        "phase_segments": [
            {"phase_code": "spin_entry", "phase_label": "spin entry", "time_start": 5.9, "time_end": 7.1, "key_frame_hint": 6.5, "confidence": 0.8, "valid": True},
            {"phase_code": "spin_main", "phase_label": "spin main", "time_start": 7.1, "time_end": 8.5, "key_frame_hint": 7.8, "confidence": 0.65, "valid": True},
        ],
        "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
        "macro_assessment": {},
        "overall_impression": "spin with natural stop",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.80,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": [],
        "validation": {"valid": True, "errors": [], "warnings": [], "duration_sec": 10.0},
    }
    return payload


def _validated_latest_weak_jump_late_timestamp_video() -> dict[str, object]:
    payload = _video_payload(0.80)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = ["action_incomplete", "low_height"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 6.15, "confidence": 0.85},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 7.95, "key_frame_hint": 7.65, "confidence": 0.80},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.95, "time_end": 8.25, "key_frame_hint": 8.05, "confidence": 0.75},
        {"phase_code": "air", "phase_label": "air", "time_start": 8.25, "time_end": 8.55, "key_frame_hint": 8.35, "confidence": 0.70},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 8.55, "time_end": 8.85, "key_frame_hint": 8.65, "confidence": 0.70},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.85, "time_end": 9.25, "key_frame_hint": 9.05, "confidence": 0.80},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 7.95, "A_air_sec": 8.35, "L_landing_sec": 8.55}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_missing_preparation_manual_review_video() -> dict[str, object]:
    payload = _video_payload(0.70)
    payload["fallback_recommendation"] = "manual_review"
    payload["quality_flags"] = ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.65, "key_frame_hint": 5.65, "confidence": 0.8},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 7.05, "key_frame_hint": 6.85, "confidence": 0.8},
        {"phase_code": "air", "phase_label": "air", "time_start": 7.05, "time_end": 7.45, "key_frame_hint": 7.25, "confidence": 0.7},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.45, "time_end": 7.85, "key_frame_hint": 7.65, "confidence": 0.8},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.85, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.8},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.85, "A_air_sec": 7.25, "L_landing_sec": 7.65}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_small_target_fallback_video(quality_flags: list[str] | None = None) -> dict[str, object]:
    payload = _video_payload(0.70)
    payload["fallback_recommendation"] = "use_sampled_frames"
    payload["quality_flags"] = quality_flags or ["low_resolution", "small_target", "distant_subject"]
    payload["phase_segments"] = [
        {
            "phase_code": "approach",
            "phase_label": "approach",
            "time_start": 4.65,
            "time_end": 5.75,
            "key_frame_hint": 5.15,
            "confidence": 0.75,
            "observations": ["distant small target"],
        },
        {
            "phase_code": "preparation",
            "phase_label": "preparation",
            "time_start": 5.75,
            "time_end": 6.00,
            "key_frame_hint": 5.90,
            "confidence": 0.70,
        },
        {
            "phase_code": "takeoff",
            "phase_label": "takeoff",
            "time_start": 6.00,
            "time_end": 6.20,
            "key_frame_hint": 6.05,
            "confidence": 0.70,
        },
        {
            "phase_code": "air",
            "phase_label": "air",
            "time_start": 6.20,
            "time_end": 6.50,
            "key_frame_hint": 6.40,
            "confidence": 0.50,
        },
        {
            "phase_code": "landing",
            "phase_label": "landing",
            "time_start": 6.50,
            "time_end": 6.75,
            "key_frame_hint": 6.60,
            "confidence": 0.65,
        },
        {
            "phase_code": "glide_out",
            "phase_label": "glide_out",
            "time_start": 6.75,
            "time_end": 8.45,
            "key_frame_hint": 7.55,
            "confidence": 0.80,
        },
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.05, "A_air_sec": 6.40, "L_landing_sec": 6.60}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_retry_glide_out_video() -> dict[str, object]:
    payload = _video_payload(0.85)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = ["video_temporal_quality_retry"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.45, "key_frame_hint": 5.65, "confidence": 0.9},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.95, "key_frame_hint": 6.75, "confidence": 0.8},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.25, "key_frame_hint": 7.05, "confidence": 0.75},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.65, "key_frame_hint": 7.35, "confidence": 0.8},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.65, "time_end": 8.65, "key_frame_hint": 8.15, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.75, "A_air_sec": 7.05, "L_landing_sec": 7.35}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_late_retry_video() -> dict[str, object]:
    payload = _video_payload(0.65)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = ["video_temporal_not_high_confidence", "video_temporal_quality_retry"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.75, "key_frame_hint": 6.15, "confidence": 0.8},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.75, "time_end": 7.85, "key_frame_hint": 7.45, "confidence": 0.7},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.85, "time_end": 8.25, "key_frame_hint": 8.05, "confidence": 0.6},
        {"phase_code": "air", "phase_label": "air", "time_start": 8.25, "time_end": 8.65, "key_frame_hint": 8.45, "confidence": 0.6},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 8.65, "time_end": 8.95, "key_frame_hint": 8.75, "confidence": 0.6},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.95, "time_end": 9.25, "key_frame_hint": 9.15, "confidence": 0.7},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 8.05, "A_air_sec": 8.45, "L_landing_sec": 8.75}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_low_confidence_quality_retry_video() -> dict[str, object]:
    payload = _video_payload(0.50)
    payload["fallback_recommendation"] = "manual_review"
    payload["quality_flags"] = [
        "distant",
        "low_resolution",
        "video_temporal_low_confidence",
        "video_temporal_not_high_confidence",
        "video_temporal_fallback_recommended",
        "video_temporal_quality_retry",
    ]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.45, "key_frame_hint": 5.65, "confidence": 0.8},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.85, "key_frame_hint": 6.65, "confidence": 0.7},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.85, "time_end": 7.25, "key_frame_hint": 7.05, "confidence": 0.6},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.45, "key_frame_hint": 7.35, "confidence": 0.6},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.45, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.7},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.75, "A_air_sec": 7.05, "L_landing_sec": 7.35}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_high_confidence_fallback_with_glide_out_motion_video() -> dict[str, object]:
    payload = _video_payload(0.85)
    payload["fallback_recommendation"] = "use_sampled_frames"
    payload["quality_flags"] = ["video_temporal_fallback_recommended"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.25, "key_frame_hint": 5.45, "confidence": 0.9},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.25, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.85},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.8, "confidence": 0.8},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.25, "key_frame_hint": 7.1, "confidence": 0.8},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.45, "key_frame_hint": 7.35, "confidence": 0.85},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.45, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.8, "A_air_sec": 7.1, "L_landing_sec": 7.35}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_high_confidence_fallback_late_tal_after_preparation_motion_video() -> dict[str, object]:
    payload = _video_payload(0.85)
    payload["fallback_recommendation"] = "use_sampled_frames"
    payload["quality_flags"] = [
        "brief foreground occlusion, skater visible again during glide_out",
        "video_temporal_fallback_recommended",
    ]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.45, "key_frame_hint": 6.15, "confidence": 0.9},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.45, "time_end": 7.85, "key_frame_hint": 7.65, "confidence": 0.85},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.85, "time_end": 8.15, "key_frame_hint": 7.95, "confidence": 0.8},
        {"phase_code": "air", "phase_label": "air", "time_start": 8.15, "time_end": 8.35, "key_frame_hint": 8.25, "confidence": 0.75},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 8.35, "time_end": 8.55, "key_frame_hint": 8.4, "confidence": 0.8},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.55, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 7.95, "A_air_sec": 8.25, "L_landing_sec": 8.4}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_high_confidence_use_timestamps_with_glide_out_motion_video(confidence: float = 0.85) -> dict[str, object]:
    payload = _video_payload(confidence)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = []
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.25, "key_frame_hint": 5.65, "confidence": 0.9},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.25, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.85},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.75, "confidence": 0.8},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.25, "key_frame_hint": 7.15, "confidence": 0.8},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.55, "key_frame_hint": 7.35, "confidence": 0.8},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.55, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.35}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_high_confidence_early_compressed_occluded_timestamp_video() -> dict[str, object]:
    payload = _video_payload(0.85)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = ["brief foreground occlusion after the reported core jump"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.75, "key_frame_hint": 5.15, "confidence": 0.9},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.75, "time_end": 6.25, "key_frame_hint": 5.95, "confidence": 0.85},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.25, "time_end": 6.45, "key_frame_hint": 6.35, "confidence": 0.85},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.45, "time_end": 6.65, "key_frame_hint": 6.55, "confidence": 0.8},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 6.65, "time_end": 6.85, "key_frame_hint": 6.75, "confidence": 0.85},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 6.85, "time_end": 9.25, "key_frame_hint": 7.15, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.35, "A_air_sec": 6.55, "L_landing_sec": 6.75}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_high_confidence_retry_early_compressed_occluded_timestamp_video() -> dict[str, object]:
    payload = _validated_high_confidence_early_compressed_occluded_timestamp_video()
    payload["quality_flags"] = [
        *[flag for flag in payload.get("quality_flags", []) if isinstance(flag, str)],
        "video_temporal_quality_retry",
    ]
    return payload


def _validated_latest_retry_early_main_motion_cluster_video() -> dict[str, object]:
    payload = _video_payload(0.80)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = ["video_temporal_quality_retry"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.15, "key_frame_hint": 5.45, "confidence": 0.9},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.15, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.9},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.75, "confidence": 0.85},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.45, "key_frame_hint": 7.15, "confidence": 0.85},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.45, "time_end": 7.85, "key_frame_hint": 7.65, "confidence": 0.85},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.85, "time_end": 8.65, "key_frame_hint": 8.15, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.65}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_uncertain_timestamp_early_main_motion_cluster_video() -> dict[str, object]:
    payload = _video_payload(0.65)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = [
        "video_temporal_not_high_confidence",
        "video_temporal_phase_3_low_confidence",
        "落冰阶段存在短暂遮挡，影响精确判断",
    ]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.32, "key_frame_hint": 5.65, "confidence": 0.8},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.32, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.7},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.65, "time_end": 7.18, "key_frame_hint": 6.92, "confidence": 0.6},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.18, "time_end": 7.65, "key_frame_hint": 7.35, "confidence": 0.5, "valid": False},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.65, "time_end": 8.65, "key_frame_hint": 7.95, "confidence": 0.6},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.45, "A_air_sec": 6.92, "L_landing_sec": 7.35}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_high_confidence_late_timestamp_with_early_skeleton_video() -> dict[str, object]:
    payload = _video_payload(0.85)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = ["distance", "slight_blur"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 6.65, "confidence": 0.9},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 7.75, "key_frame_hint": 7.55, "confidence": 0.85},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.75, "time_end": 8.05, "key_frame_hint": 7.85, "confidence": 0.8},
        {"phase_code": "air", "phase_label": "air", "time_start": 8.05, "time_end": 8.35, "key_frame_hint": 8.2, "confidence": 0.75},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 8.35, "time_end": 8.65, "key_frame_hint": 8.45, "confidence": 0.8},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.65, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 7.85, "A_air_sec": 8.2, "L_landing_sec": 8.45}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_failed_landing_core_motion_supported_video() -> dict[str, object]:
    payload = _video_payload(0.70)
    payload["fallback_recommendation"] = "use_video_timestamps"
    payload["quality_flags"] = ["部分镜头有旁人遮挡，影响对起跳细节的精确判断。", "video_temporal_not_high_confidence"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 6.15, "confidence": 0.8},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 7.65, "key_frame_hint": 7.45, "confidence": 0.7},
        {
            "phase_code": "takeoff",
            "phase_label": "takeoff",
            "time_start": 7.65,
            "time_end": 7.95,
            "key_frame_hint": 7.75,
            "confidence": 0.6,
            "issues": ["起跳瞬间身体前倾，轴心不稳，离冰高度很低。"],
        },
        {"phase_code": "air", "phase_label": "air", "time_start": 7.95, "time_end": 8.25, "key_frame_hint": 8.05, "confidence": 0.6},
        {
            "phase_code": "landing",
            "phase_label": "landing",
            "time_start": 8.25,
            "time_end": 8.45,
            "key_frame_hint": 8.35,
            "confidence": 0.7,
            "issues": ["落冰瞬间重心不稳，有踉跄，未能保持流畅滑出。"],
        },
        {
            "phase_code": "glide_out",
            "phase_label": "glide_out",
            "time_start": 8.45,
            "time_end": 9.25,
            "key_frame_hint": 8.65,
            "confidence": 0.8,
            "issues": ["滑出姿态不舒展，未能展现良好的滑出弧线。"],
        },
    ]
    payload["key_moments"] = {"T_takeoff_sec": 7.75, "A_air_sec": 8.05, "L_landing_sec": 8.35}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _validated_light_occlusion_early_tal_with_glide_out_motion_video(
    quality_flags: list[str] | None = None,
    confidence: float = 0.80,
) -> dict[str, object]:
    payload = _video_payload(confidence)
    payload["fallback_recommendation"] = "use_sampled_frames"
    payload["quality_flags"] = quality_flags or ["部分动作存在轻微遮挡", "video_temporal_fallback_recommended"]
    payload["phase_segments"] = [
        {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.85, "key_frame_hint": 5.45, "confidence": 0.9},
        {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.85, "time_end": 6.45, "key_frame_hint": 6.25, "confidence": 0.9},
        {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.75, "key_frame_hint": 6.55, "confidence": 0.85},
        {"phase_code": "air", "phase_label": "air", "time_start": 6.75, "time_end": 7.25, "key_frame_hint": 6.95, "confidence": 0.8},
        {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.55, "key_frame_hint": 7.35, "confidence": 0.9},
        {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.55, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.9},
    ]
    payload["key_moments"] = {"T_takeoff_sec": 6.55, "A_air_sec": 6.95, "L_landing_sec": 7.35}
    return validate_video_temporal_payload(
        normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
        duration_sec=9.568,
    )


def _motion_scores() -> dict[str, object]:
    return {
        "selected": [
            {"frame_id": "frame_0001", "timestamp": 1.05, "motion_score": 0.2},
            {"frame_id": "frame_0002", "timestamp": 1.2, "motion_score": 0.45},
            {"frame_id": "frame_0003", "timestamp": 1.3, "motion_score": 0.95},
            {"frame_id": "frame_0004", "timestamp": 1.55, "motion_score": 0.8},
            {"frame_id": "frame_0005", "timestamp": 1.95, "motion_score": 0.9},
        ],
        "scores": [0.2, 0.45, 0.95, 0.8, 0.9],
    }


def _motion_series() -> dict[str, object]:
    return {
        "frame_rate": 10,
        "window_start": 1.0,
        "scores": [0.05, 0.1, 0.2, 0.95, 0.4, 0.7, 0.1, 0.2, 0.1, 0.9, 0.2, 0.1, 0.05],
        "selected": [
            {"frame_id": "frame_0001", "timestamp": 1.0, "motion_score": 0.05},
            {"frame_id": "frame_0002", "timestamp": 1.5, "motion_score": 0.7},
            {"frame_id": "frame_0003", "timestamp": 1.9, "motion_score": 0.9},
        ],
    }


def _skeleton() -> dict[str, object]:
    return {
        "key_frame_candidates": {
            "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.81},
            "A": {"frame_id": "frame_0004", "timestamp": 1.55, "confidence": 0.79},
            "L": {"frame_id": "frame_0005", "timestamp": 1.95, "confidence": 0.82},
        }
    }


class VideoTemporalResolverTests(unittest.TestCase):
    def test_high_confidence_uses_video_ai_refined_plan(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual(plan["confidence"], 0.86)
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["takeoff", "air", "landing"])
        self.assertLessEqual(len(plan["selected"]), 12)
        self.assertEqual(plan["selected"][0]["frame_id"], "semantic_0001")
        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)

    def test_medium_confidence_blended_prefers_skeleton_inside_video_interval(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.68),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_skeleton_takeoff_motion_peak")

    def test_moderate_jump_tal_overrides_advisory_video_fallback(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_moderate_fallback_video(0.60),
            None,
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_moderate_confidence_tal_used", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertGreaterEqual(len(plan["selected"]), 3)
        self.assertTrue(semantic_keyframes_are_reliable(plan))
        core = {item["phase_code"]: item for item in plan["selected"] if item["phase_code"] in {"takeoff", "landing"}}
        self.assertEqual(core["takeoff"]["max_refinement_delta_sec"], 0.20)
        self.assertEqual(core["takeoff"]["max_refinement_backward_delta_sec"], 0.08)
        self.assertEqual(core["landing"]["max_refinement_delta_sec"], 0.30)
        self.assertEqual(core["landing"]["refinement_window_seconds"], 0.30)
        self.assertEqual(core["landing"]["phase_time_start_refinement_tolerance_sec"], 0.22)
        self.assertEqual(core["landing"]["phase_time_end_refinement_tolerance_sec"], 0.22)
        self.assertIn("video_temporal_resolver_takeoff_refinement_delta_expanded", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_takeoff_backward_refinement_guard", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_landing_refinement_phase_tolerance", plan["quality_flags"])

    def test_high_confidence_jump_tal_overrides_advisory_video_fallback_as_blended(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_moderate_fallback_video(0.85),
            None,
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))
        takeoff = next(item for item in plan["selected"] if item["phase_code"] == "takeoff")
        landing = next(item for item in plan["selected"] if item["phase_code"] == "landing")
        self.assertEqual(takeoff["max_refinement_delta_sec"], 0.20)
        self.assertEqual(takeoff["max_refinement_backward_delta_sec"], 0.08)
        self.assertEqual(landing["max_refinement_delta_sec"], 0.30)
        self.assertEqual(landing["refinement_window_seconds"], 0.30)
        self.assertEqual(landing["phase_time_start_refinement_tolerance_sec"], 0.22)
        self.assertEqual(landing["phase_time_end_refinement_tolerance_sec"], 0.22)
        self.assertIn("video_temporal_resolver_takeoff_refinement_delta_expanded", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_takeoff_backward_refinement_guard", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_landing_refinement_phase_tolerance", plan["quality_flags"])

    def test_failed_landing_followthrough_does_not_reject_coherent_tal(self) -> None:
        payload = _video_payload(0.75)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["video_temporal_not_high_confidence", "画面较远，细节不够清晰"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.45, "key_frame_hint": 5.05, "confidence": 0.9, "observations": ["儿童滑行者从远处向镜头方向滑行，速度较慢。"]},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.45, "time_end": 6.05, "key_frame_hint": 5.85, "confidence": 0.85, "issues": ["起跳前滑行速度不足，身体姿态不稳定。"]},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.05, "time_end": 6.45, "key_frame_hint": 6.25, "confidence": 0.8, "issues": ["起跳高度不足，离冰动作不清晰。"]},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.45, "time_end": 6.85, "key_frame_hint": 6.65, "confidence": 0.75, "issues": ["空中时间短，旋转不充分。"]},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 6.85, "time_end": 7.15, "key_frame_hint": 6.95, "confidence": 0.8, "observations": ["落冰后立即失去平衡，未能稳定滑出。"], "issues": ["落冰点不准确，重心控制差，导致摔倒。"]},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.15, "time_end": 7.65, "key_frame_hint": 7.25, "confidence": 0.7, "observations": ["落冰失败，未能完成有效的滑出动作。"], "issues": ["动作中断，未形成连续滑出。"]},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.25, "A_air_sec": 6.65, "L_landing_sec": 6.95}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.25,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0017", "timestamp": 6.15, "motion_score": 0.0701},
                {"frame_id": "frame_0019", "timestamp": 6.525, "motion_score": 0.0563},
                {"frame_id": "frame_0021", "timestamp": 7.15, "motion_score": 0.1287},
                {"frame_id": "frame_0022", "timestamp": 7.213, "motion_score": 0.1538},
                {"frame_id": "frame_0023", "timestamp": 7.275, "motion_score": 0.199},
                {"frame_id": "frame_0024", "timestamp": 7.338, "motion_score": 0.1792},
                {"frame_id": "frame_0026", "timestamp": 7.463, "motion_score": 0.1954},
                {"frame_id": "frame_0027", "timestamp": 7.525, "motion_score": 0.1971},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.25,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_failed_landing_motion_supported", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_supported_despite_late_motion", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_rejected_retry_flags_do_not_make_saved_original_semantic_frames_unreliable(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_moderate_fallback_video(0.80),
            None,
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )
        plan["quality_flags"] = [
            *plan["quality_flags"],
            "video_temporal_resolver_low_video_confidence",
            "video_temporal_resolver_partial_skeleton_fallback",
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            "video_temporal_quality_retry_rejected",
        ]
        plan["video_temporal_quality_retry_rejection_flags"] = [
            "video_temporal_resolver_low_video_confidence",
            "video_temporal_resolver_partial_skeleton_fallback",
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
        ]

        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_moderate_compressed_tal_with_later_motion_conflict_rejects_override(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_sampled_frames"
        payload["quality_flags"] = ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.95, "key_frame_hint": 5.15, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.95, "time_end": 6.35, "key_frame_hint": 6.15, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.35, "time_end": 6.55, "key_frame_hint": 6.45, "confidence": 0.7},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.55, "time_end": 6.85, "key_frame_hint": 6.65, "confidence": 0.7},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 6.85, "time_end": 7.05, "key_frame_hint": 6.95, "confidence": 0.7},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.05, "time_end": 8.15, "key_frame_hint": 7.25, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.45, "A_air_sec": 6.65, "L_landing_sec": 6.95}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.02] * 31 + [0.05, 0.04, 0.05, 0.03, 0.04, 0.03, 0.04, 0.04] + [0.02] * 8 + [0.19, 0.23, 0.22, 0.21],
            "selected": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertGreaterEqual(len(plan["selected"]), 3)
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_rejected_semantic_candidates_preserved", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_moderate_occluded_compressed_tal_rejects_even_when_provider_says_use_timestamps(self) -> None:
        payload = _video_payload(0.60)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["关键动作被严重遮挡", "video_temporal_not_high_confidence"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.65, "key_frame_hint": 5.15, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.65, "time_end": 6.05, "key_frame_hint": 5.95, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.05, "time_end": 6.35, "key_frame_hint": 6.15, "confidence": 0.7},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.35, "time_end": 6.85, "key_frame_hint": 6.55, "confidence": 0.6},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 6.85, "time_end": 7.15, "key_frame_hint": 6.95, "confidence": 0.5, "valid": False},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.15, "time_end": 7.65, "key_frame_hint": 7.45, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.15, "A_air_sec": 6.55, "L_landing_sec": 6.95}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.02] * 31 + [0.05, 0.04, 0.05, 0.03, 0.04, 0.03, 0.04, 0.04] + [0.02] * 8 + [0.19, 0.23, 0.22, 0.21],
            "selected": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_moderate_occluded_late_tal_after_strong_motion_rejects_override(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["主要动作在镜头遮挡和晃动中完成", "video_temporal_not_high_confidence"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.45, "key_frame_hint": 6.15, "confidence": 0.7},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.45, "time_end": 8.05, "key_frame_hint": 7.75, "confidence": 0.6},
            {"phase_code": "air", "phase_label": "air", "time_start": 8.05, "time_end": 8.45, "key_frame_hint": 8.25, "confidence": 0.6},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.45, "time_end": 8.85, "key_frame_hint": 8.55, "confidence": 0.7},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.85, "time_end": 9.25, "key_frame_hint": 8.95, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.85, "A_air_sec": 8.25, "L_landing_sec": 8.55}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.02] * 47 + [0.10, 0.19, 0.23, 0.22, 0.21, 0.12, 0.25, 0.23, 0.13] + [0.04] * 18,
            "selected": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_moderate_timestamp_late_tal_after_motion_peak_rejects_override(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["light_occlusion", "video_temporal_not_high_confidence"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 6.15, "confidence": 0.8},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 8.15, "key_frame_hint": 7.65, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 8.15, "time_end": 8.45, "key_frame_hint": 8.25, "confidence": 0.7},
            {"phase_code": "air", "phase_label": "air", "time_start": 8.45, "time_end": 8.75, "key_frame_hint": 8.6, "confidence": 0.7},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.75, "time_end": 8.95, "key_frame_hint": 8.85, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.95, "time_end": 9.25, "key_frame_hint": 9.1, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 8.25, "A_air_sec": 8.6, "L_landing_sec": 8.85}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_supported_core_tal_survives_late_glide_out_motion_peak(self) -> None:
        payload = _video_payload(0.75)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["distant_view", "light_occlusion", "video_temporal_not_high_confidence"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 1.15, "time_end": 2.95, "key_frame_hint": 2.65, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.95, "time_end": 3.25, "key_frame_hint": 3.05, "confidence": 0.75},
            {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.65, "key_frame_hint": 3.45, "confidence": 0.7},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 3.65, "time_end": 3.95, "key_frame_hint": 3.75, "confidence": 0.7},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 3.95, "time_end": 4.95, "key_frame_hint": 4.15, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 3.05, "A_air_sec": 3.45, "L_landing_sec": 3.75}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=5.75,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 1.15,
            "scores": [
                0.03,
                0.04,
                0.05,
                0.05,
                0.1302,
                0.1839,
                0.1084,
                0.04,
                0.04,
                0.05,
                0.1244,
                0.0954,
                0.161,
                0.1197,
                0.05,
                0.0725,
                0.081,
                0.04,
                0.086,
                0.0547,
                0.0613,
                0.1526,
                0.0616,
                0.0848,
                0.1019,
                0.0565,
                0.0994,
                0.0808,
                0.0363,
                0.0173,
                0.0503,
                0.0258,
                0.0715,
                0.1149,
                0.0925,
                0.114,
                0.1413,
                0.1438,
                0.1416,
                0.084,
                0.1366,
                0.1106,
                0.1016,
                0.0892,
                0.04,
                0.04,
                0.0918,
                0.2025,
                0.1421,
            ],
            "selected": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=5.75,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_motion_supported_despite_late_motion", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_moderate_timestamp_landing_in_glide_tail_rejects_override(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["light_occlusion"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.85, "key_frame_hint": 5.65, "confidence": 0.8},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.85, "time_end": 7.35, "key_frame_hint": 7.05, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.35, "time_end": 7.65, "key_frame_hint": 7.35, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.65, "time_end": 8.05, "key_frame_hint": 7.75, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.05, "time_end": 8.35, "key_frame_hint": 8.25, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.35, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.9},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.35, "A_air_sec": 7.75, "L_landing_sec": 8.25}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_moderate_timestamp_landing_after_motion_cluster_rejects_override(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["other skater passes through but target remains visible"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.45, "key_frame_hint": 5.65, "confidence": 0.8},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.45, "time_end": 7.15, "key_frame_hint": 6.85, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.15, "time_end": 7.55, "key_frame_hint": 7.35, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.55, "time_end": 8.05, "key_frame_hint": 7.75, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.05, "time_end": 8.45, "key_frame_hint": 8.25, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.45, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.35, "A_air_sec": 7.75, "L_landing_sec": 8.25}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_occluded_late_tal_after_strong_motion_rejects_override(self) -> None:
        payload = _video_payload(0.85)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["brief_occlusion"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 6.65, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 7.75, "key_frame_hint": 7.55, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.75, "time_end": 8.05, "key_frame_hint": 7.85, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 8.05, "time_end": 8.35, "key_frame_hint": 8.2, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.35, "time_end": 8.65, "key_frame_hint": 8.45, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.65, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.9},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.85, "A_air_sec": 8.2, "L_landing_sec": 8.45}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_fallback_early_tal_before_later_motion_rejects_when_severely_occluded(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_sampled_frames"
        payload["quality_flags"] = ["video_temporal_fallback_recommended", "关键动作被严重遮挡"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.85, "key_frame_hint": 5.65, "confidence": 0.85},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.85, "time_end": 6.45, "key_frame_hint": 6.25, "confidence": 0.9},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.75, "key_frame_hint": 6.55, "confidence": 0.85},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.75, "time_end": 7.25, "key_frame_hint": 6.95, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.55, "key_frame_hint": 7.35, "confidence": 0.9},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.55, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.9},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.55, "A_air_sec": 6.95, "L_landing_sec": 7.35}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_coherent_tal_later_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_rejected_semantic_candidates_preserved", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_occluded_early_tal_before_glide_out_motion_keeps_timestamps(self) -> None:
        payload = _video_payload(0.85)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["视频较短，有轻微遮挡，影响部分细节判断。"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.25, "key_frame_hint": 5.65, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.25, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.75, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.25, "key_frame_hint": 7.15, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.55, "key_frame_hint": 7.35, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.55, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.9},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.35}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_latest_high_confidence_fallback_shape_selects_core_semantic_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_latest_high_confidence_fallback_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "scores": [0.02] * 30,
                "selected": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertGreaterEqual(len(plan["selected"]), 3)
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_latest_high_confidence_fallback_shape_keeps_core_frames_when_landing_has_motion(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_latest_high_confidence_fallback_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.03},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.04},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.23},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.24},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertGreaterEqual(len(plan["selected"]), 3)
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_spiral_fallback_with_coherent_phases_selects_semantic_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_spiral_step_family_fallback_video(),
            None,
            None,
            video_duration_sec=12.0,
            analysis_profile="spiral",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_profile_phases_used", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["spiral_entry", "spiral_hold", "spiral_exit"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [5.8, 7.5, 9.5])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_spiral_resolver_ignores_extra_step_phase(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_spiral_with_extra_step_phase_video(),
            None,
            None,
            video_duration_sec=8.5,
            analysis_profile="spiral",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_profile_phases_used", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["spiral_entry", "spiral_hold", "spiral_exit"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [2.5, 4.0, 6.5])
        self.assertNotIn("video_temporal_resolver_phase_step_sequence_fallback", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_non_jump_request_with_provider_jump_marks_profile_mismatch_without_formal_frames(self) -> None:
        video = _video_payload(0.85)
        video["action_confirmation"] = {
            "action_family": "jump",
            "confirmed_action": "Toe Loop",
            "jump_type": "Toe Loop",
            "confidence": 0.85,
        }
        video["fallback_recommendation"] = "use_video_timestamps"

        plan = resolve_semantic_keyframes(
            video,
            None,
            None,
            video_duration_sec=3.0,
            analysis_profile="spiral",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual(plan["selected"], [])
        self.assertIn("video_temporal_resolver_profile_mismatch", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_no_selected_frames", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_non_jump_provider_profile_overrides_mistyped_request_profile(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_requested_spiral_provider_step_video(),
            None,
            None,
            video_duration_sec=8.5,
            analysis_profile="spiral",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_profile_overridden_by_video_ai", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_profile_phases_used", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["step_sequence", "step_sequence", "step_sequence"])
        self.assertEqual([item["key_moment"] for item in plan["selected"]], ["step_entry", "step_mid", "step_exit"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.796, 4.1, 6.404])
        self.assertIn("video_temporal_resolver_step_sequence_multi_frame_coverage", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_low_confidence_spiral_provider_step_sequence_uses_coverage_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_low_confidence_spiral_provider_step_video(),
            None,
            None,
            video_duration_sec=8.5,
            analysis_profile="spiral",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_profile_overridden_by_video_ai", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_profile_overridden_by_video_ai_low_confidence_step_sequence", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_profile_phases_used", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["step_sequence", "step_sequence", "step_sequence"])
        self.assertEqual([item["key_moment"] for item in plan["selected"]], ["step_entry", "step_mid", "step_exit"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [4.81, 6.25, 7.69])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_step_sequence_single_long_phase_expands_to_entry_mid_exit_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_requested_spiral_provider_step_video(),
            None,
            None,
            video_duration_sec=8.5,
            analysis_profile="step",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual(len(plan["selected"]), 3)
        self.assertEqual([item["key_moment"] for item in plan["selected"]], ["step_entry", "step_mid", "step_exit"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.796, 4.1, 6.404])
        self.assertEqual(
            [item["selection_reason"] for item in plan["selected"]],
            ["video_phase_range_step_sequence_coverage"] * 3,
        )
        self.assertIn("video_temporal_resolver_step_sequence_multi_frame_coverage", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_short_step_sequence_keeps_single_hint_frame(self) -> None:
        video = _validated_requested_spiral_provider_step_video()
        video["phase_segments"] = [
            {
                "phase_code": "step_sequence",
                "phase_label": "step sequence",
                "time_start": 0.5,
                "time_end": 1.3,
                "key_frame_hint": 0.9,
                "confidence": 0.9,
                "valid": True,
            }
        ]
        plan = resolve_semantic_keyframes(
            video,
            None,
            None,
            video_duration_sec=2.0,
            analysis_profile="step",
        )

        self.assertEqual(len(plan["selected"]), 1)
        self.assertEqual(plan["selected"][0]["timestamp"], 0.9)
        self.assertNotIn("video_temporal_resolver_step_sequence_multi_frame_coverage", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_spin_without_exit_infers_followthrough_frame(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_spin_without_exit_video(),
            None,
            None,
            video_duration_sec=10.0,
            analysis_profile="spin",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_inferred_spin_exit_phase", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["spin_entry", "spin_main", "spin_exit"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [6.5, 7.8, 9.1])
        self.assertEqual(plan["selected"][2]["selection_reason"], "inferred_spin_exit_after_main")
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_spin_without_exit_uses_source_duration_guard_near_video_tail(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_spin_without_exit_video(),
            None,
            None,
            video_duration_sec=9.101667,
            analysis_profile="spin",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_inferred_spin_exit_phase", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["spin_entry", "spin_main", "spin_exit"])
        self.assertEqual(plan["selected"][2]["timestamp"], 8.761)
        self.assertLess(plan["selected"][2]["timestamp"], 9.101667)
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_latest_weak_jump_late_timestamps_use_motion_cluster_fallback(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_latest_weak_jump_late_timestamp_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0029", "timestamp": 8.088, "motion_score": 0.1289},
                    {"frame_id": "frame_0031", "timestamp": 8.338, "motion_score": 0.0404},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_coherent_tal_weak_jump_late_main_motion_cluster_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [7.4, 7.775, 7.963])
        self.assertEqual(plan["selected"][2]["visibility_repair_max_delta_sec"], 0.12)
        self.assertTrue(plan["selected"][2]["visibility_repair_preserve_timestamp"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_quality_retry_glide_out_motion_does_not_reject_coherent_tal(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_retry_glide_out_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.03},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.04},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.23},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.24},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_failed_landing_core_motion_support_keeps_formal_coherent_tal(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_failed_landing_core_motion_supported_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0012", "timestamp": 5.838, "confidence": 0.411},
                    "A": {"frame_id": "frame_0014", "timestamp": 5.963, "confidence": 0.608},
                    "L": {"frame_id": "frame_0027", "timestamp": 7.525, "confidence": 0.791},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0029", "timestamp": 8.088, "motion_score": 0.1289},
                    {"frame_id": "frame_0031", "timestamp": 8.338, "motion_score": 0.0404},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual(
            [(item["phase_code"], item["timestamp"]) for item in plan["selected"][:3]],
            [("takeoff", 7.75), ("air", 8.05), ("landing", 8.35)],
        )
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_moderate_quality_retry_with_timestamp_recommendation_keeps_glide_out_motion_tal(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = [
            "brief_foreground_occlusion",
            "video_temporal_not_high_confidence",
            "video_temporal_quality_retry",
        ]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.95, "key_frame_hint": 5.15, "confidence": 0.8},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.95, "time_end": 6.45, "key_frame_hint": 6.25, "confidence": 0.7},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.75, "key_frame_hint": 6.6, "confidence": 0.6},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.75, "time_end": 7.15, "key_frame_hint": 6.95, "confidence": 0.6},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.15, "time_end": 7.45, "key_frame_hint": 7.3, "confidence": 0.6},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.45, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.7},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.6, "A_air_sec": 6.95, "L_landing_sec": 7.3}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0017", "timestamp": 6.588, "motion_score": 0.0548},
                    {"frame_id": "frame_0021", "timestamp": 7.025, "motion_score": 0.042},
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_moderate_uncertain_timestamp_recommendation_rejects_late_tail_tal(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = [
            "视频清晰度一般，对精细技术判断有一定影响。",
            "video_temporal_not_high_confidence",
        ]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.25, "key_frame_hint": 6.15, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.25, "time_end": 7.85, "key_frame_hint": 7.55, "confidence": 0.6},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.85, "time_end": 8.25, "key_frame_hint": 8.05, "confidence": 0.6},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.25, "time_end": 8.45, "key_frame_hint": 8.35, "confidence": 0.7},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.45, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.7},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.55, "A_air_sec": 8.05, "L_landing_sec": 8.35}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0029", "timestamp": 8.088, "motion_score": 0.1289},
                    {"frame_id": "frame_0031", "timestamp": 8.338, "motion_score": 0.0404},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_quality_retry_late_tal_after_motion_peak_is_not_accepted(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_late_retry_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.03},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.04},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.23},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.24},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_quality_retry_tail_tal_with_unclean_core_is_not_accepted(self) -> None:
        payload = _video_payload(0.65)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = [
            "轻微遮挡",
            "动作不完全清晰",
            "video_temporal_not_high_confidence",
            "video_temporal_quality_retry",
        ]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 5.85, "confidence": 0.8},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 8.15, "key_frame_hint": 7.65, "confidence": 0.7},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 8.15, "time_end": 8.45, "key_frame_hint": 8.25, "confidence": 0.6},
            {"phase_code": "air", "phase_label": "air", "time_start": 8.45, "time_end": 8.75, "key_frame_hint": 8.55, "confidence": 0.5, "valid": False},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.75, "time_end": 8.95, "key_frame_hint": 8.85, "confidence": 0.6},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.95, "time_end": 9.25, "key_frame_hint": 9.15, "confidence": 0.7},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 8.25, "A_air_sec": 8.55, "L_landing_sec": 8.85}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0031", "timestamp": 8.338, "motion_score": 0.0404},
                    {"frame_id": "frame_0032", "timestamp": 8.838, "motion_score": 0.0205},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_retry_tail_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_quality_retry_preparation_motion_near_takeoff_rejects_tail_tal(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_late_retry_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0031", "timestamp": 8.338, "motion_score": 0.0404},
                    {"frame_id": "frame_0032", "timestamp": 8.838, "motion_score": 0.0205},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_retry_tail_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_quality_retry_takeoff_boundary_motion_still_rejects_late_tal(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_late_retry_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.03},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.04},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.23},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.24},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.23},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_small_target_fallback_glide_out_motion_keeps_coherent_tal(self) -> None:
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.02] * 38
            + [0.06, 0.05, 0.04, 0.05, 0.06]
            + [0.02] * 7
            + [0.19, 0.23, 0.22, 0.21, 0.18],
            "selected": [],
        }

        plan = resolve_semantic_keyframes(
            _validated_small_target_fallback_video(),
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [6.05, 6.4, 6.6])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_small_target_glide_out_motion_still_rejects_occlusion_risk(self) -> None:
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.02] * 38
            + [0.06, 0.05, 0.04, 0.05, 0.06]
            + [0.02] * 7
            + [0.19, 0.23, 0.22, 0.21, 0.18],
            "selected": [],
        }

        plan = resolve_semantic_keyframes(
            _validated_small_target_fallback_video(["low_resolution", "small_target", "brief_occlusion"]),
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_coherent_tal_later_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_fallback_glide_out_motion_keeps_coherent_tal(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_high_confidence_fallback_with_glide_out_motion_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_advisory_fallback_revisible_glide_out_tail_rejects_core_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_high_confidence_fallback_late_tal_after_preparation_motion_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "scores": [0.02] * 48 + [0.08, 0.11, 0.10, 0.09, 0.08] + [0.03] * 21,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0031", "timestamp": 8.338, "motion_score": 0.0404},
                    {"frame_id": "frame_0032", "timestamp": 8.838, "motion_score": 0.0205},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_revisible_glide_out_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_use_timestamps_glide_out_motion_keeps_coherent_tal(self) -> None:
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            _validated_high_confidence_use_timestamps_with_glide_out_motion_video(0.85),
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))
        landing = next(item for item in plan["selected"] if item["phase_code"] == "landing")
        self.assertNotIn("phase_time_start_refinement_tolerance_sec", landing)

        low_confidence_plan = resolve_semantic_keyframes(
            {
                **_validated_high_confidence_use_timestamps_with_glide_out_motion_video(0.70),
                "quality_flags": ["brief_occlusion", "video_temporal_not_high_confidence"],
            },
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", low_confidence_plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(low_confidence_plan))

    def test_high_confidence_weak_jump_late_timestamp_uses_motion_cluster_fallback(self) -> None:
        payload = _video_payload(0.85)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["partial occlusion", "limited takeoff height"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.75, "key_frame_hint": 6.15, "confidence": 0.95},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.75, "time_end": 7.55, "key_frame_hint": 7.25, "confidence": 0.90},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.55, "time_end": 7.85, "key_frame_hint": 7.65, "confidence": 0.85},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.85, "time_end": 8.15, "key_frame_hint": 8.0, "confidence": 0.80},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.15, "time_end": 8.45, "key_frame_hint": 8.25, "confidence": 0.85},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.45, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.90},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.65, "A_air_sec": 8.0, "L_landing_sec": 8.25}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_coherent_tal_late_main_motion_cluster_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [7.4, 7.775, 7.963])
        self.assertEqual(plan["selected"][2]["visibility_repair_max_delta_sec"], 0.12)
        self.assertTrue(plan["selected"][2]["visibility_repair_preserve_timestamp"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_occluded_late_motion_conflict_uses_motion_cluster_fallback(self) -> None:
        payload = _video_payload(0.85)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["brief occlusion in the second half"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.75, "key_frame_hint": 6.15, "confidence": 0.95},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.75, "time_end": 7.65, "key_frame_hint": 7.45, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.65, "time_end": 8.05, "key_frame_hint": 7.85, "confidence": 0.80},
            {"phase_code": "air", "phase_label": "air", "time_start": 8.05, "time_end": 8.35, "key_frame_hint": 8.20, "confidence": 0.80},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.35, "time_end": 8.65, "key_frame_hint": 8.45, "confidence": 0.85},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.65, "time_end": 9.25, "key_frame_hint": 8.95, "confidence": 0.90},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.85, "A_air_sec": 8.20, "L_landing_sec": 8.45}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [7.4, 7.775, 7.963])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_quality_retry_mixed_early_late_conflict_uses_motion_cluster_fallback(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = [
            "video_temporal_not_high_confidence",
            "video_temporal_quality_retry",
            "brief occlusion in the second half",
        ]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.65, "key_frame_hint": 5.15, "confidence": 0.90},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.65, "time_end": 6.65, "key_frame_hint": 6.15, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 7.45, "key_frame_hint": 7.15, "confidence": 0.80},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.45, "time_end": 8.15, "key_frame_hint": 7.75, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.15, "time_end": 9.25, "key_frame_hint": 8.55, "confidence": 0.70},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.15, "A_air_sec": 7.75, "L_landing_sec": 8.55}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0032", "timestamp": 8.838, "motion_score": 0.0205},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_coherent_tal_late_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [7.4, 7.775, 7.963])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_occluded_timestamp_before_main_motion_cluster_uses_motion_cluster_fallback(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["远距离拍摄，细节有限", "有旁人滑过造成短暂遮挡"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.95, "key_frame_hint": 5.45, "confidence": 0.85},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.95, "time_end": 6.45, "key_frame_hint": 6.15, "confidence": 0.9},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.85, "key_frame_hint": 6.65, "confidence": 0.85},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.85, "time_end": 7.35, "key_frame_hint": 7.05, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.35, "time_end": 7.65, "key_frame_hint": 7.45, "confidence": 0.9},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.65, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.85},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.6, "A_air_sec": 7.05, "L_landing_sec": 7.4}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_coherent_tal_early_main_motion_cluster_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [7.4, 7.775, 7.963])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_low_resolution_timestamp_landing_gets_refinement_phase_tolerance(self) -> None:
        payload = _video_payload(0.85)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["video_duration_short", "low_resolution"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.45, "key_frame_hint": 5.45, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.45, "time_end": 7.15, "key_frame_hint": 6.85, "confidence": 0.9},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.15, "time_end": 7.65, "key_frame_hint": 7.45, "confidence": 0.9},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.65, "time_end": 8.15, "key_frame_hint": 7.85, "confidence": 0.9},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.15, "time_end": 8.45, "key_frame_hint": 8.25, "confidence": 0.9},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.45, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.9},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.45, "A_air_sec": 7.85, "L_landing_sec": 8.25}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            None,
            {
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        landing = next(item for item in plan["selected"] if item["phase_code"] == "landing")
        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual(landing["timestamp"], 8.25)
        self.assertEqual(landing["max_refinement_delta_sec"], 0.30)
        self.assertEqual(landing["refinement_window_seconds"], 0.30)
        self.assertEqual(landing["phase_time_start_refinement_tolerance_sec"], 0.22)
        self.assertEqual(landing["phase_time_end_refinement_tolerance_sec"], 0.22)
        self.assertIn("video_temporal_resolver_landing_refinement_phase_tolerance", plan["quality_flags"])

    def test_quality_retry_takeoff_gets_refinement_delta_expansion(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["video_temporal_quality_retry"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.5, "key_frame_hint": 5.85, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.5, "time_end": 7.1, "key_frame_hint": 6.75, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.1, "time_end": 7.4, "key_frame_hint": 7.2, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.4, "time_end": 7.7, "key_frame_hint": 7.55, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.7, "time_end": 8.0, "key_frame_hint": 7.8, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.0, "time_end": 9.25, "key_frame_hint": 8.45, "confidence": 0.9},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.2, "A_air_sec": 7.55, "L_landing_sec": 7.8}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            None,
            {"selected": [{"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265}], "scores": []},
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        takeoff = next(item for item in plan["selected"] if item["phase_code"] == "takeoff")
        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual(takeoff["timestamp"], 7.2)
        self.assertEqual(takeoff["max_refinement_delta_sec"], 0.20)
        self.assertIn("video_temporal_resolver_takeoff_refinement_delta_expanded", plan["quality_flags"])

    def test_quality_retry_late_landing_after_motion_tail_rejects_core_frames(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["video_temporal_not_high_confidence", "video_temporal_quality_retry"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.65, "key_frame_hint": 5.15, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.65, "time_end": 6.65, "key_frame_hint": 6.15, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 7.45, "key_frame_hint": 7.15, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.45, "time_end": 8.15, "key_frame_hint": 7.75, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.15, "time_end": 9.25, "key_frame_hint": 8.55, "confidence": 0.7},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.15, "A_air_sec": 7.75, "L_landing_sec": 8.55}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            None,
            {
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                    {"frame_id": "frame_0032", "timestamp": 8.838, "motion_score": 0.0205},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertIn("video_temporal_resolver_coherent_tal_retry_tail_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_quality_retry_timestamp_landing_gets_refinement_phase_tolerance(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["video_temporal_quality_retry"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.25, "key_frame_hint": 5.85, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.25, "time_end": 6.95, "key_frame_hint": 6.65, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.95, "time_end": 7.45, "key_frame_hint": 7.15, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.45, "time_end": 7.95, "key_frame_hint": 7.65, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.95, "time_end": 8.45, "key_frame_hint": 8.15, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.45, "time_end": 9.25, "key_frame_hint": 8.85, "confidence": 0.9},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.15, "A_air_sec": 7.65, "L_landing_sec": 8.15}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            None,
            {
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        landing = next(item for item in plan["selected"] if item["phase_code"] == "landing")
        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual(landing["timestamp"], 8.15)
        self.assertEqual(landing["max_refinement_delta_sec"], 0.30)
        self.assertEqual(landing["refinement_window_seconds"], 0.30)
        self.assertEqual(landing["phase_time_start_refinement_tolerance_sec"], 0.22)
        self.assertEqual(landing["phase_time_end_refinement_tolerance_sec"], 0.22)
        self.assertIn("video_temporal_resolver_landing_refinement_phase_tolerance", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_early_compressed_occluded_timestamp_rejects_core_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_high_confidence_early_compressed_occluded_timestamp_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_coherent_tal_early_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_retry_early_compressed_occluded_timestamp_rejects_core_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_high_confidence_retry_early_compressed_occluded_timestamp_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_coherent_tal_early_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_latest_retry_early_main_motion_cluster_rejects_core_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_latest_retry_early_main_motion_cluster_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_early_main_motion_cluster_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_latest_retry_early_main_motion_cluster_uses_motion_cluster_fallback_when_skeleton_partial(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_latest_retry_early_main_motion_cluster_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_low_confidence", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [7.4, 7.775, 7.963])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_motion_cluster_fallback_does_not_trigger_without_skeleton_support(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_latest_retry_early_main_motion_cluster_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertNotIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_motion_cluster_fallback_uses_apex_landing_support_when_takeoff_is_weak(self) -> None:
        payload = _video_payload(0.70)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["brief occlusion", "video_temporal_not_high_confidence"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.65, "key_frame_hint": 6.15, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 7.05, "key_frame_hint": 6.85, "confidence": 0.85},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.05, "time_end": 7.35, "key_frame_hint": 7.2, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.35, "time_end": 7.55, "key_frame_hint": 7.45, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.55, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.75},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.95, "A_air_sec": 7.2, "L_landing_sec": 7.45}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )

        plan = resolve_semantic_keyframes(
            video,
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0008", "timestamp": 5.463, "confidence": 0.436},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0027", "timestamp": 7.963, "confidence": 0.713},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:3]], [7.4, 7.775, 7.963])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_uncertain_timestamp_early_main_motion_cluster_rejects_core_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_uncertain_timestamp_early_main_motion_cluster_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_early_main_motion_cluster_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_high_confidence_late_timestamp_rejects_when_skeleton_timeline_is_much_earlier(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_high_confidence_late_timestamp_with_early_skeleton_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0008", "timestamp": 5.463, "confidence": 0.651},
                    "A": {"frame_id": "frame_0016", "timestamp": 6.4, "confidence": 0.628},
                    "L": {"frame_id": None, "timestamp": None, "confidence": 0.0},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertIn("video_temporal_resolver_coherent_tal_skeleton_timeline_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_light_occlusion_glide_out_motion_does_not_reject_coherent_tal(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_light_occlusion_early_tal_with_glide_out_motion_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0017", "timestamp": 6.588, "motion_score": 0.0548},
                    {"frame_id": "frame_0021", "timestamp": 7.025, "motion_score": 0.042},
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_severe_occlusion_glide_out_motion_still_rejects_coherent_tal(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_light_occlusion_early_tal_with_glide_out_motion_video(["关键动作被严重遮挡", "video_temporal_fallback_recommended"]),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertIn("video_temporal_resolver_coherent_tal_later_motion_conflict", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertFalse(semantic_keyframes_are_reliable(plan))

    def test_timestamp_recommended_glide_out_motion_does_not_reject_visible_core_tal(self) -> None:
        payload = _video_payload(0.60)
        payload["fallback_recommendation"] = "use_video_timestamps"
        payload["quality_flags"] = ["video_temporal_not_high_confidence", "video_temporal_phase_4_low_confidence"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 5.65, "key_frame_hint": 5.15, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 5.65, "time_end": 6.05, "key_frame_hint": 5.95, "confidence": 0.8},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.05, "time_end": 6.35, "key_frame_hint": 6.15, "confidence": 0.7},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.35, "time_end": 6.85, "key_frame_hint": 6.55, "confidence": 0.6},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 6.85, "time_end": 7.15, "key_frame_hint": 6.95, "confidence": 0.5, "valid": False},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.15, "time_end": 7.65, "key_frame_hint": 7.45, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.15, "A_air_sec": 6.55, "L_landing_sec": 6.95}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "selected": [
                {"frame_id": "frame_0014", "timestamp": 6.15, "motion_score": 0.0392},
                {"frame_id": "frame_0017", "timestamp": 6.588, "motion_score": 0.0548},
                {"frame_id": "frame_0021", "timestamp": 7.025, "motion_score": 0.042},
                {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
            ],
            "scores": [],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_legacy_raw_excerpt_recovers_phase_hints_and_timestamp_offset(self) -> None:
        raw_excerpt = (
            '{\n'
            '  "schema_version": "video_temporal_v1",\n'
            '  "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.75},\n'
            '  "phase_segments": [\n'
            '    {"phase_code": "approach", "time_start": 0.0, "time_end": 1.8, "key_frame_hint": 0.9, "confidence": 0.85},\n'
            '    {"phase_code": "preparation", "time_start": 1.8, "time_end": 2.1, "key_frame_hint": 2.0, "confidence": 0.8},\n'
            '    {"phase_code": "takeoff", "time_start": 2.1, "time_end": 2.4, "key_frame_hint": 2.3, "confidence": 0.7},\n'
            '    {"phase_code": "air", "time_start": 2.4, "time_end": 2.8, "key_frame_hint": 2.6, "confidence": 0.65},\n'
            '    {"phase_code": "landing", "time_start": 2.8, "time_end": 3.1, "key_frame_hint": 2.9, "confidence": 0.7},\n'
            '    {"phase_code": "glide_out", "time_start": 3.1, "time_end": 4.6, "key_frame_hint": 3.8, "confidence": 0.8}\n'
            '  ],\n'
            '  "key_moments"'
        )
        legacy_video = {
            "schema_version": "video_temporal_v1",
            "provider": "mimo",
            "model": "mimo-v2.5",
            "valid": False,
            "phase_segments": [],
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "confidence": 0.75,
            "fallback_recommendation": "use_sampled_frames",
            "quality_flags": ["video_temporal_missing_phase_segments"],
            "validation": {"valid": False, "errors": ["video_temporal_missing_phase_segments"], "warnings": []},
            "raw_response_excerpt": raw_excerpt,
            "raw_response_truncated": True,
            "timestamp_offset_sec": 4.65,
        }

        plan = resolve_semantic_keyframes(
            legacy_video,
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_recovered_from_raw_response_excerpt", plan["quality_flags"])
        self.assertIn("video_temporal_recovered_key_moments_from_phase_hints", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"][:3]], ["takeoff", "air", "landing"])
        self.assertEqual([item["timestamp"] for item in plan["selected"][:2]], [6.95, 7.25])
        self.assertGreaterEqual(plan["selected"][2]["timestamp"], 7.45)
        self.assertLessEqual(plan["selected"][2]["timestamp"], 7.75)
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_moderate_jump_tal_override_rejects_out_of_order_key_moments(self) -> None:
        video = _validated_moderate_fallback_video(0.60)
        video["key_moments"] = {"T_takeoff_sec": 2.0, "A_air_sec": 1.6, "L_landing_sec": 1.2}
        plan = resolve_semantic_keyframes(
            video,
            None,
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertEqual(plan["selected"], [])
        self.assertNotIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])

    def test_moderate_jump_tal_override_keeps_low_confidence_fallback(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_moderate_fallback_video(0.54),
            None,
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_low_video_confidence", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])

    def test_quality_retry_low_confidence_coherent_tal_can_recover_semantic_frames(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_low_confidence_quality_retry_video(),
            {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            },
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0021", "timestamp": 7.025, "motion_score": 0.042},
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_moderate_confidence_tal_used", plan["quality_flags"])
        self.assertNotIn("video_temporal_resolver_low_video_confidence", plan["quality_flags"])
        self.assertTrue(semantic_keyframes_are_reliable(plan))
        self.assertEqual(
            [(item["phase_code"], item["timestamp"]) for item in plan["selected"][:3]],
            [("takeoff", 6.75), ("air", 7.05), ("landing", 7.35)],
        )

    def test_low_confidence_falls_back_to_skeleton_candidates(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.42),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_low_video_confidence", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.3, 1.55, 1.95])
        self.assertEqual(plan["selected"][0]["selection_reason"], "skeleton_fallback_motion_peak")

    def test_low_confidence_skeleton_fallback_rejects_weak_candidates(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.52},
                "A": {"frame_id": "frame_0004", "timestamp": 1.55, "confidence": 0.79},
                "L": {"frame_id": "frame_0005", "timestamp": 1.95, "confidence": 0.34},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.42),
            skeleton,
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["air"])
        self.assertIn("video_temporal_resolver_skeleton_t_below_anchor_confidence", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_skeleton_l_below_anchor_confidence", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_partial_skeleton_fallback", plan["quality_flags"])

    def test_no_motion_score_uses_key_frame_hint_when_skeleton_missing(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            None,
            None,
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "video_ai_refined")
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.2, 1.6, 2.0])
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_key_moment")
        self.assertEqual(plan["selected"][0]["phase_time_start"], 1.0)
        self.assertEqual(plan["selected"][0]["phase_time_end"], 1.4)

    def test_high_confidence_takeoff_preserves_key_moment_when_no_near_motion_peak(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_latest_high_confidence_fallback_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "scores": [0.02] * 30,
                "selected": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        takeoff = [item for item in plan["selected"] if item["phase_code"] == "takeoff"][0]
        landing = [item for item in plan["selected"] if item["phase_code"] == "landing"][0]
        self.assertEqual(takeoff["timestamp"], 6.95)
        self.assertEqual(takeoff["selection_reason"], "video_phase_range_key_moment")
        self.assertEqual(landing["timestamp"], 7.65)
        self.assertEqual(landing["selection_reason"], "video_phase_range_key_moment")

    def test_jump_missing_preparation_phase_is_inferred_before_takeoff(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_missing_preparation_manual_review_video(),
            None,
            {
                "frame_rate": 16,
                "window_start": 4.65,
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                    {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                    {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                    {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                    {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                ],
                "scores": [],
            },
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_inferred_preparation_phase", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["takeoff", "air", "landing", "preparation", "glide_out", "approach"])
        preparation = [item for item in plan["selected"] if item["phase_code"] == "preparation"][0]
        self.assertEqual(preparation["timestamp"], 6.3)
        self.assertEqual(preparation["selection_reason"], "inferred_preparation_before_takeoff")
        self.assertEqual(preparation["phase_time_start"], 5.95)
        self.assertEqual(preparation["phase_time_end"], 6.65)
        self.assertEqual(len(plan["selected"]), 6)
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_jump_tail_glide_out_small_duration_overshoot_is_clamped_and_kept(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_sampled_frames"
        payload["quality_flags"] = ["video_temporal_fallback_recommended"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 3.15, "time_end": 5.35, "key_frame_hint": 4.65, "confidence": 0.9},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 5.35, "time_end": 5.95, "key_frame_hint": 5.65, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 5.95, "time_end": 6.55, "key_frame_hint": 6.25, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 6.55, "time_end": 6.95, "key_frame_hint": 6.65, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 6.95, "time_end": 7.75, "key_frame_hint": 7.25, "confidence": 0.85},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 5.65, "A_air_sec": 6.25, "L_landing_sec": 6.65}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=7.735,
        )

        plan = resolve_semantic_keyframes(
            video,
            None,
            {
                "frame_rate": 16,
                "window_start": 3.15,
                "selected": [
                    {"frame_id": "frame_0010", "timestamp": 5.588, "motion_score": 0.22},
                    {"frame_id": "frame_0016", "timestamp": 6.775, "motion_score": 0.21},
                ],
                "scores": [],
            },
            video_duration_sec=7.735,
            analysis_profile="jump",
        )

        self.assertIn("video_temporal_phase_4_end_clamped_to_duration", video["quality_flags"])
        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_inferred_preparation_phase", plan["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["takeoff", "air", "landing", "preparation", "glide_out", "approach"])
        glide_out = [item for item in plan["selected"] if item["phase_code"] == "glide_out"][0]
        self.assertEqual(glide_out["timestamp"], 7.25)
        self.assertEqual(glide_out["phase_time_end"], 7.735)
        self.assertEqual(len(plan["selected"]), 6)
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_legacy_saved_tail_overshoot_validation_error_is_rechecked(self) -> None:
        payload = _video_payload(0.80)
        payload["fallback_recommendation"] = "use_sampled_frames"
        payload["quality_flags"] = ["video_temporal_fallback_recommended", "video_temporal_phase_4_invalid_time_range"]
        payload["phase_segments"] = [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 3.15, "time_end": 5.35, "key_frame_hint": 4.65, "confidence": 0.9, "valid": True},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 5.35, "time_end": 5.95, "key_frame_hint": 5.65, "confidence": 0.8, "valid": True},
            {"phase_code": "air", "phase_label": "air", "time_start": 5.95, "time_end": 6.55, "key_frame_hint": 6.25, "confidence": 0.75, "valid": True},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 6.55, "time_end": 6.95, "key_frame_hint": 6.65, "confidence": 0.8, "valid": True},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 6.95, "time_end": 7.75, "key_frame_hint": 7.25, "confidence": 0.85, "valid": False},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 5.65, "A_air_sec": 6.25, "L_landing_sec": 6.65}
        payload["valid"] = False
        payload["validation"] = {
            "valid": False,
            "errors": ["video_temporal_phase_4_invalid_time_range"],
            "warnings": [],
            "duration_sec": 7.735,
        }
        video = normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5")

        plan = resolve_semantic_keyframes(
            video,
            None,
            {
                "frame_rate": 16,
                "window_start": 3.15,
                "selected": [],
                "scores": [],
            },
            video_duration_sec=7.735,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", plan["quality_flags"])
        self.assertNotIn("video_temporal_phase_4_invalid_time_range", plan["video_ai"]["quality_flags"])
        self.assertIn("video_temporal_phase_4_end_clamped_to_duration", plan["video_ai"]["quality_flags"])
        self.assertEqual([item["phase_code"] for item in plan["selected"]], ["takeoff", "air", "landing", "preparation", "glide_out", "approach"])
        glide_out = [item for item in plan["selected"] if item["phase_code"] == "glide_out"][0]
        self.assertEqual(glide_out["phase_time_end"], 7.735)
        self.assertTrue(semantic_keyframes_are_reliable(plan))

    def test_coherent_tal_preserves_key_moments_over_full_frame_motion_peaks(self) -> None:
        payload = _video_payload(0.75)
        payload["phase_segments"] = [
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.75, "time_end": 7.15, "key_frame_hint": 6.95, "confidence": 0.75},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.15, "time_end": 7.55, "key_frame_hint": 7.35, "confidence": 0.7},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.55, "time_end": 7.95, "key_frame_hint": 7.75, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 6.95, "A_air_sec": 7.35, "L_landing_sec": 7.75}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.01] * 34 + [0.9] + [0.01] * 30,
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 6.775, "motion_score": 0.9},
                {"frame_id": "frame_0002", "timestamp": 7.713, "motion_score": 0.95},
            ],
        }

        plan = resolve_semantic_keyframes(
            video,
            None,
            motion_scores,
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        core = {item["phase_code"]: item for item in plan["selected"] if item["phase_code"] in {"takeoff", "air", "landing"}}
        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_coherent_tal_used", plan["quality_flags"])
        self.assertEqual(core["takeoff"]["timestamp"], 6.95)
        self.assertEqual(core["landing"]["timestamp"], 7.75)
        self.assertEqual(core["takeoff"]["selection_reason"], "video_phase_range_key_moment")
        self.assertEqual(core["landing"]["selection_reason"], "video_phase_range_key_moment")

    def test_occlusion_risk_allows_coherent_skeleton_tal_to_correct_phase_edge_drift(self) -> None:
        payload = _video_payload(0.85)
        payload["quality_flags"] = ["有其他人短暂遮挡主滑行者"]
        payload["phase_segments"] = [
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.15, "time_end": 7.45, "key_frame_hint": 7.35, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 7.45, "time_end": 7.75, "key_frame_hint": 7.65, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.75, "time_end": 8.05, "key_frame_hint": 7.95, "confidence": 0.8},
        ]
        payload["key_moments"] = {"T_takeoff_sec": 7.35, "A_air_sec": 7.65, "L_landing_sec": 7.95}
        video = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"),
            duration_sec=9.568,
        )
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0001", "timestamp": 6.95, "confidence": 0.82},
                "A": {"frame_id": "frame_0002", "timestamp": 7.35, "confidence": 0.8},
                "L": {"frame_id": "frame_0003", "timestamp": 7.65, "confidence": 0.83},
            }
        }

        plan = resolve_semantic_keyframes(
            video,
            skeleton,
            {"selected": [], "scores": []},
            video_duration_sec=9.568,
            analysis_profile="jump",
        )

        core = {item["phase_code"]: item for item in plan["selected"] if item["phase_code"] in {"takeoff", "air", "landing"}}
        self.assertEqual(core["takeoff"]["timestamp"], 6.95)
        self.assertEqual(core["air"]["timestamp"], 7.35)
        self.assertEqual(core["landing"]["timestamp"], 7.65)
        self.assertEqual(core["takeoff"]["selection_reason"], "video_phase_range_skeleton_takeoff_occlusion_anchor")
        self.assertIn("video_temporal_resolver_occlusion_skeleton_tal_available", plan["quality_flags"])
        self.assertIn("video_temporal_resolver_skeleton_occlusion_anchor_used", plan["quality_flags"])

    def test_skeleton_takeoff_snaps_to_full_motion_score_peak(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.81},
                "A": {"frame_id": "frame_0005", "timestamp": 1.5, "confidence": 0.79},
                "L": {"frame_id": "frame_0009", "timestamp": 1.9, "confidence": 0.82},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_skeleton_takeoff_motion_peak")

    def test_skeleton_takeoff_outside_motion_tolerance_preserves_anchor(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.0, "confidence": 0.81},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["selected"][0]["timestamp"], 1.0)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_skeleton_takeoff_anchor")

    def test_low_skeleton_confidence_falls_through_to_motion_peak_without_coherent_jump_override(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0002", "timestamp": 1.2, "confidence": 0.58},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.68),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile=None,
        )

        self.assertEqual(plan["selected"][0]["timestamp"], 1.3)
        self.assertEqual(plan["selected"][0]["selection_reason"], "video_phase_range_motion_peak")

    def test_apex_is_not_pulled_to_motion_peak(self) -> None:
        skeleton = {
            "key_frame_candidates": {
                "A": {"frame_id": "frame_0005", "timestamp": 1.5, "confidence": 0.81},
            }
        }
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            skeleton,
            _motion_series(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        apex = [item for item in plan["selected"] if item["phase_code"] == "air"][0]
        self.assertEqual(apex["timestamp"], 1.5)
        self.assertEqual(apex["selection_reason"], "video_phase_range_skeleton_apex")

    def test_tal_out_of_order_switches_to_blended_and_flags(self) -> None:
        payload = _video_payload(0.88)
        payload["key_moments"] = {"T_takeoff_sec": 2.0, "A_air_sec": 1.6, "L_landing_sec": 1.2}
        validated = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus"),
            duration_sec=3.0,
        )

        plan = resolve_semantic_keyframes(
            validated,
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "blended")
        self.assertIn("video_temporal_resolver_tal_order_blended", plan["quality_flags"])
        self.assertTrue(plan["selected"])

    def test_out_of_bounds_video_interval_falls_back_per_phase(self) -> None:
        payload = _video_payload(0.86)
        payload["phase_segments"] = [
            {"phase_code": "takeoff", "phase_label": "起跳", "time_start": 3.5, "time_end": 4.0, "key_frame_hint": 3.6, "confidence": 0.82}
        ]
        validated = validate_video_temporal_payload(
            normalize_video_temporal_payload(payload, "qwen", "qwen3.6-plus"),
            duration_sec=3.0,
        )

        plan = resolve_semantic_keyframes(
            validated,
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
        )

        self.assertEqual(plan["source"], "skeleton_fallback")
        self.assertIn("video_temporal_resolver_phase_takeoff_fallback", plan["quality_flags"])
        self.assertEqual([item["timestamp"] for item in plan["selected"]], [1.3, 1.55, 1.95])

    def test_plan_is_json_serializable_and_respects_frame_budget(self) -> None:
        plan = resolve_semantic_keyframes(
            _validated_video(0.86),
            _skeleton(),
            _motion_scores(),
            video_duration_sec=3.0,
            analysis_profile="jump",
            max_frames=2,
        )

        json.dumps(plan, ensure_ascii=False)
        self.assertEqual(len(plan["selected"]), 2)


if __name__ == "__main__":
    unittest.main()
