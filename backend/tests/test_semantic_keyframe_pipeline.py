from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.semantic_keyframe_pipeline import (
    SemanticKeyframePipelineResult,
    _apply_unreliable_semantic_selected_fallback,
    _candidate_repair_timestamps,
    _maybe_reanchor_late_phase_range_tal,
    _motion_aligned_candidate_fallback_selected,
    _phase_range_motion_fallback_jump_partial_can_be_promoted,
    _repair_candidate_quality_score,
    _retry_tail_motion_aligned_jump_partial_promotion_support,
    _semantic_motion_cluster_conflict_flags,
    _video_temporal_retry_reason_flags,
    _retry_replacement_rejection_flags,
    _semantic_candidate_tal_conflict_flags,
    _semantic_result_quality_score,
    validate_semantic_keyframes_against_current_evidence,
    resolve_semantic_keyframe_pipeline,
    run_semantic_keyframe_pipeline,
    retry_video_temporal_if_needed,
)
from app.services.biomechanics import sync_key_frames_from_resolved_keyframes
from app.services.video import VideoSamplingMetadata
from app.services.video_temporal import (
    normalize_video_temporal_payload,
    resolve_semantic_keyframes,
    semantic_keyframes_are_reliable,
    validate_video_temporal_payload,
)


def _validated_coherent_fallback_jump_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "jump_type": "Toe Loop", "confidence": 0.85},
        "phase_segments": [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.25, "key_frame_hint": 5.45, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.25, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.8, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.25, "key_frame_hint": 7.1, "confidence": 0.8},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.45, "key_frame_hint": 7.35, "confidence": 0.85},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.45, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.9},
        ],
        "key_moments": {"T_takeoff_sec": 6.8, "A_air_sec": 7.1, "L_landing_sec": 7.35},
        "macro_assessment": {},
        "overall_impression": "",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.85,
        "fallback_recommendation": "use_sampled_frames",
        "quality_flags": ["video_temporal_fallback_recommended"],
    }
    return validate_video_temporal_payload(normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"), duration_sec=9.568)


def _validated_late_motion_conflict_jump_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "jump_type": "Toe Loop", "confidence": 0.85},
        "phase_segments": [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 7.15, "key_frame_hint": 6.25, "confidence": 0.85},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 7.15, "time_end": 7.75, "key_frame_hint": 7.45, "confidence": 0.85},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.75, "time_end": 8.05, "key_frame_hint": 7.95, "confidence": 0.8},
            {"phase_code": "air", "phase_label": "air", "time_start": 8.05, "time_end": 8.35, "key_frame_hint": 8.25, "confidence": 0.75},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 8.35, "time_end": 8.55, "key_frame_hint": 8.4, "confidence": 0.8},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 8.55, "time_end": 9.25, "key_frame_hint": 8.75, "confidence": 0.8},
        ],
        "key_moments": {"T_takeoff_sec": 7.95, "A_air_sec": 8.25, "L_landing_sec": 8.4},
        "macro_assessment": {},
        "overall_impression": "",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.85,
        "fallback_recommendation": "use_sampled_frames",
        "quality_flags": ["brief_occlusion", "video_temporal_fallback_recommended"],
    }
    return validate_video_temporal_payload(normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"), duration_sec=9.568)


def _validated_latest_retry_early_main_motion_cluster_video() -> dict[str, object]:
    payload = {
        "schema_version": "video_temporal_v1",
        "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "jump_type": "Toe Loop", "confidence": 0.8},
        "phase_segments": [
            {"phase_code": "approach", "phase_label": "approach", "time_start": 4.65, "time_end": 6.15, "key_frame_hint": 5.45, "confidence": 0.9},
            {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.15, "time_end": 6.65, "key_frame_hint": 6.45, "confidence": 0.9},
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.65, "time_end": 6.95, "key_frame_hint": 6.75, "confidence": 0.85},
            {"phase_code": "air", "phase_label": "air", "time_start": 6.95, "time_end": 7.45, "key_frame_hint": 7.15, "confidence": 0.85},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 7.45, "time_end": 7.85, "key_frame_hint": 7.65, "confidence": 0.85},
            {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 7.85, "time_end": 8.65, "key_frame_hint": 8.15, "confidence": 0.9},
        ],
        "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.65},
        "macro_assessment": {},
        "overall_impression": "",
        "camera_view": "diagonal_front",
        "data_quality_hint": "partial",
        "confidence": 0.8,
        "fallback_recommendation": "use_video_timestamps",
        "quality_flags": ["video_temporal_quality_retry"],
    }
    return validate_video_temporal_payload(normalize_video_temporal_payload(payload, "mimo", "mimo-v2.5"), duration_sec=9.568)


def _glide_out_motion_scores() -> dict[str, object]:
    return {
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


def _visible_person_candidates() -> list[dict[str, object]]:
    return [{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}]


def _foreground_occluded_person_candidates() -> list[dict[str, object]]:
    return [
        {"bbox": {"x": 0.42, "y": 0.18, "width": 0.22, "height": 0.74}, "confidence": 0.9},
        {"bbox": {"x": 0.46, "y": 0.46, "width": 0.03, "height": 0.12}, "confidence": 0.72},
    ]


def _retry_tail_motion_aligned_phase_range_fixture(*, occluded: bool = False) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    video_temporal = {
        "schema_version": "video_temporal_v1",
        "valid": False,
        "confidence": 0.65,
        "fallback_recommendation": "use_video_timestamps",
        "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.65},
        "quality_flags": [
            "video_temporal_quality_retry",
            "video_temporal_not_high_confidence",
            "video_temporal_fallback_recommended",
        ],
        "key_moments": {"T_takeoff_sec": 5.25, "A_air_sec": 5.5, "L_landing_sec": 5.7},
        "phase_segments": [
            {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 5.1, "time_end": 5.35, "confidence": 0.55},
            {"phase_code": "air", "phase_label": "air", "time_start": 5.35, "time_end": 5.62, "confidence": 0.55},
            {"phase_code": "landing", "phase_label": "landing", "time_start": 5.62, "time_end": 5.95, "confidence": 0.55},
        ],
    }
    selected = [
        {
            "frame_id": "semantic_0001",
            "timestamp": 5.25,
            "phase_code": "takeoff",
            "phase_label": "takeoff",
            "key_moment": "T_takeoff_sec",
            "selection_reason": "video_phase_range_key_moment",
            "confidence": 0.55,
            "phase_time_start": 5.1,
            "phase_time_end": 5.35,
        },
        {
            "frame_id": "semantic_0002",
            "timestamp": 5.5,
            "phase_code": "air",
            "phase_label": "air",
            "key_moment": "A_air_sec",
            "selection_reason": "video_phase_range_key_moment",
            "confidence": 0.55,
            "phase_time_start": 5.35,
            "phase_time_end": 5.62,
        },
        {
            "frame_id": "semantic_0003",
            "timestamp": 5.7,
            "phase_code": "landing",
            "phase_label": "landing",
            "key_moment": "L_landing_sec",
            "selection_reason": "video_phase_range_key_moment",
            "confidence": 0.55,
            "phase_time_start": 5.62,
            "phase_time_end": 5.95,
        },
    ]
    if occluded:
        selected[0]["semantic_visibility"] = {"status": "foreground_person_occluded"}
    resolved = {
        "source": "blended",
        "confidence": 0.65,
        "quality_flags": [
            "video_temporal_resolver_coherent_tal_compressed",
            "video_temporal_resolver_coherent_tal_late_motion_conflict",
            "video_temporal_resolver_coherent_tal_retry_tail_motion_conflict",
            "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
            "video_temporal_resolver_video_fallback_recommended",
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            "semantic_keyframes_partial_core_frames_available",
        ],
        "selected": selected,
        "video_ai": video_temporal,
    }
    bio_data = {
        "key_frame_candidates": {
            "quality_flags": [
                "keyframe_candidates_excluded_unreliable_pose_frames",
                "tal_candidate_landing_geometry_weak",
                "tal_candidate_temporal_geometry_unreliable",
                "tal_candidate_apex_landing_gap_unreliable",
            ],
            "T": {
                "frame_id": "frame_0078",
                "timestamp": 4.875,
                "confidence": 0.49,
                "warnings": ["knee_extension_weak", "tal_candidate_temporal_geometry_unreliable"],
            },
            "A": {
                "frame_id": "frame_0079",
                "timestamp": 4.938,
                "confidence": 0.461,
                "warnings": ["apex_local_minimum_not_clear", "tal_candidate_apex_landing_gap_unreliable"],
            },
            "L": {
                "frame_id": "frame_0098",
                "timestamp": 6.125,
                "confidence": 0.361,
                "warnings": ["landing_geometry_weak", "tal_candidate_landing_geometry_weak"],
            },
        }
    }
    motion_scores = {
        "selected": [
            {"frame_id": "frame_0077", "timestamp": 4.812, "motion_score": 0.1153},
            {"frame_id": "frame_0076", "timestamp": 4.75, "motion_score": 0.1138},
            {"frame_id": "frame_0102", "timestamp": 6.375, "motion_score": 0.1045},
            {"frame_id": "frame_0116", "timestamp": 7.25, "motion_score": 0.0973},
            {"frame_id": "frame_0101", "timestamp": 6.312, "motion_score": 0.09},
        ]
    }
    return video_temporal, resolved, bio_data, motion_scores


def _zoomed_visible_person_candidates() -> list[dict[str, object]]:
    return [
        {
            "bbox": {"x": 0.45, "y": 0.42, "width": 0.035, "height": 0.13},
            "confidence": 0.76,
            "source": "yolo_zoomed_content",
        }
    ]


def _fake_extract_precise_frames(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    copied_records = []
    for index, record in enumerate(records, start=1):
        path = output_dir / f"{prefix}_{index:04d}.jpg"
        path.write_bytes(b"frame")
        paths.append(path)
        copied_records.append(dict(record))
    return paths, copied_records


class SemanticKeyframePipelineTests(unittest.IsolatedAsyncioTestCase):
    def _motion_aligned_jump_bio(
        self,
        *,
        flags: list[str],
        times: tuple[float, float, float] = (3.0, 3.167, 3.5),
        confidences: tuple[float, float, float] = (0.46, 0.44, 0.45),
    ) -> dict[str, object]:
        return {
            "key_frame_candidates": {
                "quality_flags": flags,
                "T": {
                    "frame_id": "frame_0018",
                    "timestamp": times[0],
                    "confidence": confidences[0],
                    "warnings": [flag for flag in flags if "takeoff" in flag or "motion_fallback" in flag],
                },
                "A": {
                    "frame_id": "frame_0019",
                    "timestamp": times[1],
                    "confidence": confidences[1],
                    "warnings": [flag for flag in flags if "apex" in flag or "motion_fallback" in flag],
                },
                "L": {
                    "frame_id": "frame_0021",
                    "timestamp": times[2],
                    "confidence": confidences[2],
                    "warnings": [flag for flag in flags if "landing" in flag or "motion_fallback" in flag],
                },
            }
        }

    def test_motion_aligned_candidate_fallback_selects_bounded_low_precision_candidate(self) -> None:
        bio_data = self._motion_aligned_jump_bio(
            flags=[
                "keyframe_candidates_motion_fallback",
                "tal_candidate_motion_fallback_low_precision",
                "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                "tal_candidate_incomplete",
                "tal_order_unresolved",
            ]
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0018", "timestamp": 3.0, "motion_score": 0.18},
                {"frame_id": "frame_0019", "timestamp": 3.167, "motion_score": 0.24},
                {"frame_id": "frame_0020", "timestamp": 3.333, "motion_score": 0.19},
                {"frame_id": "frame_0021", "timestamp": 3.5, "motion_score": 0.22},
            ]
        }

        selected, flags, diagnostics = _motion_aligned_candidate_fallback_selected(
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
            video_duration_sec=4.0,
        )

        self.assertEqual([item["timestamp"] for item in selected], [3.0, 3.167, 3.5])
        self.assertIn("semantic_keyframes_motion_aligned_candidate_fallback_used", flags)
        self.assertIn("semantic_keyframes_motion_aligned_candidate_fallback_low_precision", flags)
        self.assertEqual(diagnostics["decision"], "selected_motion_aligned_candidate_fallback")

    def test_motion_aligned_candidate_fallback_selects_weak_geometry_when_motion_is_exact(self) -> None:
        bio_data = self._motion_aligned_jump_bio(
            flags=[
                "tal_candidate_takeoff_geometry_weak",
                "tal_candidate_landing_geometry_weak",
                "tal_candidate_confidence_low",
            ],
            times=(7.5, 7.833, 8.0),
            confidences=(0.38, 0.36, 0.39),
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0045", "timestamp": 7.5, "motion_score": 0.16},
                {"frame_id": "frame_0046", "timestamp": 7.667, "motion_score": 0.18},
                {"frame_id": "frame_0047", "timestamp": 7.833, "motion_score": 0.25},
                {"frame_id": "frame_0048", "timestamp": 8.0, "motion_score": 0.17},
            ]
        }

        selected, flags, diagnostics = _motion_aligned_candidate_fallback_selected(
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
            video_duration_sec=8.5,
        )

        self.assertEqual([item["timestamp"] for item in selected], [7.5, 7.833, 8.0])
        self.assertIn("semantic_keyframes_motion_aligned_candidate_fallback_weak_candidate", flags)
        self.assertTrue(diagnostics["global_peak_inside_candidate_window"])

    def test_motion_aligned_candidate_fallback_rejects_contaminated_or_cross_segment_candidates(self) -> None:
        for blocking_flag in (
            "tal_candidate_motion_fallback_cross_segment_unreliable",
            "tal_candidate_motion_fallback_foreground_motion_risk",
            "keyframe_candidates_motion_fallback_multiperson_relock_instability_risk",
            "keyframe_candidates_motion_fallback_unreliable_pose_state",
        ):
            with self.subTest(blocking_flag=blocking_flag):
                bio_data = self._motion_aligned_jump_bio(flags=[blocking_flag])
                selected, flags, diagnostics = _motion_aligned_candidate_fallback_selected(
                    bio_data=bio_data,
                    motion_scores={
                        "selected": [
                            {"frame_id": "frame_0018", "timestamp": 3.0, "motion_score": 0.18},
                            {"frame_id": "frame_0019", "timestamp": 3.167, "motion_score": 0.24},
                            {"frame_id": "frame_0021", "timestamp": 3.5, "motion_score": 0.22},
                        ]
                    },
                    analysis_profile="jump",
                    video_duration_sec=4.0,
                )

                self.assertEqual(selected, [])
                self.assertEqual(flags, [])
                self.assertEqual(diagnostics["decision"], "blocked_candidate_quality_flags")

    def test_motion_aligned_candidate_fallback_rejects_candidate_far_from_motion_peak(self) -> None:
        bio_data = self._motion_aligned_jump_bio(
            flags=["tal_candidate_landing_geometry_weak", "tal_candidate_confidence_low"],
            times=(1.833, 2.333, 2.5),
            confidences=(0.35, 0.35, 0.35),
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0009", "timestamp": 1.5, "motion_score": 0.18},
                {"frame_id": "frame_0010", "timestamp": 1.667, "motion_score": 0.21},
                {"frame_id": "frame_0011", "timestamp": 1.833, "motion_score": 0.05},
                {"frame_id": "frame_0012", "timestamp": 3.167, "motion_score": 0.22},
            ]
        }

        selected, flags, diagnostics = _motion_aligned_candidate_fallback_selected(
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
            video_duration_sec=4.0,
        )

        self.assertEqual(selected, [])
        self.assertEqual(flags, [])
        self.assertIn(diagnostics["decision"], {"candidate_key_motion_alignment_rejected", "insufficient_candidate_window_motion_records"})

    def test_motion_aligned_candidate_fallback_rejects_landing_outside_alignment_tolerance(self) -> None:
        bio_data = self._motion_aligned_jump_bio(
            flags=[
                "tal_candidate_takeoff_geometry_weak",
                "tal_candidate_landing_geometry_weak",
                "tal_candidate_confidence_low",
            ],
            times=(7.167, 7.333, 7.5),
            confidences=(0.38, 0.36, 0.39),
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0043", "timestamp": 7.167, "motion_score": 0.16},
                {"frame_id": "frame_0044", "timestamp": 7.333, "motion_score": 0.18},
                {"frame_id": "frame_0045", "timestamp": 7.36, "motion_score": 0.15},
                {"frame_id": "frame_0090", "timestamp": 14.833, "motion_score": 0.20},
            ]
        }

        selected, flags, diagnostics = _motion_aligned_candidate_fallback_selected(
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
            video_duration_sec=15.0,
        )

        self.assertEqual(selected, [])
        self.assertEqual(flags, [])
        self.assertEqual(diagnostics["decision"], "candidate_key_motion_alignment_rejected")

    async def test_quality_retry_rejected_uses_motion_aligned_candidate_fallback(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.42,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": [],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_missing_core_tal"]},
        }
        original_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.42,
            "quality_flags": ["video_temporal_resolver_no_semantic_selection"],
            "selected": [],
            "video_ai": original_video,
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.38,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_missing_core_tal"]},
        }
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes={
                "source": "skeleton_fallback",
                "confidence": 0.38,
                "quality_flags": [
                    "video_temporal_resolver_no_semantic_selection",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                ],
                "selected": [],
            },
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=False,
        )
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=False,
        )
        bio_data = self._motion_aligned_jump_bio(
            flags=[
                "keyframe_candidates_motion_fallback",
                "tal_candidate_motion_fallback_low_precision",
                "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                "tal_candidate_incomplete",
                "tal_order_unresolved",
            ]
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0018", "timestamp": 3.0, "motion_score": 0.18},
                {"frame_id": "frame_0019", "timestamp": 3.167, "motion_score": 0.24},
                {"frame_id": "frame_0020", "timestamp": 3.333, "motion_score": 0.19},
                {"frame_id": "frame_0021", "timestamp": 3.5, "motion_score": 0.22},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=4.0, ai_clip_payload=lambda: {"duration_sec": 4.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        updated = await retry_video_temporal_if_needed(
                            result=result,
                            video_path=root / "source.mp4",
                            work_dir=root,
                            semantic_frames_dir=root / "semantic",
                            sampling_metadata=VideoSamplingMetadata(0.0, 4.0, 0.0, 4.0, 16.0, 30.0, False),
                            action_type="jump",
                            action_subtype=None,
                            motion_scores=motion_scores,
                            analysis_profile="jump",
                            bio_data=bio_data,
                        )

            self.assertIsNot(updated, result)
            self.assertTrue(updated.used_semantic_frames)
            self.assertEqual([path.parent for path in updated.semantic_frames], [root / "semantic", root / "semantic", root / "semantic"])
            self.assertEqual(
                [
                    item["timestamp"]
                    for item in updated.resolved_keyframes["selected"]
                    if item.get("key_moment") in {"T_takeoff_sec", "A_air_sec", "L_landing_sec"}
                ],
                [3.0, 3.167, 3.5],
            )
            self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
            self.assertIn(
                "semantic_keyframes_motion_aligned_candidate_fallback_used",
                updated.resolved_keyframes["quality_flags"],
            )
            self.assertNotIn(
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                updated.resolved_keyframes["quality_flags"],
            )
            self.assertTrue(semantic_keyframes_are_reliable(updated.resolved_keyframes))

    def test_repair_timestamps_use_temporal_neighbors_not_record_order(self) -> None:
        records = [
            {"timestamp": 7.35, "phase_code": "takeoff", "phase_time_start": 7.15, "phase_time_end": 7.45},
            {"timestamp": 7.65, "phase_code": "air", "phase_time_start": 7.45, "phase_time_end": 7.85},
            {"timestamp": 7.95, "phase_code": "landing", "phase_time_start": 7.85, "phase_time_end": 8.15},
            {"timestamp": 6.65, "phase_code": "preparation", "phase_time_start": 6.15, "phase_time_end": 7.15},
            {"timestamp": 8.65, "phase_code": "glide_out", "phase_time_start": 8.15, "phase_time_end": 9.25},
        ]

        candidates = _candidate_repair_timestamps(
            records[2],
            records,
            source_fps=30.0,
            duration_sec=9.568,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0], 7.917)
        self.assertIn(8.017, candidates)

    def test_repair_timestamps_include_pre_refine_search_center(self) -> None:
        records = [
            {"timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 7.35, "phase_time_end": 7.55},
            {"timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.55, "phase_time_end": 7.75},
            {
                "timestamp": 7.803,
                "pre_refine_timestamp": 7.85,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "phase_time_start": 7.75,
                "phase_time_end": 7.95,
            },
        ]

        candidates = _candidate_repair_timestamps(
            records[2],
            records,
            source_fps=30.0,
            duration_sec=9.568,
        )

        self.assertTrue(candidates)
        self.assertIn(7.85, candidates)
        self.assertLess(candidates.index(7.85), candidates.index(7.917))

    def test_repair_timestamps_keep_core_tal_spacing(self) -> None:
        records = [
            {"timestamp": 7.55, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "phase_time_start": 7.45, "phase_time_end": 7.65},
            {"timestamp": 7.85, "phase_code": "air", "key_moment": "A_air_sec", "phase_time_start": 7.65, "phase_time_end": 8.05},
            {"timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec", "phase_time_start": 8.05, "phase_time_end": 8.25},
        ]

        candidates = _candidate_repair_timestamps(
            records[1],
            records,
            source_fps=30.0,
            duration_sec=9.568,
        )

        self.assertTrue(candidates)
        self.assertIn(7.75, candidates)
        self.assertNotIn(8.017, candidates)
        self.assertNotIn(8.05, candidates)

    def test_quality_score_penalizes_core_visibility_repair(self) -> None:
        selected = [
            {"timestamp": 7.55, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            {"timestamp": 7.85, "phase_code": "air", "key_moment": "A_air_sec"},
            {"timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
        ]
        clean = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal={"confidence": 0.85, "quality_flags": []},
            resolved_keyframes={"source": "video_ai_refined", "confidence": 0.85, "quality_flags": [], "selected": selected},
            used_semantic_frames=True,
        )
        repaired = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal={"confidence": 0.85, "quality_flags": []},
            resolved_keyframes={
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    selected[0],
                    {**selected[1], "pre_visibility_repair_timestamp": 7.85, "visibility_repair_timestamp": 7.75},
                    selected[2],
                ],
            },
            used_semantic_frames=True,
        )

        self.assertGreater(_semantic_result_quality_score(clean), _semantic_result_quality_score(repaired))

    async def test_core_foreground_occlusion_repairs_to_nearby_visible_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": []}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.15, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.45, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    repaired_timestamp_ms: int | None = None

                    async def fake_extract(_: Path, output_dir: Path, extract_records: list[dict[str, object]], *, prefix: str = "semantic"):
                        output_dir.mkdir(parents=True, exist_ok=True)
                        if prefix == "semantic":
                            return semantic_paths, [dict(item) for item in extract_records]
                        timestamp = float(extract_records[0]["timestamp"])
                        path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                        path.write_bytes(b"visible")
                        return [path], [{**extract_records[0], "frame_id": "repair_0001"}]

                    def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                        nonlocal repaired_timestamp_ms
                        if frame_path.parent.name.startswith("repair_"):
                            timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                            if timestamp_ms == 7717:
                                repaired_timestamp_ms = timestamp_ms
                                return visible
                            return occluded
                        if frame_path.name == "semantic_0003.jpg":
                            return visible if repaired_timestamp_ms == 7717 else occluded
                        return visible

                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.717)
        self.assertEqual(landing["frame_id"], "semantic_0003")
        self.assertEqual(landing["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertNotIn("semantic_visibility", landing)

    async def test_core_foreground_occlusion_repairs_from_pre_refine_timestamp_when_refined_center_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": []}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.85,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "phase_time_start": 7.75,
                        "phase_time_end": 7.95,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined_records = [
                {**resolved["selected"][0], "pre_refine_timestamp": 7.45, "refinement_method": "local_motion_peak_phase_rejected"},
                {**resolved["selected"][1], "pre_refine_timestamp": 7.65, "refinement_method": "apex_preserved"},
                {
                    **resolved["selected"][2],
                    "timestamp": 7.803,
                    "pre_refine_timestamp": 7.85,
                    "refinement_method": "local_motion_peak",
                    "refinement_delta_sec": -0.047,
                },
            ]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]
            extracted_paths: list[Path] = []
            repaired_semantic_0003 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0003
                parent_name = frame_path.parent.name
                if parent_name.startswith("repair_"):
                    timestamp_ms = int(parent_name.rsplit("_", 1)[1])
                    if timestamp_ms == 7850:
                        repaired_semantic_0003 = True
                        return visible
                    return occluded
                if frame_path.name == "semantic_0003.jpg":
                    if repaired_semantic_0003:
                        return visible
                    return occluded
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined_records, ["semantic_keyframe_refinement_phase_rejected"])),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.85)
        self.assertEqual(landing["pre_visibility_repair_timestamp"], 7.803)
        self.assertEqual(landing["visibility_repair_search_origin"], "pre_refine_timestamp")
        self.assertEqual(landing["visibility_repair_search_center_timestamp"], 7.85)
        self.assertTrue(any("repair_semantic_0003_00007850" in str(path) for path in extracted_paths))

    async def test_late_phase_reanchor_occlusion_rolls_back_to_visible_phase_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": []}
            resolved = {
                "source": "blended",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 3.75,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "phase_time_start": 4.2,
                        "phase_time_end": 4.6,
                        "pre_refine_timestamp": 4.4,
                        "pre_late_phase_reanchor_timestamp": 4.553,
                        "late_phase_range_reanchor": True,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 4.23,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "phase_time_start": 4.6,
                        "phase_time_end": 5.1,
                        "pre_refine_timestamp": 4.8,
                        "pre_late_phase_reanchor_timestamp": 4.8,
                        "late_phase_range_reanchor": True,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.55,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "phase_time_start": 5.1,
                        "phase_time_end": 5.5,
                        "phase_time_start_refinement_tolerance_sec": 0.22,
                        "phase_time_end_refinement_tolerance_sec": 0.22,
                        "pre_refine_timestamp": 5.2,
                        "pre_late_phase_reanchor_timestamp": 4.933,
                        "late_phase_range_reanchor": True,
                    },
                ],
                "video_ai": video_temporal,
            }
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.35, "y": 0.18, "width": 0.35, "height": 0.78}, "confidence": 0.9, "area": 0.273},
                {"bbox": {"x": 0.42, "y": 0.30, "width": 0.06, "height": 0.18}, "confidence": 0.5, "area": 0.0108},
            ]
            rollback_extracts: list[list[float]] = []
            rollback_applied = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                nonlocal rollback_applied
                output_dir.mkdir(parents=True, exist_ok=True)
                if output_dir.name.startswith("late_reanchor_rollback"):
                    rollback_applied = True
                    rollback_extracts.append([float(record["timestamp"]) for record in records])
                    paths = []
                    extracted = []
                    for index, record in enumerate(records, start=1):
                        path = output_dir / f"{prefix}_{index:04d}.jpg"
                        path.write_bytes(b"rollback")
                        paths.append(path)
                        extracted.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                    return paths, extracted
                return semantic_paths, [dict(item) for item in records]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25, **_: object):  # noqa: ARG001
                if frame_path.parent.name.startswith("late_reanchor_rollback"):
                    return visible
                if frame_path.name == "semantic_0001.jpg":
                    if rollback_applied:
                        return visible
                    return occluded
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(resolved["selected"], []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=7.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(
            [item["timestamp"] for item in result.resolved_keyframes["selected"][:3]],
            [4.553, 4.8, 4.933],
        )
        self.assertIn([4.553, 4.8, 4.933], rollback_extracts)
        self.assertIn("semantic_keyframes_late_phase_reanchor_occlusion_rolled_back", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        takeoff = result.resolved_keyframes["selected"][0]
        self.assertEqual(takeoff["visibility_repair_method"], "late_phase_range_reanchor_rollback_visible_frame")
        self.assertEqual(takeoff["visibility_repair_search_origin"], "pre_late_phase_reanchor_timestamp")
        self.assertNotIn("semantic_visibility", takeoff)

    async def test_refined_landing_visibility_repair_stays_near_motion_peak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.75, "quality_flags": ["video_temporal_fallback_recommended"]}
            resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_landing_refinement_phase_tolerance"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.95, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.45,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "phase_time_start": 7.35,
                        "phase_time_end": 7.55,
                        "phase_time_end_refinement_tolerance_sec": 0.22,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined_records = [
                {**resolved["selected"][0], "timestamp": 6.903, "pre_refine_timestamp": 6.95, "refinement_method": "local_motion_peak"},
                {**resolved["selected"][1], "pre_refine_timestamp": 7.15, "refinement_method": "apex_preserved"},
                {
                    **resolved["selected"][2],
                    "timestamp": 7.717,
                    "pre_refine_timestamp": 7.45,
                    "refinement_method": "local_motion_peak",
                    "refinement_delta_sec": 0.267,
                    "refinement_phase_end_tolerance_used": True,
                },
            ]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]
            extracted_paths: list[Path] = []
            repaired_semantic_0003 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0003
                parent_name = frame_path.parent.name
                if parent_name.startswith("repair_"):
                    timestamp_ms = int(parent_name.rsplit("_", 1)[1])
                    if timestamp_ms == 7750:
                        repaired_semantic_0003 = True
                        return visible
                    if timestamp_ms == 7450:
                        return visible
                    return occluded
                if frame_path.name == "semantic_0003.jpg":
                    return visible if repaired_semantic_0003 else occluded
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined_records, ["semantic_keyframe_refinement_phase_end_tolerance_used"])),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.75)
        self.assertEqual(landing["pre_visibility_repair_timestamp"], 7.717)
        self.assertEqual(landing["visibility_repair_search_origin"], "timestamp")
        self.assertFalse(any("repair_semantic_0003_00007450" in str(path) for path in extracted_paths))

    def test_landing_repair_score_prefers_nearby_candidate_when_quality_is_close(self) -> None:
        context_area = 0.00833728
        nearer = [
            {
                "bbox": {"x": 0.3944, "y": 0.2766, "width": 0.0521, "height": 0.1866},
                "confidence": 0.747,
            }
        ]
        later = [
            {
                "bbox": {"x": 0.3947, "y": 0.2667, "width": 0.0448, "height": 0.1861},
                "confidence": 0.806,
            }
        ]

        nearer_score = _repair_candidate_quality_score(
            nearer,
            candidate_timestamp=8.05,
            original_timestamp=7.95,
            target_context_area=context_area,
            semantic_key="L",
        )
        later_score = _repair_candidate_quality_score(
            later,
            candidate_timestamp=8.117,
            original_timestamp=7.95,
            target_context_area=context_area,
            semantic_key="L",
        )

        self.assertIsNotNone(nearer_score)
        self.assertIsNotNone(later_score)
        self.assertGreater(nearer_score, later_score)

    async def test_motion_cluster_landing_visibility_repair_respects_explicit_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.75, "quality_flags": ["foreground_occlusion"]}
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_motion_cluster_fallback_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.4, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.66},
                    {"frame_id": "semantic_0002", "timestamp": 7.775, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.66},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.963,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.66,
                        "phase_time_start": 7.795,
                        "phase_time_end": 8.145,
                        "visibility_repair_max_delta_sec": 0.12,
                        "visibility_repair_preserve_timestamp": True,
                    },
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]
            attempted_repair_ms: list[int] = []
            repaired_semantic_0003 = False

            async def fake_extract(_: Path, output_dir: Path, extract_records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in extract_records]
                timestamp = float(extract_records[0]["timestamp"])
                timestamp_ms = int(round(timestamp * 1000))
                attempted_repair_ms.append(timestamp_ms)
                path = output_dir / f"{prefix}_{timestamp_ms:08d}.jpg"
                path.write_bytes(b"repair")
                return [path], [{**extract_records[0], "frame_id": "repair_0001"}]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0003
                parent_name = frame_path.parent.name
                if parent_name.startswith("repair_"):
                    timestamp_ms = int(parent_name.rsplit("_", 1)[1])
                    if 7995 <= timestamp_ms <= 7997:
                        repaired_semantic_0003 = True
                        return visible
                    if timestamp_ms == 8063:
                        return [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.18}, "confidence": 0.95, "area": 0.0144}]
                    return occluded
                if frame_path.name == "semantic_0003.jpg":
                    return visible if repaired_semantic_0003 else occluded
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["timestamp"], 7.963)
        self.assertEqual(landing["pre_visibility_repair_timestamp"], 7.963)
        self.assertTrue(landing["visibility_repair_timestamp_preserved"])
        self.assertEqual(landing["visibility_repair_frame_timestamp"], 7.996)
        self.assertIn(7996, attempted_repair_ms)

    async def test_single_large_foreground_person_repairs_when_target_context_is_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.70, "quality_flags": ["foreground occlusion"]}
            resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 7.85,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "phase_time_start": 7.65,
                        "phase_time_end": 8.05,
                    },
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            single_large_foreground = [{"bbox": {"x": 0.34, "y": 0.20, "width": 0.24, "height": 0.63}, "confidence": 0.81, "area": 0.1512}]
            extracted_paths: list[Path] = []
            repaired_semantic_0002 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0002
                if frame_path.parent.name.startswith("repair_"):
                    timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                    if timestamp_ms == 7817:
                        repaired_semantic_0002 = True
                        return visible
                    return single_large_foreground
                if frame_path.name == "semantic_0002.jpg":
                    if repaired_semantic_0002:
                        return visible
                    return single_large_foreground
                return visible

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        apex = result.resolved_keyframes["selected"][1]
        self.assertEqual(apex["timestamp"], 7.817)
        self.assertEqual(apex["pre_visibility_repair_timestamp"], 7.85)
        self.assertEqual(apex["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertTrue(any("repair_semantic_0002_00007817" in str(path) for path in extracted_paths))

    async def test_foreground_occlusion_repair_keeps_apex_away_from_landing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": ["foreground occlusion"]}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 7.55,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "phase_time_start": 7.45,
                        "phase_time_end": 7.65,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 7.85,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "phase_time_start": 7.65,
                        "phase_time_end": 8.05,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 8.15,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "phase_time_start": 8.05,
                        "phase_time_end": 8.25,
                    },
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible_context = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            original_occluded = [{"bbox": {"x": 0.34, "y": 0.20, "width": 0.24, "height": 0.63}, "confidence": 0.81, "area": 0.1512}]
            earlier_visible = [
                {"bbox": {"x": 0.42, "y": 0.29, "width": 0.07, "height": 0.17}, "confidence": 0.73, "area": 0.0119},
                {"bbox": {"x": 0.55, "y": 0.06, "width": 0.11, "height": 0.91}, "confidence": 0.47, "area": 0.1001},
            ]
            clearer_but_too_close_to_landing = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.18}, "confidence": 0.91, "area": 0.0144}]
            extracted_paths: list[Path] = []
            repaired_semantic_0002 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0002
                if frame_path.parent.name.startswith("repair_"):
                    timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                    if timestamp_ms == 7750:
                        repaired_semantic_0002 = True
                        return earlier_visible
                    if timestamp_ms in {8017, 8050}:
                        return clearer_but_too_close_to_landing
                    return original_occluded
                if frame_path.name == "semantic_0002.jpg":
                    if repaired_semantic_0002:
                        return earlier_visible
                    return original_occluded
                return visible_context

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        apex = result.resolved_keyframes["selected"][1]
        self.assertEqual(apex["timestamp"], 7.75)
        self.assertEqual(apex["pre_visibility_repair_timestamp"], 7.85)
        self.assertEqual(apex["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertTrue(any("repair_semantic_0002_00007750" in str(path) for path in extracted_paths))
        self.assertFalse(any("repair_semantic_0002_00008017" in str(path) for path in extracted_paths))

    async def test_foreground_occlusion_repair_prefers_clearer_target_over_first_visible_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.70, "quality_flags": ["foreground occlusion"]}
            resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.37, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 7.85,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "phase_time_start": 7.50,
                        "phase_time_end": 8.05,
                    },
                    {"frame_id": "semantic_0003", "timestamp": 8.35, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible_context = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            original_occluded = [{"bbox": {"x": 0.34, "y": 0.20, "width": 0.24, "height": 0.63}, "confidence": 0.81, "area": 0.1512}]
            first_visible_but_foreground_heavy = [
                {"bbox": {"x": 0.42, "y": 0.29, "width": 0.07, "height": 0.17}, "confidence": 0.73, "area": 0.0119},
                {"bbox": {"x": 0.55, "y": 0.06, "width": 0.11, "height": 0.91}, "confidence": 0.47, "area": 0.1001},
            ]
            clearer_target = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.08, "height": 0.18}, "confidence": 0.84, "area": 0.0144}]
            extracted_paths: list[Path] = []
            repaired_semantic_0002 = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                if prefix == "semantic":
                    return semantic_paths, [dict(item) for item in records]
                timestamp = float(records[0]["timestamp"])
                path = output_dir / f"{prefix}_{int(timestamp * 1000):08d}.jpg"
                path.write_bytes(b"repair")
                extracted_paths.append(path)
                return [path], [dict(records[0])]

            def fake_candidates(frame_path: Path, min_confidence: float = 0.25):  # noqa: ARG001
                nonlocal repaired_semantic_0002
                if frame_path.parent.name.startswith("repair_"):
                    timestamp_ms = int(frame_path.parent.name.rsplit("_", 1)[1])
                    if timestamp_ms == 7517:
                        repaired_semantic_0002 = True
                        return clearer_target
                    if timestamp_ms == 7817:
                        return first_visible_but_foreground_heavy
                    return original_occluded
                if frame_path.name == "semantic_0002.jpg":
                    if repaired_semantic_0002:
                        return clearer_target
                    return original_occluded
                return visible_context

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertTrue(result.used_semantic_frames)
        apex = result.resolved_keyframes["selected"][1]
        self.assertEqual(apex["timestamp"], 7.517)
        self.assertEqual(apex["pre_visibility_repair_timestamp"], 7.85)
        self.assertEqual(apex["visibility_repair_method"], "nearby_unoccluded_person_frame")
        self.assertGreater(apex["visibility_repair_quality_score"], 0)
        self.assertTrue(any("repair_semantic_0002_00007517" in str(path) for path in extracted_paths))

    async def test_quality_retry_replaces_repaired_visible_result_when_retry_scores_better(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.7 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 7.45, "A_air_sec": 7.85, "L_landing_sec": 8.15},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.55},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.75, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.75)
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", retry_context["retry_reason_flags"])

    async def test_quality_retry_keeps_repaired_visible_result_when_retry_scores_worse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 7.1 + index * 0.2, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 7.45, "A_air_sec": 7.85, "L_landing_sec": 8.15},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.60,
                "key_moments": {"T_takeoff_sec": 7.45, "A_air_sec": 7.85, "L_landing_sec": 8.15},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.75, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "blended",
                "confidence": 0.60,
                "quality_flags": [
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.75, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 7.45)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertLessEqual(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_early_compressed_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 6.95, "A_air_sec": 7.35, "L_landing_sec": 7.65},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 6.35, "A_air_sec": 6.55, "L_landing_sec": 6.75},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": [
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.95, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.35, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.65, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.35, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.55, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 6.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.95)
        self.assertIn("video_temporal_quality_retry_early_compressed_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    def test_retry_replacement_rejects_core_spacing_under_one_tenth_second(self) -> None:
        original = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal={"confidence": 0.66, "quality_flags": []},
            resolved_keyframes={
                "source": "skeleton_fallback",
                "confidence": 0.66,
                "quality_flags": ["video_temporal_resolver_motion_cluster_fallback_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 0.812, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 1.062, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 1.625, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
            },
            used_semantic_frames=True,
        )
        retry = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal={"confidence": 0.75, "quality_flags": ["video_temporal_quality_retry"]},
            resolved_keyframes={
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_quality_retry_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 1.053, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 1.600, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 1.633, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
            },
            used_semantic_frames=True,
        )

        self.assertEqual(
            _retry_replacement_rejection_flags(original, retry, analysis_profile="jump"),
            ["video_temporal_quality_retry_core_spacing_rejected"],
        )

    async def test_quality_retry_rejects_early_main_motion_cluster_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.65, "L_landing_sec": 7.95},
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.80,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.65},
                "quality_flags": ["video_temporal_quality_retry"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.95, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.80,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.65, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={
                                                        "selected": [
                                                            {"frame_id": "frame_0022", "timestamp": 7.65, "motion_score": 0.1926},
                                                            {"frame_id": "frame_0023", "timestamp": 7.713, "motion_score": 0.2265},
                                                            {"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166},
                                                            {"frame_id": "frame_0025", "timestamp": 7.838, "motion_score": 0.2097},
                                                            {"frame_id": "frame_0027", "timestamp": 7.963, "motion_score": 0.25},
                                                            {"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302},
                                                        ],
                                                    },
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 7.25)
        self.assertIn("video_temporal_quality_retry_early_main_motion_cluster_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_preserves_unreliable_retry_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 6.35, "A_air_sec": 6.55, "L_landing_sec": 6.75},
                "quality_flags": ["video_temporal_quality_retry"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.70,
                "quality_flags": [
                    "video_temporal_resolver_no_semantic_selection",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_compressed",
                    "video_temporal_resolver_coherent_tal_early_motion_conflict",
                    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.35, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.55, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 6.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=semantic_dir,
                                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_early_motion_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn(
            "video_temporal_resolver_coherent_tal_early_motion_conflict",
            result.resolved_keyframes["video_temporal_quality_retry_rejection_flags"],
        )
        self.assertIn("retry_attempt", result.video_temporal)

    async def test_rejected_retry_diagnostics_do_not_invalidate_original_semantic_frames(self) -> None:
        first_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.80,
            "key_moments": {"T_takeoff_sec": 7.05, "A_air_sec": 7.35, "L_landing_sec": 7.75},
            "quality_flags": ["video_temporal_fallback_recommended"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.20,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_quality_retry", "video_temporal_low_confidence"],
            "validation": {"valid": False, "errors": [], "warnings": ["manual_review"]},
        }
        first_resolved = {
            "source": "blended",
            "confidence": 0.80,
            "quality_flags": [
                "video_temporal_resolver_advisory_fallback_overridden",
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_core_foreground_occlusion_repaired",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 7.05, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 7.35, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 7.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_ai": first_video,
        }
        retry_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.20,
            "quality_flags": [
                "video_temporal_resolver_low_video_confidence",
                "video_temporal_resolver_partial_skeleton_fallback",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [{"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"}],
            "video_ai": retry_video,
        }

        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=first_video,
            resolved_keyframes=first_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=first_resolved["selected"],
            quality_flags=[*first_video["quality_flags"], *first_resolved["quality_flags"]],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[*retry_video["quality_flags"], *retry_resolved["quality_flags"]],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("app.services.semantic_keyframe_pipeline.start_video_temporal_task") as start_mock:
                retry_future = asyncio.get_running_loop().create_future()
                retry_future.set_result(retry_video)
                start_mock.return_value = SimpleNamespace(
                    task=retry_future,
                    source_duration_sec=9.568,
                    ai_clip_payload=lambda: {"duration_sec": 4.6},
                )
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": [{"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302}]},
                        analysis_profile="jump",
                    )

        self.assertIs(updated, result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_partial_skeleton_fallback", updated.resolved_keyframes["quality_flags"])
        self.assertIn(
            "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            updated.resolved_keyframes["video_temporal_quality_retry_rejection_flags"],
        )

    async def test_quality_retry_used_promotes_retry_artifacts_to_official_semantic_dir(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.30,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_missing_core_tal"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_missing_core_tal"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.92,
            "key_moments": {"T_takeoff_sec": 1.0, "A_air_sec": 1.25, "L_landing_sec": 1.55},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            semantic_dir = root / "semantic"
            retry_dir = root / "semantic_retry"
            retry_records = []
            for index, timestamp in enumerate((1.0, 1.25, 1.55), start=1):
                retry_records.append(
                    {
                        "frame_id": f"semantic_{index:04d}",
                        "timestamp": timestamp,
                        "phase_code": ("takeoff", "air", "landing")[index - 1],
                        "key_moment": ("T_takeoff_sec", "A_air_sec", "L_landing_sec")[index - 1],
                    }
                )
            result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=original_video,
                resolved_keyframes={
                    "source": "skeleton_fallback",
                    "confidence": 0.30,
                    "quality_flags": ["video_temporal_resolver_no_semantic_selection"],
                    "selected": [],
                },
                semantic_frames=[],
                semantic_records=[],
                quality_flags=["video_temporal_missing_core_tal", "video_temporal_resolver_no_semantic_selection"],
                used_semantic_frames=False,
                has_semantic_moments=False,
            )

            async def fake_resolve_retry(**kwargs):
                output_dir = kwargs["semantic_frames_dir"]
                output_dir.mkdir(parents=True, exist_ok=True)
                retry_paths = []
                for index in range(1, 4):
                    path = output_dir / f"semantic_{index:04d}.jpg"
                    path.write_bytes(f"retry-{index}".encode("ascii"))
                    retry_paths.append(path)
                return SemanticKeyframePipelineResult(
                    ai_clip=None,
                    video_temporal=retry_video,
                    resolved_keyframes={
                        "source": "video_ai_refined",
                        "confidence": 0.92,
                        "quality_flags": [],
                        "selected": retry_records,
                    },
                    semantic_frames=retry_paths,
                    semantic_records=retry_records,
                    quality_flags=[],
                    used_semantic_frames=True,
                    has_semantic_moments=True,
                )

            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=2.0, ai_clip_payload=lambda: {"duration_sec": 2.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(side_effect=fake_resolve_retry)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        sampling_metadata=VideoSamplingMetadata(0.0, 2.0, 0.0, 2.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": []},
                        analysis_profile="jump",
                    )

            self.assertTrue(updated.used_semantic_frames)
            self.assertIn("video_temporal_quality_retry_used", updated.resolved_keyframes["quality_flags"])
            self.assertEqual([path.parent for path in updated.semantic_frames], [semantic_dir, semantic_dir, semantic_dir])
            self.assertEqual((semantic_dir / "semantic_0001.jpg").read_bytes(), b"retry-1")
            self.assertEqual((semantic_dir / "semantic_0002.jpg").read_bytes(), b"retry-2")
            self.assertEqual((semantic_dir / "semantic_0003.jpg").read_bytes(), b"retry-3")
            self.assertFalse(retry_dir.exists())

    async def test_quality_retry_rejected_result_keeps_original_semantic_frame_artifacts(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.82,
            "key_moments": {"T_takeoff_sec": 1.0, "A_air_sec": 1.25, "L_landing_sec": 1.55},
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 5.0, "A_air_sec": 5.25, "L_landing_sec": 5.55},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            semantic_dir = root / "semantic"
            semantic_dir.mkdir()
            original_paths = []
            original_records = []
            for index, timestamp in enumerate((1.0, 1.25, 1.55), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(f"original-{index}".encode("ascii"))
                original_paths.append(path)
                original_records.append(
                    {
                        "frame_id": f"semantic_{index:04d}",
                        "timestamp": timestamp,
                        "phase_code": ("takeoff", "air", "landing")[index - 1],
                        "key_moment": ("T_takeoff_sec", "A_air_sec", "L_landing_sec")[index - 1],
                    }
                )
            result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=original_video,
                resolved_keyframes={
                    "source": "video_ai_refined",
                    "confidence": 0.82,
                    "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                    "selected": original_records,
                },
                semantic_frames=original_paths,
                semantic_records=original_records,
                quality_flags=["semantic_keyframe_core_foreground_occlusion_repaired"],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=retry_video,
                resolved_keyframes={
                    "source": "video_ai_refined",
                    "confidence": 0.90,
                    "quality_flags": [],
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 5.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                        {"frame_id": "semantic_0002", "timestamp": 5.25, "phase_code": "air", "key_moment": "A_air_sec"},
                        {"frame_id": "semantic_0003", "timestamp": 5.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                    ],
                },
                semantic_frames=[],
                semantic_records=[],
                quality_flags=[],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            resolve_mock = AsyncMock(return_value=retry_result)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=6.0, ai_clip_payload=lambda: {"duration_sec": 6.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", resolve_mock):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        sampling_metadata=VideoSamplingMetadata(0.0, 6.0, 0.0, 6.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": []},
                        analysis_profile="jump",
                    )

            self.assertIs(updated, result)
            self.assertEqual((semantic_dir / "semantic_0001.jpg").read_bytes(), b"original-1")
            self.assertEqual((semantic_dir / "semantic_0002.jpg").read_bytes(), b"original-2")
            self.assertEqual((semantic_dir / "semantic_0003.jpg").read_bytes(), b"original-3")
            self.assertEqual(resolve_mock.await_args.kwargs["semantic_frames_dir"], root / "semantic_retry")

    async def test_quality_retry_starts_when_semantic_tal_conflicts_with_high_confidence_skeleton(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.86,
            "key_moments": {"T_takeoff_sec": 2.0, "A_air_sec": 2.3, "L_landing_sec": 2.6},
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        original_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.86,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 2.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 2.3, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.6, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.9,
            "key_moments": {"T_takeoff_sec": 3.0, "A_air_sec": 3.3, "L_landing_sec": 3.6},
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.9,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 3.3, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 3.6, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=original_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=retry_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        bio_data = {
            "key_frame_candidates": {
                "T": {"timestamp": 3.0, "confidence": 0.82},
                "A": {"timestamp": 3.3, "confidence": 0.78},
                "L": {"timestamp": 3.6, "confidence": 0.80},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=4.0, ai_clip_payload=lambda: {"duration_sec": 4.0})),
            ) as start_mock:
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 4.0, 0.0, 4.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": []},
                        analysis_profile="jump",
                        bio_data=bio_data,
                    )

        self.assertIs(updated, result)
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_skeleton_tal_conflict", updated.resolved_keyframes["quality_flags"])
        start_mock.assert_awaited_once()
        retry_context = start_mock.await_args.kwargs["retry_context"]
        self.assertIn("video_temporal_quality_retry_skeleton_tal_conflict", retry_context["retry_reason_flags"])
        self.assertEqual(retry_context["semantic_skeleton_tal_conflicts"][0]["key"], "T")
        self.assertEqual(retry_context["skeleton_candidate_tal"][0]["key"], "T")
        self.assertEqual(retry_context["skeleton_candidate_tal"][0]["timestamp"], 3.0)
        self.assertAlmostEqual(retry_context["skeleton_candidate_tal"][0]["delta_from_rejected_tal_sec"], 1.0)

    async def test_quality_retry_ignores_skeleton_conflict_from_weak_temporal_geometry_candidate(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.82,
            "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.22, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 5.70, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 6.33, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": ["tal_candidate_temporal_geometry_unreliable", "tal_candidate_takeoff_apex_gap_unreliable"],
                "T": {"timestamp": 6.375, "confidence": 0.65, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                "A": {"timestamp": 8.188, "confidence": 0.63, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                "L": {"timestamp": 8.25, "confidence": 0.70, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
            }
        }

        flags = _video_temporal_retry_reason_flags(
            {"confidence": 0.82, "quality_flags": []},
            resolved,
            analysis_profile="jump",
            bio_data=bio_data,
        )

        self.assertNotIn("video_temporal_quality_retry_skeleton_tal_conflict", flags)
        self.assertIn(
            "video_temporal_quality_retry_skeleton_tal_conflict_ignored_weak_temporal_geometry",
            resolved["quality_flags"],
        )
        self.assertEqual(resolved["semantic_skeleton_tal_conflict_decision"], "ignored_weak_temporal_geometry_candidate")

    async def test_quality_retry_rejects_early_semantic_takeoff_when_candidate_core_still_aligns(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.30, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 1.75, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.25, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                ],
                "T": {
                    "timestamp": 1.625,
                    "confidence": 0.806,
                    "warnings": ["keyframe_candidates_motion_fallback"],
                    "evidence": {"motion_score": 0.0614},
                },
                "A": {
                    "timestamp": 1.875,
                    "confidence": 0.487,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                    "evidence": {"motion_score": 0.0492},
                },
                "L": {
                    "timestamp": 2.125,
                    "confidence": 0.48,
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "l_pose_signal_drifted",
                        "landing_low_tail_motion_plateau_early_contact",
                    ],
                    "evidence": {"motion_score": 0.0427},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0016", "timestamp": 1.25, "motion_score": 0.0589},
                {"frame_id": "frame_0017", "timestamp": 1.375, "motion_score": 0.0420},
                {"frame_id": "frame_0018", "timestamp": 1.625, "motion_score": 0.0614},
                {"frame_id": "frame_0019", "timestamp": 1.875, "motion_score": 0.0492},
                {"frame_id": "frame_0020", "timestamp": 2.125, "motion_score": 0.0427},
            ],
        }

        flags = _video_temporal_retry_reason_flags(
            {
                "confidence": 0.85,
                "quality_flags": [],
                "key_moments": {"T_takeoff_sec": 1.30, "A_air_sec": 1.75, "L_landing_sec": 2.25},
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 1.0, "time_end": 1.5, "key_frame_hint": 1.30, "confidence": 0.8},
                    {"phase_code": "air", "time_start": 1.5, "time_end": 2.0, "key_frame_hint": 1.75, "confidence": 0.85},
                    {"phase_code": "landing", "time_start": 2.0, "time_end": 2.5, "key_frame_hint": 2.25, "confidence": 0.8},
                ],
            },
            resolved,
            analysis_profile="jump",
            motion_scores=motion_scores,
            bio_data=bio_data,
        )

        self.assertIn("semantic_keyframes_unreliable_candidate_early_takeoff_conflict", flags)
        self.assertIn("semantic_keyframes_unreliable_candidate_early_takeoff_conflict", resolved["quality_flags"])
        diagnostic = resolved["semantic_candidate_tal_conflict"]["early_takeoff_conflict"]
        self.assertEqual(diagnostic["support_mode"], "early_semantic_takeoff_over_ordered_candidate_core")
        self.assertEqual(diagnostic["conflict"]["key"], "T")
        self.assertAlmostEqual(diagnostic["core_delta_sec"]["T"], 0.325)
        self.assertAlmostEqual(diagnostic["core_delta_sec"]["A"], -0.125)
        self.assertAlmostEqual(diagnostic["core_delta_sec"]["L"], 0.125)

    async def test_quality_retry_rejects_replacement_that_still_conflicts_with_skeleton(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.70,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_missing_core_tal"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_missing_core_tal"]},
        }
        original_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.40,
            "quality_flags": ["video_temporal_resolver_partial_skeleton_fallback"],
            "selected": [
                {"frame_id": "frame_0005", "timestamp": 0.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            ],
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 5.9, "A_air_sec": 6.2, "L_landing_sec": 6.6},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.9, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 6.2, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 6.6, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=False,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=retry_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        bio_data = {
            "key_frame_candidates": {
                "T": {"timestamp": 0.812, "confidence": 0.84},
                "A": {"timestamp": 1.0, "confidence": 0.78},
                "L": {"timestamp": 1.2, "confidence": 0.72},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.0, ai_clip_payload=lambda: {"duration_sec": 7.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": []},
                        analysis_profile="jump",
                        bio_data=bio_data,
                    )

        self.assertIs(updated, result)
        self.assertFalse(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_skeleton_tal_conflict_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("retry_attempt", updated.video_temporal)

    async def test_quality_retry_downgrades_original_semantic_when_original_skeleton_conflict_remains(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 4.5, "A_air_sec": 5.1, "L_landing_sec": 5.6},
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        original_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_candidate",
                "video_temporal_quality_retry_skeleton_tal_conflict",
            ],
            "semantic_skeleton_tal_conflicts": [
                {"key": "T", "semantic_timestamp": 4.5, "skeleton_timestamp": 0.562, "delta_sec": 3.938},
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 4.5, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                {"frame_id": "semantic_0002", "timestamp": 5.1, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"frame_id": "semantic_0003", "timestamp": 5.687, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
            ],
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 4.5, "A_air_sec": 5.1, "L_landing_sec": 5.6},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [],
            "selected": [
                {"frame_id": "retry_0001", "timestamp": 4.5, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "retry_0002", "timestamp": 5.1, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "retry_0003", "timestamp": 5.687, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=original_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[Path("retry_0001.jpg"), Path("retry_0002.jpg"), Path("retry_0003.jpg")],
            semantic_records=retry_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                "T": {"frame_id": "frame_0009", "timestamp": 0.562, "confidence": 0.627},
                "A": {"frame_id": "frame_0010", "timestamp": 1.125, "confidence": 0.48},
                "L": {"frame_id": "frame_0011", "timestamp": 1.688, "confidence": 0.35},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.0, ai_clip_payload=lambda: {"duration_sec": 7.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": []},
                        analysis_profile="jump",
                        bio_data=bio_data,
                    )

        self.assertIs(updated, result)
        self.assertFalse(updated.used_semantic_frames)
        self.assertEqual(updated.effective_source, "sampled_frames")
        self.assertEqual([item["timestamp"] for item in updated.resolved_keyframes["selected"][:3]], [0.562, 1.125, 1.688])
        self.assertEqual(updated.resolved_keyframes["source"], "skeleton_fallback")
        self.assertIn("semantic_keyframes_unreliable_after_retry_rejection", updated.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", updated.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in updated.resolved_keyframes["rejected_semantic_selected"][:3]], [4.5, 5.1, 5.687])

    async def test_quality_retry_rejection_does_not_downgrade_visible_phase_range_promotion(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.85,
            "key_moments": {"T_takeoff_sec": 4.7, "A_air_sec": 5.0, "L_landing_sec": 5.3},
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        original_resolved = {
            "source": "blended",
            "confidence": 0.85,
            "quality_flags": [
                "video_temporal_resolver_phase_range_visual_tal_promoted",
                "video_temporal_resolver_phase_range_zoomed_visual_check",
                "semantic_keyframes_phase_range_visual_tal_promoted",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 4.7,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_temporal_phase_range_visual_tal_promoted",
                    "confidence": 0.8,
                    "semantic_visibility": {"status": "target_visible"},
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 5.0,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_temporal_phase_range_visual_tal_promoted",
                    "confidence": 0.8,
                    "semantic_visibility": {"status": "target_visible"},
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 5.3,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_temporal_phase_range_visual_tal_promoted",
                    "confidence": 0.8,
                    "semantic_visibility": {"status": "target_visible"},
                },
            ],
            "video_ai": original_video,
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.80,
            "key_moments": {"T_takeoff_sec": 4.25, "A_air_sec": 4.7, "L_landing_sec": 5.05},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.80,
            "quality_flags": [
                "video_temporal_quality_retry_skeleton_tal_conflict",
                "semantic_keyframe_core_foreground_occlusion",
                "semantic_keyframes_unreliable_after_visibility_check",
            ],
            "selected": [
                {"frame_id": "retry_0001", "timestamp": 3.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "retry_0002", "timestamp": 4.23, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "retry_0003", "timestamp": 4.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=original_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {"frame_id": "frame_0019", "timestamp": 3.688, "confidence": 0.652},
                "A": {"frame_id": "frame_0020", "timestamp": 3.75, "confidence": 0.389},
                "L": {"frame_id": "frame_0023", "timestamp": 3.938, "confidence": 0.35},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.0, ai_clip_payload=lambda: {"duration_sec": 7.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": []},
                        analysis_profile="jump",
                        bio_data=bio_data,
                    )

        self.assertIs(updated, result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertEqual(updated.effective_source, "blended")
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_after_retry_rejection", updated.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in updated.resolved_keyframes["selected"][:3]], [4.7, 5.0, 5.3])
        self.assertTrue(semantic_keyframes_are_reliable(updated.resolved_keyframes))

    async def test_quality_retry_rejection_keeps_full_context_weak_candidate_semantic(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 2.3, "A_air_sec": 2.7, "L_landing_sec": 3.153},
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        original_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_refinement_delta_rejected",
                "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_weak_candidate",
                "video_temporal_quality_retry_motion_cluster_conflict",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 2.3, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"frame_id": "semantic_0002", "timestamp": 2.7, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                {"frame_id": "semantic_0003", "timestamp": 3.153, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "semantic_candidate_tal_conflict": {
                "decision": "ignored_full_context_weak_candidate_motion_window_conflict",
            },
            "video_ai": original_video,
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.80,
            "key_moments": {"T_takeoff_sec": 13.7, "A_air_sec": 14.3, "L_landing_sec": 14.8},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.80,
            "quality_flags": [
                "semantic_keyframes_unreliable_candidate_motion_window_conflict",
                "video_temporal_quality_retry_motion_cluster_conflict",
                "semantic_keyframes_unreliable_after_refinement",
            ],
            "selected": [
                {"frame_id": "retry_0001", "timestamp": 13.7, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "retry_0002", "timestamp": 14.3, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "retry_0003", "timestamp": 14.8, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=original_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_sparse_takeoff_prepeak_estimated",
                    "tal_candidate_landing_geometry_weak",
                ],
                "T": {"frame_id": "frame_0027", "timestamp": 18.19, "confidence": 0.58},
                "A": {"frame_id": "frame_0030", "timestamp": 18.75, "confidence": 0.552},
                "L": {"frame_id": "frame_0031", "timestamp": 19.312, "confidence": 0.367},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=20.5, ai_clip_payload=lambda: {"duration_sec": 20.5})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 20.5, 0.0, 20.5, 16.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores={"selected": []},
                        analysis_profile="jump",
                        bio_data=bio_data,
                    )

        self.assertIs(updated, result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertEqual(updated.effective_source, "video_ai_refined")
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_after_retry_rejection", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", updated.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in updated.resolved_keyframes["selected"][:3]], [2.3, 2.7, 3.153])
        self.assertTrue(semantic_keyframes_are_reliable(updated.resolved_keyframes))

    async def test_quality_retry_rejects_replacement_that_still_conflicts_with_motion_cluster(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.70,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_missing_core_tal"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_missing_core_tal"]},
        }
        original_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.40,
            "quality_flags": ["video_temporal_resolver_partial_skeleton_fallback"],
            "selected": [
                {"frame_id": "frame_0005", "timestamp": 0.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            ],
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 5.9, "A_air_sec": 6.2, "L_landing_sec": 6.6},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.9, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 6.2, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 6.6, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=False,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=retry_resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0002", "timestamp": 0.25, "motion_score": 0.14},
                {"frame_id": "frame_0003", "timestamp": 0.31, "motion_score": 0.15},
                {"frame_id": "frame_0004", "timestamp": 0.38, "motion_score": 0.14},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.0, ai_clip_payload=lambda: {"duration_sec": 7.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores=motion_scores,
                        analysis_profile="jump",
                        bio_data=None,
                    )

        self.assertIs(updated, result)
        self.assertFalse(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_motion_cluster_conflict_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("retry_attempt", updated.video_temporal)

    async def test_quality_retry_does_not_start_when_motion_cluster_conflict_has_near_skeleton_candidate_support(self) -> None:
        video_temporal = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.80,
            "fallback_recommendation": "use_video_timestamps",
            "key_moments": {"T_takeoff_sec": 1.795, "A_air_sec": 2.2, "L_landing_sec": 2.333},
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        resolved = {
            "source": "blended",
            "confidence": 0.80,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.795, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 2.2, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.333, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=video_temporal,
            resolved_keyframes=resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=resolved["selected"],
            quality_flags=[],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0028", "timestamp": 1.9, "motion_score": 0.04},
                {"frame_id": "frame_0030", "timestamp": 2.2, "motion_score": 0.035},
                {"frame_id": "frame_0032", "timestamp": 2.35, "motion_score": 0.04},
                {"frame_id": "frame_0060", "timestamp": 5.0, "motion_score": 0.20},
                {"frame_id": "frame_0061", "timestamp": 5.063, "motion_score": 0.19},
            ]
        }
        bio_data = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0019", "timestamp": 1.875, "confidence": 0.702},
                "A": {"frame_id": "frame_0022", "timestamp": 2.25, "confidence": 0.481},
                "L": {"frame_id": "frame_0023", "timestamp": 2.312, "confidence": 0.35},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("app.services.semantic_keyframe_pipeline.start_video_temporal_task", AsyncMock()) as start_task:
                updated = await retry_video_temporal_if_needed(
                    result=result,
                    video_path=root / "source.mp4",
                    work_dir=root,
                    semantic_frames_dir=root / "semantic",
                    sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 10.0, 30.0, False),
                    action_type="jump",
                    action_subtype=None,
                    motion_scores=motion_scores,
                    analysis_profile="jump",
                    bio_data=bio_data,
                )

        self.assertIs(updated, result)
        start_task.assert_not_awaited()
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate",
            updated.resolved_keyframes["quality_flags"],
        )
        self.assertEqual(
            updated.resolved_keyframes["semantic_motion_cluster_conflict"]["decision"],
            "ignored_near_skeleton_candidate_tal",
        )
        self.assertNotIn("video_temporal_quality_retry_motion_cluster_conflict", updated.resolved_keyframes["quality_flags"])

    async def test_quality_retry_keeps_replacement_when_motion_cluster_conflict_has_near_skeleton_candidate_support(self) -> None:
        original = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal={
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_missing_core_tal"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_missing_core_tal"]},
            },
            resolved_keyframes={
                "source": "skeleton_fallback",
                "confidence": 0.40,
                "quality_flags": ["video_temporal_resolver_partial_skeleton_fallback"],
                "selected": [
                    {"frame_id": "frame_0005", "timestamp": 0.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                ],
            },
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=False,
        )
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 1.795, "A_air_sec": 2.2, "L_landing_sec": 2.333},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.795, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 2.2, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.333, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0028", "timestamp": 1.9, "motion_score": 0.04},
                {"frame_id": "frame_0030", "timestamp": 2.2, "motion_score": 0.035},
                {"frame_id": "frame_0032", "timestamp": 2.35, "motion_score": 0.04},
                {"frame_id": "frame_0060", "timestamp": 5.0, "motion_score": 0.20},
                {"frame_id": "frame_0061", "timestamp": 5.063, "motion_score": 0.19},
            ]
        }
        bio_data = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0019", "timestamp": 1.875, "confidence": 0.702},
                "A": {"frame_id": "frame_0022", "timestamp": 2.25, "confidence": 0.481},
                "L": {"frame_id": "frame_0023", "timestamp": 2.312, "confidence": 0.35},
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_paths = [root / "retry_1.jpg", root / "retry_2.jpg", root / "retry_3.jpg"]
            for path in retry_paths:
                path.write_bytes(b"fake-jpeg")
            retry_result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=retry_video,
                resolved_keyframes=retry_resolved,
                semantic_frames=retry_paths,
                semantic_records=retry_resolved["selected"],
                quality_flags=[],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.0, ai_clip_payload=lambda: {"duration_sec": 7.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=original,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores=motion_scores,
                        analysis_profile="jump",
                        bio_data=bio_data,
                    )

        self.assertIs(updated, retry_result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_used", updated.resolved_keyframes["quality_flags"])
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_near_skeleton_candidate",
            updated.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("video_temporal_quality_retry_motion_cluster_conflict_rejected", updated.resolved_keyframes["quality_flags"])

    async def test_pipeline_keeps_refinement_rejected_tal_when_skeleton_boundaries_support_same_jump(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 1.77, "A_air_sec": 2.02, "L_landing_sec": 2.32},
                "quality_flags": ["video_temporal_quality_retry"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_takeoff_refinement_delta_expanded",
                    "video_temporal_resolver_landing_refinement_phase_tolerance",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 1.77,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "confidence": 0.8,
                        "phase_time_start": 1.67,
                        "phase_time_end": 1.87,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 2.02,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "confidence": 0.8,
                        "phase_time_start": 1.87,
                        "phase_time_end": 2.17,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 2.32,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.75,
                        "phase_time_start": 2.17,
                        "phase_time_end": 2.47,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined = [
                {
                    **resolved["selected"][0],
                    "pre_refine_timestamp": 1.77,
                    "refinement_method": "local_motion_peak_phase_rejected",
                    "refinement_delta_sec": 0.0,
                    "refinement_motion_score": 0.038,
                    "refinement_candidate_timestamp": 1.62,
                    "refinement_candidate_delta_sec": -0.15,
                    "refinement_reject_reason": "phase",
                },
                {
                    **resolved["selected"][1],
                    "pre_refine_timestamp": 2.02,
                    "refinement_method": "apex_preserved",
                    "refinement_delta_sec": 0.0,
                    "refinement_motion_score": None,
                },
                {
                    **resolved["selected"][2],
                    "pre_refine_timestamp": 2.32,
                    "refinement_method": "local_motion_peak_order_rejected",
                    "refinement_delta_sec": 0.0,
                    "refinement_motion_score": 0.036,
                    "refinement_candidate_timestamp": 2.05,
                    "refinement_candidate_delta_sec": -0.27,
                    "refinement_reject_reason": "order",
                },
            ]
            bio_data = {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0019", "timestamp": 1.875, "confidence": 0.702},
                    "A": {
                        "frame_id": "frame_0022",
                        "timestamp": 2.25,
                        "confidence": 0.481,
                        "warnings": ["confidence_missing_knee_angle_change", "apex_local_minimum_not_clear"],
                    },
                    "L": {
                        "frame_id": "frame_0023",
                        "timestamp": 2.312,
                        "confidence": 0.35,
                        "warnings": ["landing_geometry_weak"],
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(
                        return_value=(
                            refined,
                            [
                                "semantic_keyframe_refinement_order_rejected",
                                "semantic_keyframe_refinement_phase_rejected",
                            ],
                        )
                    ),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=video_temporal,
                                motion_scores={
                                    "selected": [
                                        {"frame_id": "frame_0004", "timestamp": 0.312, "motion_score": 0.1481},
                                        {"frame_id": "frame_0019", "timestamp": 1.875, "motion_score": 0.0491},
                                        {"frame_id": "frame_0022", "timestamp": 2.25, "motion_score": 0.0427},
                                        {"frame_id": "frame_0023", "timestamp": 2.312, "motion_score": 0.0385},
                                    ]
                                },
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.3, 0.0, 7.3, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=7.3,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [1.77, 2.02, 2.32])
        self.assertIn(
            "semantic_keyframe_refinement_rejection_ignored_near_skeleton_candidate",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_refinement_rejection"]
        self.assertEqual(diagnostic["decision"], "ignored_near_skeleton_candidate_tal")
        self.assertEqual(
            diagnostic["candidate_support"]["support_mode"],
            "takeoff_landing_boundary_with_weak_apex_candidate",
        )

    async def test_quality_retry_keeps_replacement_when_motion_cluster_matches_unreliable_pose_fallback(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.70,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_missing_core_tal"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_missing_core_tal"]},
        }
        original_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.40,
            "quality_flags": ["video_temporal_resolver_partial_skeleton_fallback"],
            "selected": [
                {"frame_id": "frame_0005", "timestamp": 1.312, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            ],
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.90,
            "key_moments": {"T_takeoff_sec": 3.5, "A_air_sec": 4.0, "L_landing_sec": 4.5},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.553, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 4.0, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 4.5, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes=original_resolved,
            semantic_frames=[],
            semantic_records=[],
            quality_flags=[],
            used_semantic_frames=False,
            has_semantic_moments=False,
        )
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0015", "timestamp": 2.562, "motion_score": 0.2292},
                {"frame_id": "frame_0016", "timestamp": 2.625, "motion_score": 0.2258},
                {"frame_id": "frame_0017", "timestamp": 2.688, "motion_score": 0.1998},
                {"frame_id": "frame_0022", "timestamp": 5.125, "motion_score": 0.0919},
                {"frame_id": "frame_0023", "timestamp": 5.188, "motion_score": 0.1067},
            ]
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_unreliable_pose_state",
                ],
                "motion_fallback_unreliable_pose_records": {
                    "L": {"frame_id": "frame_0015", "tracking_state": "interpolated", "tracker_state": "lost_reused"},
                },
                "T": {"frame_id": "frame_0010", "timestamp": 1.312, "confidence": 0.617},
                "A": {"frame_id": "frame_0011", "timestamp": 1.688, "confidence": 0.47},
                "L": {
                    "frame_id": "frame_0015",
                    "timestamp": 2.562,
                    "confidence": 0.58,
                    "warnings": ["keyframe_candidates_motion_fallback_unreliable_pose_state"],
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_paths = [root / "retry_1.jpg", root / "retry_2.jpg", root / "retry_3.jpg"]
            for path in retry_paths:
                path.write_bytes(b"fake-jpeg")
            retry_result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=retry_video,
                resolved_keyframes=retry_resolved,
                semantic_frames=retry_paths,
                semantic_records=retry_resolved["selected"],
                quality_flags=[],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.0, ai_clip_payload=lambda: {"duration_sec": 7.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 10.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores=motion_scores,
                        analysis_profile="jump",
                        bio_data=bio_data,
                    )

        self.assertIs(updated, retry_result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_used", updated.resolved_keyframes["quality_flags"])
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_unreliable_pose_fallback",
            updated.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("video_temporal_quality_retry_motion_cluster_conflict_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertEqual(
            updated.resolved_keyframes["semantic_motion_cluster_conflict"]["decision"],
            "ignored_unreliable_pose_motion_fallback_cluster",
        )

    async def test_quality_retry_rejection_can_downgrade_original_to_motion_cluster_fallback(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.85,
            "fallback_recommendation": "use_video_timestamps",
            "key_moments": {"T_takeoff_sec": 2.1, "A_air_sec": 2.45, "L_landing_sec": 2.75},
            "phase_segments": [
                {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 1.9, "time_end": 2.3, "key_frame_hint": 2.1, "confidence": 0.8},
                {"phase_code": "air", "phase_label": "air", "time_start": 2.3, "time_end": 2.6, "key_frame_hint": 2.45, "confidence": 0.75},
                {"phase_code": "landing", "phase_label": "landing", "time_start": 2.6, "time_end": 2.9, "key_frame_hint": 2.75, "confidence": 0.8},
            ],
            "quality_flags": ["limited takeoff power"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_video = {
            **original_video,
            "quality_flags": ["video_temporal_quality_retry"],
            "key_moments": {"T_takeoff_sec": 2.0, "A_air_sec": 2.4, "L_landing_sec": 2.8},
        }
        original_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": ["video_temporal_quality_retry_skeleton_tal_conflict"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 2.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 2.45, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.86,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 2.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 2.4, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.8, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0009", "timestamp": 0.812, "confidence": 0.843},
                "A": {"frame_id": "frame_0031", "timestamp": 5.875, "confidence": 0.527},
                "L": {"frame_id": "frame_0032", "timestamp": 6.625, "confidence": 0.35},
            }
        }
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "selected": [],
            "scores": [
                0.0,
                0.0634,
                0.0836,
                0.1101,
                0.1193,
                0.1481,
                0.144,
                0.1253,
                0.0743,
                0.1184,
                0.1218,
                0.1278,
                0.1384,
                0.1384,
                0.1284,
                0.1142,
                0.0661,
                0.1051,
                0.0963,
                0.0763,
                0.0589,
                0.0521,
                0.042,
                0.0536,
                0.0406,
                0.0557,
                0.0614,
                0.0512,
                0.0491,
                0.0631,
                0.0491,
                0.0592,
                0.0335,
                0.0342,
                0.0427,
                0.0386,
                0.0427,
                0.0385,
                0.0292,
                0.0344,
                0.0235,
                0.0359,
                0.0313,
                0.035,
                0.0283,
                0.0371,
                0.0312,
                0.0301,
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            semantic_dir = root / "semantic"
            semantic_dir.mkdir()
            original_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(f"late-{index}".encode("ascii"))
                original_paths.append(path)
            result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=original_video,
                resolved_keyframes=original_resolved,
                semantic_frames=original_paths,
                semantic_records=original_resolved["selected"],
                quality_flags=original_resolved["quality_flags"],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=retry_video,
                resolved_keyframes=retry_resolved,
                semantic_frames=[],
                semantic_records=retry_resolved["selected"],
                quality_flags=[],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.3, ai_clip_payload=lambda: {"duration_sec": 7.3})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            updated = await retry_video_temporal_if_needed(
                                result=result,
                                video_path=root / "source.mp4",
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.3, 0.0, 7.3, 16.0, 30.0, False),
                                action_type="jump",
                                action_subtype=None,
                                motion_scores=motion_scores,
                                analysis_profile="jump",
                                bio_data=bio_data,
                            )
            self.assertEqual(updated.semantic_frames[0].read_bytes(), b"frame")

        self.assertIsNot(updated, result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertEqual(updated.resolved_keyframes["source"], "skeleton_fallback")
        self.assertIn("video_temporal_quality_retry_motion_cluster_fallback_used", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_skeleton_tal_conflict_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertEqual([record["timestamp"] for record in updated.resolved_keyframes["selected"][:3]], [0.812, 1.062, 1.625])

    async def test_quality_retry_rejection_downgrades_extreme_late_original_to_motion_cluster_fallback(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.85,
            "fallback_recommendation": "use_video_timestamps",
            "key_moments": {"T_takeoff_sec": 4.1, "A_air_sec": 4.55, "L_landing_sec": 5.05},
            "phase_segments": [
                {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 4.0, "time_end": 4.3, "key_frame_hint": 4.1, "confidence": 0.8},
                {"phase_code": "air", "phase_label": "air", "time_start": 4.3, "time_end": 4.8, "key_frame_hint": 4.55, "confidence": 0.85},
                {"phase_code": "landing", "phase_label": "landing", "time_start": 4.8, "time_end": 5.2, "key_frame_hint": 5.05, "confidence": 0.9},
            ],
            "quality_flags": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        retry_video = {**original_video, "quality_flags": ["video_temporal_quality_retry"]}
        original_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": [
                "video_temporal_quality_retry_skeleton_tal_conflict",
                "video_temporal_quality_retry_motion_cluster_conflict",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 4.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 4.55, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 5.05, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        retry_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.86,
            "quality_flags": [],
            "selected": original_resolved["selected"],
        }
        bio_data = {
            "key_frame_candidates": {
                "T": {"frame_id": "frame_0009", "timestamp": 0.812, "confidence": 0.843},
                "A": {"frame_id": "frame_0031", "timestamp": 5.875, "confidence": 0.527},
                "L": {"frame_id": "frame_0032", "timestamp": 6.625, "confidence": 0.35},
            }
        }
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "selected": [],
            "scores": [
                0.0, 0.0634, 0.0836, 0.1101, 0.1193, 0.1481, 0.144, 0.1253,
                0.0743, 0.1184, 0.1218, 0.1278, 0.1384, 0.1384, 0.1284, 0.1142,
                0.0661, 0.1051, 0.0963, 0.0763, 0.0589, 0.0521, 0.042, 0.0536,
                0.0406, 0.0557, 0.0614, 0.0512, 0.0491, 0.0631, 0.0491, 0.0592,
                0.0335, 0.0342, 0.0427, 0.0386, 0.0427, 0.0385, 0.0292, 0.0344,
                0.0235, 0.0359, 0.0313, 0.035, 0.0283, 0.0371, 0.0312, 0.0301,
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            semantic_dir = root / "semantic"
            semantic_dir.mkdir()
            original_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(f"late-{index}".encode("ascii"))
                original_paths.append(path)
            result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=original_video,
                resolved_keyframes=original_resolved,
                semantic_frames=original_paths,
                semantic_records=original_resolved["selected"],
                quality_flags=original_resolved["quality_flags"],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=retry_video,
                resolved_keyframes=retry_resolved,
                semantic_frames=[],
                semantic_records=retry_resolved["selected"],
                quality_flags=[],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=7.3, ai_clip_payload=lambda: {"duration_sec": 7.3})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            updated = await retry_video_temporal_if_needed(
                                result=result,
                                video_path=root / "source.mp4",
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.3, 0.0, 7.3, 16.0, 30.0, False),
                                action_type="jump",
                                action_subtype=None,
                                motion_scores=motion_scores,
                                analysis_profile="jump",
                                bio_data=bio_data,
                            )

        self.assertIsNot(updated, result)
        self.assertEqual(updated.resolved_keyframes["source"], "skeleton_fallback")
        self.assertIn("video_temporal_quality_retry_extreme_late_motion_cluster_conflict", updated.resolved_keyframes["quality_flags"])
        self.assertEqual([record["timestamp"] for record in updated.resolved_keyframes["selected"][:3]], [0.812, 1.062, 1.625])

    async def test_quality_retry_can_partially_merge_clearer_takeoff_when_retry_landing_is_occluded(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.75,
            "key_moments": {"T_takeoff_sec": 6.95, "A_air_sec": 7.65, "L_landing_sec": 8.05},
            "quality_flags": ["video_temporal_not_high_confidence"],
            "validation": {"valid": True, "errors": [], "warnings": ["video_temporal_not_high_confidence"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.85,
            "key_moments": {"T_takeoff_sec": 7.40, "A_air_sec": 7.65, "L_landing_sec": 7.90},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        original_selected = [
            {"frame_id": "semantic_0001", "timestamp": 6.903, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
            {"frame_id": "semantic_0003", "timestamp": 8.037, "phase_code": "landing", "key_moment": "L_landing_sec"},
        ]
        retry_selected = [
            {
                "frame_id": "semantic_0001",
                "timestamp": 7.40,
                "phase_code": "takeoff",
                "key_moment": "T_takeoff_sec",
                "phase_time_start": 7.25,
                "phase_time_end": 7.50,
            },
            {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
            {
                "frame_id": "semantic_0003",
                "timestamp": 7.80,
                "phase_code": "landing",
                "key_moment": "L_landing_sec",
                "semantic_visibility": {"status": "foreground_person_occluded"},
            },
        ]
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=original_video,
            resolved_keyframes={
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_used",
                    "semantic_keyframe_core_foreground_occlusion_repaired",
                ],
                "selected": original_selected,
                "video_ai": original_video,
            },
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=original_selected,
            quality_flags=[
                "video_temporal_not_high_confidence",
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_core_foreground_occlusion_repaired",
            ],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes={
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion", "semantic_keyframes_unreliable_after_visibility_check"],
                "selected": retry_selected,
                "video_ai": retry_video,
            },
            semantic_frames=[],
            semantic_records=[],
            quality_flags=["video_temporal_quality_retry", "semantic_keyframe_core_foreground_occlusion", "semantic_keyframes_unreliable_after_visibility_check"],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            extracted_records: list[dict[str, object]] = []

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                extracted_records[:] = [dict(record) for record in records]
                paths = []
                copied = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"frame")
                    paths.append(path)
                    copied.append(dict(record))
                return paths, copied

            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=9.568, ai_clip_payload=lambda: {"duration_sec": 4.6})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", fake_extract):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            updated = await retry_video_temporal_if_needed(
                                result=result,
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic",
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                action_type="jump",
                                action_subtype=None,
                                motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                analysis_profile="jump",
                            )

        self.assertIsNot(updated, result)
        self.assertTrue(updated.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_takeoff_partial_merge_used", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertEqual([record["timestamp"] for record in extracted_records[:3]], [7.40, 7.65, 8.037])
        self.assertEqual(updated.resolved_keyframes["selected"][0]["selection_reason"], "video_temporal_quality_retry_takeoff_partial_merge")
        self.assertEqual(updated.resolved_keyframes["selected"][0]["retry_partial_merge_from_timestamp"], 6.903)
        self.assertEqual(updated.effective_source, "blended")

    async def test_quality_retry_partial_merge_unreliable_candidate_keeps_original_artifacts(self) -> None:
        original_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.70,
            "key_moments": {"T_takeoff_sec": 6.90, "A_air_sec": 7.65, "L_landing_sec": 8.03},
            "quality_flags": ["video_temporal_fallback_recommended"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.85,
            "key_moments": {"T_takeoff_sec": 7.40, "A_air_sec": 7.65, "L_landing_sec": 8.03},
            "quality_flags": ["video_temporal_quality_retry"],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }
        original_selected = [
            {"frame_id": "semantic_0001", "timestamp": 6.90, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
            {"frame_id": "semantic_0003", "timestamp": 8.03, "phase_code": "landing", "key_moment": "L_landing_sec"},
        ]
        retry_selected = [
            {"frame_id": "semantic_0001", "timestamp": 7.40, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
            {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
            {"frame_id": "semantic_0003", "timestamp": 8.03, "phase_code": "landing", "key_moment": "L_landing_sec"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            semantic_dir = root / "semantic"
            semantic_dir.mkdir()
            original_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.write_bytes(f"original-{index}".encode("ascii"))
                original_paths.append(path)
            result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=original_video,
                resolved_keyframes={
                    "source": "blended",
                    "confidence": 0.75,
                    "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                    "selected": original_selected,
                },
                semantic_frames=original_paths,
                semantic_records=original_selected,
                quality_flags=["semantic_keyframe_core_foreground_occlusion_repaired"],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            retry_result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=retry_video,
                resolved_keyframes={
                    "source": "video_ai_refined",
                    "confidence": 0.85,
                    "quality_flags": ["semantic_keyframe_core_foreground_occlusion"],
                    "selected": retry_selected,
                },
                semantic_frames=[],
                semantic_records=[],
                quality_flags=["semantic_keyframe_core_foreground_occlusion"],
                used_semantic_frames=False,
                has_semantic_moments=True,
            )
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(f"candidate-{index}".encode("ascii"))
                    paths.append(path)
                    copied_record = {**record, "frame_id": f"{prefix}_{index:04d}"}
                    if index == 1:
                        copied_record["semantic_visibility"] = {"status": "foreground_person_occluded"}
                    copied.append(copied_record)
                return paths, copied

            def fake_visibility(_frame_paths, records, **_kwargs):
                inspected = [dict(record) for record in records]
                if inspected:
                    inspected[0]["semantic_visibility"] = {"status": "foreground_person_occluded"}
                return inspected, ["semantic_keyframe_core_foreground_occlusion"]

            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=9.0, ai_clip_payload=lambda: {"duration_sec": 9.0})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", fake_extract):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=[]):
                            with patch("app.services.semantic_keyframe_pipeline._semantic_frame_visibility_flags", fake_visibility):
                                updated = await retry_video_temporal_if_needed(
                                    result=result,
                                    video_path=root / "source.mp4",
                                    work_dir=root,
                                    semantic_frames_dir=semantic_dir,
                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                    action_type="jump",
                                    action_subtype=None,
                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                    analysis_profile="jump",
                                )

            self.assertIs(updated, result)
            self.assertEqual((semantic_dir / "semantic_0001.jpg").read_bytes(), b"original-1")
            self.assertEqual((semantic_dir / "semantic_0002.jpg").read_bytes(), b"original-2")
            self.assertEqual((semantic_dir / "semantic_0003.jpg").read_bytes(), b"original-3")
            self.assertFalse((root / "semantic_partial_merge").exists())

    async def test_quality_retry_rejects_late_drift_when_original_semantic_frames_are_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.7 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.55},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 7.35, "A_air_sec": 7.85, "L_landing_sec": 8.35},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": ["semantic_keyframe_core_foreground_occlusion_repaired"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.35, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.85, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.35, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.75)
        self.assertIn("video_temporal_quality_retry_late_drift_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_late_drift_from_unreliable_but_ordered_original_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            original_paths = []
            retry_paths = []
            original_records = []
            retry_records = []
            original_timestamps = [6.85, 7.25, 7.55]
            retry_timestamps = [7.25, 7.65, 8.15]
            for index, (phase_code, original_timestamp, retry_timestamp) in enumerate(
                zip(("takeoff", "air", "landing"), original_timestamps, retry_timestamps),
                start=1,
            ):
                original_path = semantic_dir / f"original_{index:04d}.jpg"
                retry_path = semantic_dir / f"retry_{index:04d}.jpg"
                original_path.parent.mkdir(parents=True, exist_ok=True)
                original_path.write_bytes(b"semantic")
                retry_path.write_bytes(b"semantic")
                original_paths.append(original_path)
                retry_paths.append(retry_path)
                original_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": original_timestamp, "phase_code": phase_code})
                retry_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": retry_timestamp, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "key_moments": {"T_takeoff_sec": 6.85, "A_air_sec": 7.25, "L_landing_sec": 7.55},
                "quality_flags": ["video_temporal_not_high_confidence"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.65, "L_landing_sec": 8.15},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["semantic_keyframes_unreliable_after_visibility_check"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.85, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.25, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.65, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 8.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                if records and records[0].get("timestamp") == 6.85:
                    return original_paths, original_records
                return retry_paths, retry_records

            async def fake_refine(_: Path, output_dir: Path, records: list[dict[str, object]], **kwargs: object):
                return records, []

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=fake_refine),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0028", "timestamp": 8.025, "motion_score": 0.2302}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.85)
        self.assertIn("video_temporal_quality_retry_late_drift_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_low_confidence_late_shift_with_weak_motion_support(self) -> None:
        first_video = {
            "schema_version": "video_temporal_v1",
            "valid": True,
            "confidence": 0.75,
            "key_moments": {"T_takeoff_sec": 1.60, "A_air_sec": 1.90, "L_landing_sec": 2.133},
            "quality_flags": ["video_temporal_fallback_recommended"],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.70,
            "key_moments": {"T_takeoff_sec": 2.90, "A_air_sec": 3.30, "L_landing_sec": 3.65},
            "quality_flags": [
                "video_temporal_quality_retry",
                "video_temporal_not_high_confidence",
                "video_temporal_fallback_recommended",
            ],
            "validation": {
                "valid": False,
                "errors": [],
                "warnings": ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"],
            },
        }
        first_resolved = {
            "source": "video_ai_refined",
            "confidence": 0.75,
            "quality_flags": [
                "video_temporal_resolver_advisory_fallback_overridden",
                "semantic_keyframe_refinement_phase_rejected",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 1.60, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 1.90, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 2.133, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_ai": first_video,
        }
        retry_resolved = {
            "source": "blended",
            "confidence": 0.70,
            "quality_flags": [
                "video_temporal_resolver_video_fallback_recommended",
                "video_temporal_resolver_advisory_fallback_overridden",
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_resolver_moderate_confidence_tal_used",
                "video_temporal_resolver_video_validation_not_clean",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 2.82,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.70,
                    "refinement_method": "local_motion_peak",
                    "refinement_motion_score": 0.0165,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 3.30,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.70,
                    "refinement_method": "apex_preserved",
                    "refinement_motion_score": None,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 3.717,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.60,
                    "refinement_method": "local_motion_peak",
                    "refinement_motion_score": 0.0125,
                },
            ],
            "video_ai": retry_video,
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=first_video,
            resolved_keyframes=first_resolved,
            quality_flags=[*first_video["quality_flags"], *first_resolved["quality_flags"]],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=retry_resolved["selected"],
            quality_flags=[*retry_video["quality_flags"], *retry_resolved["quality_flags"]],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "scores": [
                0.0,
                0.0509,
                0.0577,
                0.0414,
                0.0563,
                0.0451,
                0.0427,
                0.0415,
                0.0317,
                0.035,
                0.0304,
                0.0309,
                0.0289,
                0.0266,
                0.0234,
                0.0301,
                0.0208,
                0.021,
                0.0296,
                0.0312,
                0.0324,
                0.0351,
                0.0371,
                0.0355,
                0.0196,
                0.0318,
                0.0315,
                0.0239,
                0.0274,
                0.0268,
                0.0267,
                0.0236,
                0.0113,
                0.0193,
                0.0329,
                0.0313,
                0.0299,
                0.0284,
                0.0224,
                0.0233,
                0.0133,
                0.019,
                0.0186,
                0.0164,
                0.018,
                0.0233,
                0.0229,
                0.0226,
                0.0146,
                0.021,
                0.018,
                0.0205,
                0.019,
                0.0147,
                0.0129,
                0.011,
                0.0081,
                0.0185,
                0.0147,
                0.0134,
                0.0139,
                0.0129,
                0.0135,
                0.0116,
                0.0066,
                0.0137,
                0.0108,
                0.0157,
                0.0129,
                0.0134,
                0.0192,
                0.0153,
                0.0152,
                0.0225,
                0.0162,
                0.0165,
                0.015,
                0.0131,
                0.0154,
                0.0144,
                0.001,
                0.013,
                0.0153,
                0.0176,
                0.0151,
                0.0169,
                0.0145,
                0.0161,
                0.0104,
                0.0145,
                0.0157,
                0.0124,
                0.0172,
                0.0151,
                0.0192,
                0.0156,
                0.0083,
                0.0147,
                0.0147,
                0.0109,
                0.0203,
                0.0301,
                0.0178,
                0.0815,
                0.0609,
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=6.568, ai_clip_payload=lambda: {"duration_sec": 6.568})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(0.0, 6.568, 0.0, 6.568, 16.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores=motion_scores,
                        analysis_profile="jump",
                    )

        self.assertIs(updated, result)
        self.assertEqual(updated.resolved_keyframes["selected"][0]["timestamp"], 1.60)
        self.assertIn("video_temporal_quality_retry_low_confidence_late_shift_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_used", updated.resolved_keyframes["quality_flags"])

    async def test_quality_retry_rejects_early_drift_when_original_semantic_frames_are_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.7 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.15, "L_landing_sec": 7.55},
                "quality_flags": ["video_temporal_resolver_advisory_fallback_overridden"],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.90,
                "key_moments": {"T_takeoff_sec": 6.50, "A_air_sec": 6.90, "L_landing_sec": 7.30},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            first_resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_advisory_fallback_overridden"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.15, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.55, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.50, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.90, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.30, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(side_effect=[(first_resolved["selected"], []), (retry_resolved["selected"], [])]),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(side_effect=fake_extract),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertEqual(result.resolved_keyframes["selected"][0]["timestamp"], 6.75)
        self.assertIn("video_temporal_quality_retry_early_drift_rejected", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        self.assertGreater(
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["retry"],
            result.resolved_keyframes["video_temporal_quality_retry_scores"]["original"],
        )

    async def test_quality_retry_rejects_early_tal_before_later_strong_motion(self) -> None:
        first_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.40,
            "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            "quality_flags": ["video_temporal_low_confidence"],
            "validation": {"valid": False, "errors": [], "warnings": ["manual_review"]},
        }
        retry_video = {
            "schema_version": "video_temporal_v1",
            "valid": False,
            "confidence": 0.75,
            "key_moments": {"T_takeoff_sec": 6.25, "A_air_sec": 6.85, "L_landing_sec": 7.25},
            "quality_flags": [
                "video_temporal_quality_retry",
                "video_temporal_low_confidence",
                "video_temporal_not_high_confidence",
                "video_temporal_fallback_recommended",
            ],
            "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_fallback_recommended"]},
        }
        first_resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.40,
            "quality_flags": [
                "video_temporal_resolver_low_video_confidence",
                "video_temporal_resolver_partial_skeleton_fallback",
            ],
            "selected": [{"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"}],
            "video_ai": first_video,
        }
        retry_resolved = {
            "source": "blended",
            "confidence": 0.75,
            "quality_flags": [
                "video_temporal_resolver_advisory_fallback_overridden",
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_resolver_moderate_confidence_tal_used",
            ],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 6.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 6.85, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 7.37, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
            "video_ai": retry_video,
        }
        result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=first_video,
            resolved_keyframes=first_resolved,
            quality_flags=[*first_video["quality_flags"], *first_resolved["quality_flags"]],
            used_semantic_frames=False,
            has_semantic_moments=True,
        )
        retry_result = SemanticKeyframePipelineResult(
            ai_clip=None,
            video_temporal=retry_video,
            resolved_keyframes=retry_resolved,
            semantic_frames=[Path("semantic_0001.jpg"), Path("semantic_0002.jpg"), Path("semantic_0003.jpg")],
            semantic_records=retry_resolved["selected"],
            quality_flags=[*retry_video["quality_flags"], *retry_resolved["quality_flags"]],
            used_semantic_frames=True,
            has_semantic_moments=True,
        )
        motion_scores = {
            "frame_rate": 16,
            "window_start": 4.65,
            "scores": [0.04] * 47 + [0.103, 0.193, 0.226, 0.217, 0.21, 0.122, 0.25, 0.23, 0.129] + [0.05] * 18,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            retry_future = asyncio.get_running_loop().create_future()
            retry_future.set_result(retry_video)
            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=9.568, ai_clip_payload=lambda: {"duration_sec": 4.6})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    updated = await retry_video_temporal_if_needed(
                        result=result,
                        video_path=root / "source.mp4",
                        work_dir=root,
                        semantic_frames_dir=root / "semantic",
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        action_type="jump",
                        action_subtype=None,
                        motion_scores=motion_scores,
                        analysis_profile="jump",
                    )

        self.assertIs(updated, result)
        self.assertFalse(updated.used_semantic_frames)
        self.assertEqual(updated.resolved_keyframes["selected"][0]["timestamp"], 8.025)
        self.assertIn("video_temporal_quality_retry_later_motion_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_quality_retry_rejected", updated.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_used", updated.resolved_keyframes["quality_flags"])

    async def test_core_foreground_occlusion_rejects_semantic_frames_when_repair_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            for index in range(1, 4):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frame")
                semantic_paths.append(path)

            video_temporal = {"schema_version": "video_temporal_v1", "confidence": 0.85, "quality_flags": []}
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.15, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.45, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.75, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": video_temporal,
            }
            records = [dict(item) for item in resolved["selected"]]
            visible = [{"bbox": {"x": 0.40, "y": 0.30, "width": 0.07, "height": 0.18}, "confidence": 0.8, "area": 0.0126}]
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(records, []))):
                    with patch(
                        "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                        AsyncMock(return_value=(semantic_paths, records)),
                    ):
                        with patch(
                            "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                            side_effect=[visible, visible, occluded, *([occluded] * 30)],
                        ):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                video_duration_sec=9.568,
                            )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_after_visibility_check", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["semantic_visibility"]["status"], "foreground_person_occluded")

    async def test_pipeline_uses_coherent_fallback_tal_after_resolver_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")

            with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=_validated_coherent_fallback_jump_video(),
                        motion_scores=_glide_out_motion_scores(),
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 6.739, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=9.568,
                    )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual(len(result.semantic_frames), 6)
        self.assertIn("video_temporal_resolver_advisory_fallback_overridden", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_used", result.resolved_keyframes["quality_flags"])
        core = [item for item in result.resolved_keyframes["selected"] if item["phase_code"] in {"takeoff", "air", "landing"}]
        self.assertEqual([item["phase_code"] for item in core], ["takeoff", "air", "landing"])

    async def test_pipeline_keeps_late_motion_conflict_as_sampled_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")

            result = await resolve_semantic_keyframe_pipeline(
                video_path=video_path,
                work_dir=root,
                semantic_frames_dir=root / "semantic_frames",
                video_temporal=_validated_late_motion_conflict_jump_video(),
                motion_scores=_glide_out_motion_scores(),
                sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 6.739, 30.0, False),
                analysis_profile="jump",
                video_duration_sec=9.568,
            )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "sampled_frames")
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", result.resolved_keyframes["quality_flags"])

    async def test_pipeline_rejects_semantic_tal_when_tracker_final_loss_has_bounded_motion_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.8,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.703, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 7.0, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0003", "timestamp": 7.583, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {"confidence": 0.8, "quality_flags": [], "key_moments": {"T_takeoff_sec": 6.703, "A_air_sec": 7.0, "L_landing_sec": 7.583}},
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                    ],
                    "T": {"frame_id": "frame_0011", "timestamp": 6.5, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {"frame_id": "frame_0012", "timestamp": 7.0, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "L": {"frame_id": "frame_0013", "timestamp": 7.6, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                result = await resolve_semantic_keyframe_pipeline(
                    video_path=video_path,
                    work_dir=root,
                    semantic_frames_dir=root / "semantic_frames",
                    video_temporal=resolved["video_ai"],
                    motion_scores={"selected": []},
                    sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                    analysis_profile="jump",
                    bio_data=bio_data,
                    video_duration_sec=11.25,
                )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_tracker_final_loss_motion_fallback", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])

    async def test_pipeline_keeps_semantic_tal_when_tracker_final_loss_motion_fallback_spans_tail_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.8,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 9.0, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0003", "timestamp": 10.0, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {"confidence": 0.8, "quality_flags": [], "key_moments": {"T_takeoff_sec": 8.0, "A_air_sec": 9.0, "L_landing_sec": 10.0}},
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                    ],
                    "T": {"frame_id": "frame_0003", "timestamp": 0.438, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {"frame_id": "frame_0013", "timestamp": 2.938, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "L": {"frame_id": "frame_0032", "timestamp": 11.25, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(resolved["selected"], []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=11.25,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_motion_fallback", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_tracker_final_loss_motion_fallback_ignored", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            result.resolved_keyframes["semantic_tracker_final_loss_motion_fallback"]["decision"],
            "ignored_unbounded_motion_fallback",
        )

    async def test_pipeline_rejects_semantic_tal_outside_reliable_pose_bound_after_tracker_final_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.5, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                    {"frame_id": "semantic_0002", "timestamp": 6.2, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0003", "timestamp": 6.7, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                ],
                "video_ai": {"confidence": 0.85, "quality_flags": [], "key_moments": {"T_takeoff_sec": 5.5, "A_air_sec": 6.2, "L_landing_sec": 6.7}},
            }
            refined = [
                {**resolved["selected"][0], "timestamp": 5.587, "pre_refine_timestamp": 5.5, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0529},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0520},
            ]
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 4.1},
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 2.875,
                        "confidence": 0.54,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.42},
                    },
                    "A": {
                        "frame_id": "frame_0013",
                        "timestamp": 2.938,
                        "confidence": 0.54,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.38},
                    },
                    "L": {
                        "frame_id": "frame_0014",
                        "timestamp": 3.0,
                        "confidence": 0.504,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.35},
                    },
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=11.25,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_tracker_final_loss_reliable_pose_bounds"]
        self.assertEqual(diagnostic["bounds"]["end_timestamp"], 4.1)
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["T", "A", "L"])

    async def test_pipeline_rejects_semantic_tal_shifted_from_bounded_motion_fallback_after_tracker_final_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.65,
                "quality_flags": [
                    "video_temporal_fallback_recommended",
                    "video_temporal_resolver_video_fallback_recommended",
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_moderate_confidence_tal_used",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 3.553, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.65},
                    {"frame_id": "semantic_0002", "timestamp": 3.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0003", "timestamp": 4.1, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.65},
                ],
                "video_ai": {
                    "confidence": 0.65,
                    "fallback_recommendation": "manual_review",
                    "quality_flags": ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"],
                    "key_moments": {"T_takeoff_sec": 3.6, "A_air_sec": 3.8, "L_landing_sec": 4.0},
                },
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                    "bio_key_frames_not_synced_tracker_final_loss_motion_fallback",
                    "tal_candidate_unreliable_tracker_final_loss",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 4.1},
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 2.875,
                        "confidence": 0.54,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.42},
                    },
                    "A": {
                        "frame_id": "frame_0013",
                        "timestamp": 2.938,
                        "confidence": 0.54,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.38},
                    },
                    "L": {
                        "frame_id": "frame_0014",
                        "timestamp": 3.0,
                        "confidence": 0.504,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.35},
                    },
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                result = await resolve_semantic_keyframe_pipeline(
                    video_path=video_path,
                    work_dir=root,
                    semantic_frames_dir=root / "semantic_frames",
                    video_temporal=resolved["video_ai"],
                    motion_scores={"selected": []},
                    sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                    analysis_profile="jump",
                    bio_data=bio_data,
                    video_duration_sec=11.25,
                )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_tracker_final_loss_motion_fallback", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            [(item["phase_code"], item["timestamp"], item["frame_id"]) for item in result.resolved_keyframes["selected"]],
            [("takeoff", 2.875, "frame_0012"), ("air", 2.938, "frame_0013"), ("landing", 3.0, "frame_0014")],
        )
        self.assertEqual(
            [item["timestamp"] for item in result.resolved_keyframes["rejected_semantic_selected"][:3]],
            [3.553, 3.8, 4.1],
        )
        diagnostic = result.resolved_keyframes["semantic_tracker_final_loss_motion_fallback"]
        self.assertEqual(diagnostic["decision"], "rejected_bounded_motion_fallback_candidate_conflict")
        self.assertEqual(diagnostic["bounds"]["end_timestamp"], 4.1)
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["T", "A", "L"])

    async def test_pipeline_rejects_low_visibility_semantic_drift_from_bounded_motion_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.65,
                "quality_flags": [
                    "distant_view",
                    "partial_occlusion",
                    "low_detail",
                    "video_temporal_not_high_confidence",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_moderate_confidence_tal_used",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 2.92, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.65},
                    {"frame_id": "semantic_0002", "timestamp": 3.4, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0003", "timestamp": 3.567, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.65},
                ],
                "video_ai": {
                    "confidence": 0.65,
                    "quality_flags": ["distant_view", "partial_occlusion", "low_detail", "video_temporal_not_high_confidence"],
                    "key_moments": {"T_takeoff_sec": 2.92, "A_air_sec": 3.4, "L_landing_sec": 3.567},
                },
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_transient_loss_recovered",
                    "person_tracker_relock_rejected",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 4.1},
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 2.875,
                        "confidence": 0.54,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.42},
                    },
                    "A": {
                        "frame_id": "frame_0013",
                        "timestamp": 2.938,
                        "confidence": 0.54,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.38},
                    },
                    "L": {
                        "frame_id": "frame_0014",
                        "timestamp": 3.0,
                        "confidence": 0.504,
                        "warnings": ["keyframe_candidates_motion_fallback"],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.35},
                    },
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                result = await resolve_semantic_keyframe_pipeline(
                    video_path=video_path,
                    work_dir=root,
                    semantic_frames_dir=root / "semantic_frames",
                    video_temporal=resolved["video_ai"],
                    motion_scores={"selected": []},
                    sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                    analysis_profile="jump",
                    bio_data=bio_data,
                    video_duration_sec=11.25,
                )

        self.assertFalse(result.used_semantic_frames)
        self.assertIn(
            "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            [(item["phase_code"], item["timestamp"], item["frame_id"]) for item in result.resolved_keyframes["selected"]],
            [("takeoff", 2.875, "frame_0012"), ("air", 2.938, "frame_0013"), ("landing", 3.0, "frame_0014")],
        )
        diagnostic = result.resolved_keyframes["semantic_low_visibility_bounded_motion_fallback_drift"]
        self.assertEqual(diagnostic["decision"], "rejected_low_visibility_bounded_motion_fallback_drift")
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["A", "L"])

    async def test_pipeline_keeps_current_video_tal_over_low_visibility_motion_fallback_without_pose_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.6,
                "quality_flags": [
                    "distance",
                    "partial_occlusion",
                    "video_temporal_not_high_confidence",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_moderate_confidence_tal_used",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.3, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0002", "timestamp": 6.6, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0003", "timestamp": 6.9, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.6},
                ],
                "video_ai": {
                    "confidence": 0.6,
                    "quality_flags": ["distance", "partial_occlusion", "video_temporal_not_high_confidence"],
                    "key_moments": {"T_takeoff_sec": 6.3, "A_air_sec": 6.6, "L_landing_sec": 6.9},
                },
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_transient_loss_recovered",
                    "person_tracker_relock_rejected",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_tiny_target_full_frame_motion_risk",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_motion_fallback_foreground_motion_risk",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 3.188, "end_timestamp": 5.038},
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 3.188,
                        "confidence": 0.54,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "t_pose_signal_insufficient",
                            "tal_candidate_motion_fallback_foreground_motion_risk",
                        ],
                        "evidence": {"motion_fallback": True, "motion_score": 0.0999, "visibility_score": 0.0},
                    },
                    "A": {
                        "frame_id": "frame_0016",
                        "timestamp": 3.438,
                        "confidence": 0.54,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "a_pose_signal_insufficient",
                            "tal_candidate_motion_fallback_foreground_motion_risk",
                        ],
                        "evidence": {"motion_fallback": True, "motion_score": 0.0998, "visibility_score": 0.0},
                    },
                    "L": {
                        "frame_id": "frame_0020",
                        "timestamp": 3.688,
                        "confidence": 0.503,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "l_pose_signal_insufficient",
                            "tal_candidate_motion_fallback_foreground_motion_risk",
                        ],
                        "evidence": {"motion_fallback": True, "motion_score": 0.077, "visibility_score": 0.0},
                    },
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(resolved["selected"], [])),
                ):
                    with patch(
                        "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                        AsyncMock(side_effect=_fake_extract_precise_frames),
                    ):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=root / "semantic_frames",
                            video_temporal=resolved["video_ai"],
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 10.235, 0.0, 10.235, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=10.235,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertNotIn(
            "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertIn(
            "semantic_keyframes_low_visibility_bounded_motion_fallback_ignored_no_pose_support",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_low_visibility_bounded_motion_fallback_drift"]["decision"],
            "ignored_low_visibility_bounded_motion_fallback_without_pose_support",
        )
        self.assertEqual(
            [(item["phase_code"], item["timestamp"]) for item in result.resolved_keyframes["selected"]],
            [("takeoff", 6.3), ("air", 6.6), ("landing", 6.9)],
        )

    async def test_pipeline_rejects_high_confidence_semantic_tal_when_bounded_motion_fallback_core_edges_disagree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.9,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_skeleton_candidate_not_used",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 2.65, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.88},
                    {"frame_id": "semantic_0002", "timestamp": 3.0, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0003", "timestamp": 3.32, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                ],
                "video_ai": {
                    "valid": True,
                    "confidence": 0.9,
                    "fallback_recommendation": "use_video_timestamps",
                    "key_moments": {"T_takeoff_sec": 2.65, "A_air_sec": 3.0, "L_landing_sec": 3.3},
                },
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                    "bio_key_frames_not_synced_tracker_final_loss_motion_fallback",
                    "tal_candidate_unreliable_tracker_final_loss",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 4.1},
                    "T": {"frame_id": "frame_0012", "timestamp": 2.875, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {"frame_id": "frame_0013", "timestamp": 2.938, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "L": {"frame_id": "frame_0014", "timestamp": 3.0, "confidence": 0.504, "warnings": ["keyframe_candidates_motion_fallback"]},
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                result = await resolve_semantic_keyframe_pipeline(
                    video_path=video_path,
                    work_dir=root,
                    semantic_frames_dir=root / "semantic_frames",
                    video_temporal=resolved["video_ai"],
                    motion_scores={"selected": []},
                    sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                    analysis_profile="jump",
                    bio_data=bio_data,
                    video_duration_sec=11.25,
                )

        self.assertFalse(result.used_semantic_frames)
        self.assertIn("semantic_keyframes_unreliable_tracker_final_loss_motion_fallback", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            [(item["phase_code"], item["timestamp"], item["frame_id"]) for item in result.resolved_keyframes["selected"]],
            [("takeoff", 2.875, "frame_0012"), ("air", 2.938, "frame_0013"), ("landing", 3.0, "frame_0014")],
        )
        self.assertEqual(
            [item["timestamp"] for item in result.resolved_keyframes["rejected_semantic_selected"][:3]],
            [2.65, 3.0, 3.32],
        )
        diagnostic = result.resolved_keyframes["semantic_tracker_final_loss_motion_fallback"]
        self.assertEqual(diagnostic["decision"], "rejected_bounded_motion_fallback_candidate_conflict")
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["T", "L"])

    async def test_pipeline_keeps_semantic_tal_inside_reliable_pose_bound_after_tracker_final_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 3.0, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                    {"frame_id": "semantic_0002", "timestamp": 3.3, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0003", "timestamp": 3.6, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                ],
                "video_ai": {"confidence": 0.85, "quality_flags": [], "key_moments": {"T_takeoff_sec": 3.0, "A_air_sec": 3.3, "L_landing_sec": 3.6}},
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 4.1},
                    "T": {"frame_id": "frame_0012", "timestamp": 2.9, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {"frame_id": "frame_0013", "timestamp": 3.2, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "L": {"frame_id": "frame_0014", "timestamp": 3.6, "confidence": 0.54, "warnings": ["keyframe_candidates_motion_fallback"]},
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(resolved["selected"], []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=11.25,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose", result.resolved_keyframes["quality_flags"])

    async def test_pipeline_rejects_weak_semantic_motion_when_tracker_ends_unrecovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_fallback_recommended",
                    "video_temporal_resolver_video_fallback_recommended",
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "video_temporal_resolver_coherent_tal_used",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 4.82, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0002", "timestamp": 5.2, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.80},
                    {"frame_id": "semantic_0003", "timestamp": 5.867, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
                ],
                "video_ai": {"confidence": 0.85, "quality_flags": [], "key_moments": {"T_takeoff_sec": 4.82, "A_air_sec": 5.2, "L_landing_sec": 5.867}},
            }
            refined = [
                {**resolved["selected"][0], "pre_refine_timestamp": 4.7, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0192, "refinement_delta_sec": 0.12},
                {**resolved["selected"][1], "pre_refine_timestamp": 5.2, "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "pre_refine_timestamp": 5.6, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0160, "refinement_delta_sec": 0.267},
            ]
            bio_data = {
                "quality_flags": [
                    "target_lock_zoomed_multiperson_manual_review",
                    "person_tracker_target_lost",
                    "person_tracker_detector_relocked",
                    "person_tracker_continuity_rejected",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0023", "timestamp": 8.688, "confidence": 0.365},
                    "A": {"frame_id": "frame_0024", "timestamp": 8.75, "confidence": 0.447},
                    "L": {"frame_id": "frame_0025", "timestamp": 9.188, "confidence": 0.463},
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 11.25, 0.0, 11.25, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=11.25,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_tracker_final_loss_weak_semantic_motion"]
        self.assertEqual([item["key"] for item in diagnostic["weak_candidate_conflicts"]], ["T", "A", "L"])

    async def test_retry_keeps_nearby_semantic_tal_when_candidate_landing_geometry_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            original = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal={"confidence": 0.85, "quality_flags": ["video_temporal_fallback_recommended"]},
                resolved_keyframes={
                    "source": "blended",
                    "confidence": 0.85,
                    "quality_flags": [
                        "video_temporal_resolver_coherent_tal_used",
                        "semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion",
                    ],
                    "selected": [
                        {"frame_id": "semantic_0001", "timestamp": 11.42, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                        {"frame_id": "semantic_0002", "timestamp": 12.5, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.80},
                        {"frame_id": "semantic_0003", "timestamp": 13.3, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
                    ],
                },
                quality_flags=["semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion"],
                used_semantic_frames=False,
                has_semantic_moments=True,
            )
            retry_video_temporal = {
                "confidence": 0.80,
                "quality_flags": ["video_temporal_quality_retry", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.6, "A_air_sec": 4.0, "L_landing_sec": 4.5},
            }
            retry_resolved = {
                "source": "blended",
                "confidence": 0.80,
                "quality_flags": [
                    "video_temporal_quality_retry",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_video_fallback_recommended",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 3.6,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "confidence": 0.8,
                        "refinement_motion_score": 0.031,
                    },
                    {"frame_id": "semantic_0002", "timestamp": 4.0, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.5,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.8,
                        "refinement_motion_score": 0.032,
                    },
                ],
            }
            retry_frame_paths = [root / "retry_1.jpg", root / "retry_2.jpg", root / "retry_3.jpg"]
            for path in retry_frame_paths:
                path.write_bytes(b"fake-jpeg")
            retry_result = SemanticKeyframePipelineResult(
                ai_clip=None,
                video_temporal=retry_video_temporal,
                resolved_keyframes=retry_resolved,
                semantic_frames=retry_frame_paths,
                semantic_records=list(retry_resolved["selected"]),
                quality_flags=retry_resolved["quality_flags"],
                used_semantic_frames=True,
                has_semantic_moments=True,
            )
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_pending",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_landing_geometry_absent",
                        "tal_candidate_weak_geometry",
                    ],
                    "T": {"frame_id": "frame_0009", "timestamp": 0.562, "confidence": 0.60},
                    "A": {"frame_id": "frame_0010", "timestamp": 1.125, "confidence": 0.486},
                    "L": {"frame_id": "frame_0012", "timestamp": 4.5, "confidence": 0.35},
                },
            }
            retry_future: asyncio.Future[dict[str, object]] = asyncio.Future()
            retry_future.set_result(retry_video_temporal)

            with patch(
                "app.services.semantic_keyframe_pipeline.start_video_temporal_task",
                AsyncMock(return_value=SimpleNamespace(task=retry_future, source_duration_sec=17.8, ai_clip_payload=lambda: {"duration_sec": 17.8})),
            ):
                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframe_pipeline", AsyncMock(return_value=retry_result)):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await retry_video_temporal_if_needed(
                                result=original,
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                sampling_metadata=VideoSamplingMetadata(0.0, 17.8, 0.0, 17.8, 16.0, 30.0, False),
                                action_type="jump",
                                action_subtype=None,
                                motion_scores={"selected": []},
                                analysis_profile="jump",
                                bio_data=bio_data,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion", result.resolved_keyframes["quality_flags"])
        core_times = {
            item["key_moment"]: item["timestamp"]
            for item in result.resolved_keyframes["selected"]
            if item.get("key_moment")
        }
        self.assertEqual(core_times["T_takeoff_sec"], 3.6)
        self.assertEqual(core_times["A_air_sec"], 4.0)
        self.assertEqual(core_times["L_landing_sec"], 4.5)

    async def test_pipeline_ignores_tracker_final_loss_weak_motion_for_retry_near_absent_landing_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.80,
                "quality_flags": [
                    "video_temporal_quality_retry",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_video_fallback_recommended",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 3.6,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "confidence": 0.8,
                        "refinement_motion_score": 0.031,
                    },
                    {"frame_id": "semantic_0002", "timestamp": 4.0, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.5,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.8,
                        "refinement_motion_score": 0.032,
                    },
                ],
                "video_ai": {
                    "confidence": 0.80,
                    "quality_flags": ["video_temporal_quality_retry", "video_temporal_fallback_recommended"],
                    "key_moments": {"T_takeoff_sec": 3.6, "A_air_sec": 4.0, "L_landing_sec": 4.5},
                },
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_pending",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_landing_geometry_absent",
                        "tal_candidate_weak_geometry",
                    ],
                    "T": {"frame_id": "frame_0009", "timestamp": 0.562, "confidence": 0.60},
                    "A": {"frame_id": "frame_0010", "timestamp": 1.125, "confidence": 0.486},
                    "L": {"frame_id": "frame_0012", "timestamp": 4.5, "confidence": 0.35},
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(resolved["selected"], []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 17.8, 0.0, 17.8, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=17.8,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframes_tracker_final_loss_weak_semantic_motion_ignored", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_tracker_final_loss_weak_semantic_motion"]
        self.assertEqual(diagnostic["decision"], "ignored_retry_absent_landing_geometry_candidate")
        self.assertEqual(diagnostic["landing_delta_sec"], 0.0)

    async def test_pipeline_ignores_absent_landing_retry_with_borderline_landing_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.80,
                "quality_flags": [
                    "video_temporal_quality_retry",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_video_fallback_recommended",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 3.2,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "confidence": 0.85,
                    },
                    {"frame_id": "semantic_0002", "timestamp": 3.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.80},
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.4,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.85,
                    },
                ],
                "video_ai": {
                    "confidence": 0.80,
                    "quality_flags": ["video_temporal_quality_retry", "video_temporal_fallback_recommended"],
                    "key_moments": {"T_takeoff_sec": 3.35, "A_air_sec": 3.75, "L_landing_sec": 4.15},
                },
            }
            refined = [
                {
                    **resolved["selected"][0],
                    "timestamp": 3.187,
                    "pre_refine_timestamp": 3.2,
                    "refinement_method": "local_motion_peak",
                    "refinement_motion_score": 0.0282,
                    "refinement_delta_sec": -0.013,
                },
                {
                    **resolved["selected"][1],
                    "timestamp": 3.8,
                    "pre_refine_timestamp": 3.8,
                    "refinement_method": "apex_preserved",
                    "refinement_motion_score": None,
                    "refinement_delta_sec": 0.0,
                },
                {
                    **resolved["selected"][2],
                    "timestamp": 4.667,
                    "pre_refine_timestamp": 4.4,
                    "refinement_method": "local_motion_peak",
                    "refinement_motion_score": 0.0359,
                    "refinement_delta_sec": 0.267,
                },
            ]
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_pending",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_landing_geometry_absent",
                        "tal_candidate_weak_geometry",
                    ],
                    "T": {"frame_id": "frame_0009", "timestamp": 0.562, "confidence": 0.60},
                    "A": {"frame_id": "frame_0010", "timestamp": 1.125, "confidence": 0.486},
                    "L": {"frame_id": "frame_0012", "timestamp": 2.25, "confidence": 0.35},
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 17.8, 0.0, 17.8, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=17.8,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_weak_semantic_motion", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_tracker_final_loss_weak_semantic_motion"]
        self.assertEqual(diagnostic["decision"], "ignored_retry_absent_landing_geometry_candidate")
        self.assertEqual(diagnostic["refinement_motion_scores"]["L"], 0.0359)

    async def test_pipeline_rejects_weak_refinement_semantic_tal_when_late_vs_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.80,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 3.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 4.3, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                    {"frame_id": "semantic_0003", "timestamp": 4.8, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {"confidence": 0.80, "quality_flags": [], "key_moments": {"T_takeoff_sec": 3.8, "A_air_sec": 4.3, "L_landing_sec": 4.8}},
            }
            refined = [
                {**resolved["selected"][0], "timestamp": 3.653, "pre_refine_timestamp": 3.8, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0115, "refinement_delta_sec": -0.147},
                {**resolved["selected"][1], "pre_refine_timestamp": 4.3, "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "timestamp": 4.533, "pre_refine_timestamp": 4.8, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0184, "refinement_delta_sec": -0.267},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_tail_motion_window_rejected",
                        "tal_candidate_skeleton_drifted_after_takeoff",
                        "keyframe_candidates_motion_fallback",
                    ],
                    "T": {"frame_id": "frame_0011", "timestamp": 1.062, "confidence": 0.572, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {"frame_id": "frame_0013", "timestamp": 1.312, "confidence": 0.500, "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"]},
                    "L": {"frame_id": "frame_0017", "timestamp": 1.875, "confidence": 0.486, "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"]},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 6.5, 0.0, 6.5, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=6.5,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_weak_refinement_late_candidate_conflict"]
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["T", "A", "L"])

    async def test_pipeline_keeps_weak_refinement_semantic_tal_when_candidates_are_late_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 1.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0002", "timestamp": 2.1, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.80},
                    {"frame_id": "semantic_0003", "timestamp": 2.4, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
                ],
                "video_ai": {"confidence": 0.85, "quality_flags": [], "key_moments": {"T_takeoff_sec": 1.8, "A_air_sec": 2.1, "L_landing_sec": 2.4}},
            }
            refined = [
                {**resolved["selected"][0], "timestamp": 1.887, "pre_refine_timestamp": 1.8, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0164, "refinement_delta_sec": 0.087},
                {**resolved["selected"][1], "pre_refine_timestamp": 2.1, "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "timestamp": 2.32, "pre_refine_timestamp": 2.4, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0133, "refinement_delta_sec": -0.08},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_tail_motion_window_rejected"],
                    "T": {"frame_id": "frame_0029", "timestamp": 5.250, "confidence": 0.593, "warnings": ["knee_extension_weak"]},
                    "A": {"frame_id": "frame_0031", "timestamp": 5.750, "confidence": 0.564, "warnings": ["apex_local_minimum_not_clear"]},
                    "L": {"frame_id": "frame_0032", "timestamp": 5.812, "confidence": 0.447, "warnings": ["ankle_return_weak"]},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 6.5, 0.0, 6.5, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=6.5,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertNotIn("semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict", result.resolved_keyframes["quality_flags"])

    async def test_pipeline_rejects_semantic_tal_when_candidate_conflict_is_large_in_either_direction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.80,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 4.2, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0002", "timestamp": 4.6, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0003", "timestamp": 4.953, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.7},
                ],
                "video_ai": {"confidence": 0.80, "quality_flags": [], "key_moments": {"T_takeoff_sec": 4.2, "A_air_sec": 4.6, "L_landing_sec": 4.953}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.021, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0206, "refinement_delta_sec": 0.053},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_tail_motion_window_rejected"],
                    "T": {"frame_id": "frame_0019", "timestamp": 5.0, "confidence": 0.547},
                    "A": {"frame_id": "frame_0022", "timestamp": 7.375, "confidence": 0.510},
                    "L": {"frame_id": "frame_0032", "timestamp": 9.75, "confidence": 0.478, "warnings": ["landing_geometry_weak"]},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 9.835, 0.0, 9.835, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=9.835,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_candidate_tal_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["T", "A", "L"])

    async def test_pipeline_rejects_semantic_tal_when_takeoff_anchor_core_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.80,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.1, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0002", "timestamp": 5.7, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.5},
                    {"frame_id": "semantic_0003", "timestamp": 5.967, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.7},
                ],
                "video_ai": {"confidence": 0.80, "quality_flags": [], "key_moments": {"T_takeoff_sec": 5.1, "A_air_sec": 5.7, "L_landing_sec": 5.967}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_backward_delta_rejected", "refinement_motion_score": 0.0219, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0163, "refinement_delta_sec": 0.033},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_skeleton_drifted_after_takeoff",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "tal_candidate_motion_fallback_low_precision",
                    ],
                    "T": {"frame_id": "frame_0018", "timestamp": 4.875, "confidence": 0.542, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {"frame_id": "frame_0019", "timestamp": 5.0, "confidence": 0.472, "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"]},
                    "L": {"frame_id": "frame_0020", "timestamp": 5.875, "confidence": 0.475, "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"]},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 9.835, 0.0, 9.835, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=9.835,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_candidate_tal_conflict", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertTrue(diagnostic["takeoff_anchor_core_conflict"])
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["A"])

    async def test_pipeline_keeps_semantic_tal_when_takeoff_anchor_fallback_used_unreliable_pose_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.80,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 6.5, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0003", "timestamp": 6.987, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {"confidence": 0.80, "quality_flags": [], "key_moments": {"T_takeoff_sec": 5.8, "A_air_sec": 6.5, "L_landing_sec": 7.0}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.0622, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0587, "refinement_delta_sec": -0.013},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_skeleton_drifted_after_takeoff",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "tal_candidate_motion_fallback_low_precision",
                        "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    ],
                    "motion_fallback_unreliable_pose_records": {
                        "A": {"frame_id": "frame_0011", "tracking_state": "interpolated", "tracker_state": ""},
                        "L": {"frame_id": "frame_0015", "tracking_state": "lost", "tracker_state": "lost_reused"},
                    },
                    "T": {"frame_id": "frame_0010", "timestamp": 1.312, "confidence": 0.617, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {
                        "frame_id": "frame_0011",
                        "timestamp": 1.688,
                        "confidence": 0.47,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "a_pose_signal_drifted",
                            "keyframe_candidates_motion_fallback_unreliable_pose_state",
                        ],
                    },
                    "L": {
                        "frame_id": "frame_0015",
                        "timestamp": 2.562,
                        "confidence": 0.58,
                        "warnings": [
                            "keyframe_candidates_motion_fallback",
                            "l_pose_signal_drifted",
                            "keyframe_candidates_motion_fallback_unreliable_pose_state",
                        ],
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 10.435, 0.0, 10.435, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=10.435,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertNotIn("semantic_keyframes_unreliable_candidate_tal_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_candidate_tal_conflict_ignored_unreliable_pose_fallback", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_unreliable_pose_motion_fallback_candidate")
        self.assertTrue(diagnostic["takeoff_anchor_core_conflict"])
        self.assertEqual(diagnostic["unreliable_pose_records"]["L"]["tracker_state"], "lost_reused")
        ignored_conflicts = diagnostic["ignored_unreliable_pose_fallback_conflicts"]
        self.assertTrue(any(item["key"] == "A" for item in ignored_conflicts))
        self.assertTrue(any(item["key"] == "L" for item in ignored_conflicts))
        self.assertTrue(all(item["candidate_confidence"] <= 0.34 for item in ignored_conflicts))
        self.assertTrue(any(item["candidate_raw_confidence"] > item["candidate_confidence"] for item in ignored_conflicts))

    async def test_pipeline_keeps_semantic_tal_when_takeoff_anchor_fallback_has_low_visibility_weak_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.86,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 2.637, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.86},
                    {"frame_id": "semantic_0002", "timestamp": 2.900, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.82},
                    {"frame_id": "semantic_0003", "timestamp": 3.350, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.84},
                ],
                "video_ai": {
                    "confidence": 0.86,
                    "quality_flags": [],
                    "key_moments": {
                        "T_takeoff_sec": 2.637,
                        "A_air_sec": 2.900,
                        "L_landing_sec": 3.350,
                    },
                },
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.052, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.045, "refinement_delta_sec": 0.0},
            ]
            low_visibility_warning = "tal_candidate_motion_fallback_low_visibility_weak_boundary"
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_skeleton_drifted_after_takeoff",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "keyframe_candidates_motion_fallback_low_visibility_weak_boundary",
                        "tal_candidate_motion_fallback_low_precision",
                        low_visibility_warning,
                    ],
                    "motion_fallback_low_visibility_weak_boundary": {
                        "reason": "takeoff_anchor_low_visibility_motion_only_boundary",
                        "low_visibility_motion_roles": ["A", "L"],
                    },
                    "T": {
                        "frame_id": "frame_0010",
                        "timestamp": 0.625,
                        "confidence": 0.568,
                        "warnings": ["keyframe_candidates_motion_fallback", low_visibility_warning],
                    },
                    "A": {
                        "frame_id": "frame_0014",
                        "timestamp": 0.875,
                        "confidence": 0.34,
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted", low_visibility_warning],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    },
                    "L": {
                        "frame_id": "frame_0017",
                        "timestamp": 1.625,
                        "confidence": 0.34,
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted", low_visibility_warning],
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={
                                    "selected": [
                                        {"timestamp": 0.625, "motion_score": 0.0423},
                                        {"timestamp": 0.875, "motion_score": 0.0346},
                                        {"timestamp": 1.625, "motion_score": 0.0334},
                                        {"timestamp": 2.637, "motion_score": 0.0180},
                                        {"timestamp": 3.350, "motion_score": 0.0200},
                                    ]
                                },
                                sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=8.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertNotIn("semantic_keyframes_unreliable_candidate_tal_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_candidate_tal_conflict_ignored_unreliable_pose_fallback", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_unreliable_pose_motion_fallback_candidate")
        self.assertTrue(diagnostic["takeoff_anchor_core_conflict"])
        ignored_conflicts = diagnostic["ignored_unreliable_pose_fallback_conflicts"]
        self.assertTrue(any(item["key"] == "A" for item in ignored_conflicts))
        self.assertTrue(any(item["key"] == "L" for item in ignored_conflicts))
        self.assertTrue(all(item["candidate_confidence"] <= 0.34 for item in ignored_conflicts))

    async def test_pipeline_keeps_semantic_tal_when_candidate_conflict_has_weak_temporal_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.82,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.22, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 5.70, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0003", "timestamp": 6.33, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {"confidence": 0.82, "quality_flags": [], "key_moments": {"T_takeoff_sec": 5.22, "A_air_sec": 5.7, "L_landing_sec": 6.33}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.05, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.06, "refinement_delta_sec": 0.0},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_takeoff_apex_gap_unreliable",
                        "tal_candidate_weak_geometry",
                        "tal_candidate_landing_geometry_weak",
                    ],
                    "T": {"frame_id": "frame_0017", "timestamp": 6.375, "confidence": 0.65, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                    "A": {"frame_id": "frame_0025", "timestamp": 8.188, "confidence": 0.63, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                    "L": {"frame_id": "frame_0026", "timestamp": 8.25, "confidence": 0.70, "warnings": ["tal_candidate_temporal_geometry_unreliable", "landing_geometry_weak"]},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 10.0, 0.0, 10.0, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=10.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertNotIn("semantic_keyframes_unreliable_candidate_tal_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            result.resolved_keyframes["semantic_candidate_tal_conflict"]["decision"],
            "ignored_weak_temporal_geometry_candidate",
        )

    async def test_pipeline_promotes_distant_full_context_phase_range_over_weak_geometry_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            video_ai = {
                "confidence": 0.6,
                "quality_flags": [
                    "video_temporal_not_high_confidence",
                    "video_temporal_fallback_recommended",
                    "video_temporal_phase_3_low_confidence",
                ],
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Toe Loop",
                    "confidence": 0.8,
                },
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 6.0, "time_end": 7.5, "key_frame_hint": 6.5, "confidence": 0.6},
                    {"phase_code": "air", "time_start": 7.5, "time_end": 8.5, "key_frame_hint": 8.0, "confidence": 0.5},
                    {"phase_code": "landing", "time_start": 8.5, "time_end": 9.5, "key_frame_hint": 9.0, "confidence": 0.6},
                ],
                "key_moments": {"T_takeoff_sec": 6.5, "A_air_sec": 8.0, "L_landing_sec": 9.0},
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.6,
                "quality_flags": [
                    "video_temporal_resolver_video_fallback_recommended",
                    "semantic_keyframes_unreliable_candidate_tal_conflict",
                ],
                "selected": [
                    {"frame_id": "frame_0021", "timestamp": 5.938, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.469},
                    {"frame_id": "frame_0023", "timestamp": 6.062, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.465},
                    {"frame_id": "frame_0025", "timestamp": 6.188, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.43},
                    {"frame_id": "semantic_0001", "timestamp": 6.5, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "selection_reason": "video_phase_range_key_moment", "confidence": 0.6},
                    {"frame_id": "semantic_0002", "timestamp": 8.0, "phase_code": "air", "key_moment": "A_air_sec", "selection_reason": "video_phase_range_key_moment", "confidence": 0.5},
                    {"frame_id": "semantic_0003", "timestamp": 9.233, "phase_code": "landing", "key_moment": "L_landing_sec", "selection_reason": "video_phase_range_key_moment", "confidence": 0.6},
                ],
                "video_ai": video_ai,
            }
            cluster = {"start_timestamp": 5.75, "end_timestamp": 6.25}
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_takeoff_geometry_weak",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_weak_geometry",
                    ],
                    "T": {
                        "frame_id": "frame_0021",
                        "timestamp": 5.938,
                        "confidence": 0.469,
                        "warnings": ["knee_extension_weak", "com_ascent_weak", "takeoff_geometry_weak"],
                        "evidence": {"motion_cluster_window": cluster},
                    },
                    "A": {
                        "frame_id": "frame_0023",
                        "timestamp": 6.062,
                        "confidence": 0.465,
                        "warnings": ["confidence_missing_knee_angle_change", "apex_motion_bounded_unclear_fallback"],
                        "evidence": {"motion_cluster_window": cluster},
                    },
                    "L": {
                        "frame_id": "frame_0025",
                        "timestamp": 6.188,
                        "confidence": 0.43,
                        "warnings": ["ankle_return_weak", "knee_absorption_weak", "landing_geometry_weak"],
                        "evidence": {"motion_cluster_window": cluster},
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=root / "semantic_frames",
                            video_temporal=video_ai,
                            motion_scores={
                                "input_window_mode": "full_context",
                                "input_window_reason": "full_context",
                                "input_window_duration_sec": 11.835,
                                "selected": [
                                    {"frame_id": "frame_0005", "timestamp": 0.875, "motion_score": 0.0359},
                                    {"frame_id": "frame_0020", "timestamp": 5.875, "motion_score": 0.0465},
                                    {"frame_id": "frame_0024", "timestamp": 6.125, "motion_score": 0.0441},
                                    {"frame_id": "semantic_t", "timestamp": 6.5, "motion_score": 0.0208},
                                    {"frame_id": "semantic_l", "timestamp": 9.233, "motion_score": 0.0153},
                                ],
                            },
                            sampling_metadata=VideoSamplingMetadata(0.0, 11.835, 0.0, 11.835, 2.619, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=11.835,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "blended")
        self.assertIn("semantic_keyframes_distant_full_context_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [6.5, 8.0, 9.233])
        diagnostic = result.resolved_keyframes["semantic_distant_full_context_visual_promotion"]
        self.assertEqual(diagnostic["promotion_context"], "weak_geometry_candidate")

    def test_candidate_tal_conflict_ignores_core_gap_compressed_candidates(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.82,
            "quality_flags": [],
            "selected": [
                {"timestamp": 2.60, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 2.95, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.7},
                {"timestamp": 3.20, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": ["tal_candidate_core_gap_compressed"],
                "T": {"timestamp": 1.312, "confidence": 0.62},
                "A": {"timestamp": 1.375, "confidence": 0.60},
                "L": {"timestamp": 1.438, "confidence": 0.64},
            }
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores={"selected": []},
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
            resolved["quality_flags"],
        )
        self.assertEqual(
            resolved["semantic_candidate_tal_conflict"]["decision"],
            "ignored_weak_temporal_geometry_candidate",
        )
        self.assertGreaterEqual(len(resolved["semantic_candidate_tal_conflict"]["conflicts"]), 2)

    def test_candidate_tal_conflict_rejects_semantic_when_late_pose_core_was_reselected(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": [],
            "selected": [
                {"timestamp": 2.9, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 3.4, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 3.8, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_tail_motion_window_rejected",
                    "keyframe_candidates_tail_motion_window_reselected",
                    "keyframe_candidates_late_pose_core_reselected",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_apex_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                ],
                "T": {
                    "timestamp": 4.188,
                    "confidence": 0.34,
                    "evidence": {
                        "motion_score": 0.0148,
                        "motion_cluster_window": {"start_timestamp": 4.188, "end_timestamp": 4.875},
                    },
                    "warnings": ["tal_candidate_late_pose_core_reselected"],
                },
                "A": {
                    "timestamp": 4.812,
                    "confidence": 0.34,
                    "evidence": {
                        "motion_score": 0.0114,
                        "motion_cluster_window": {"start_timestamp": 4.188, "end_timestamp": 4.875},
                    },
                    "warnings": ["tal_candidate_late_pose_core_reselected"],
                },
                "L": {
                    "timestamp": 4.875,
                    "confidence": 0.34,
                    "evidence": {
                        "motion_score": 0.0124,
                        "motion_cluster_window": {"start_timestamp": 4.188, "end_timestamp": 4.875},
                    },
                    "warnings": ["tal_candidate_late_pose_core_reselected"],
                },
            }
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores={
                "selected": [
                    {"timestamp": 0.375, "motion_score": 0.0633},
                    {"timestamp": 2.875, "motion_score": 0.0219},
                    {"timestamp": 3.375, "motion_score": 0.0104},
                    {"timestamp": 3.812, "motion_score": 0.0137},
                    {"timestamp": 4.188, "motion_score": 0.0148},
                    {"timestamp": 4.812, "motion_score": 0.0114},
                    {"timestamp": 4.875, "motion_score": 0.0124},
                    {"timestamp": 7.312, "motion_score": 0.0675},
                ]
            },
        )

        self.assertEqual(flags, ["semantic_keyframes_unreliable_candidate_tal_conflict"])
        self.assertIn("semantic_keyframes_unreliable_candidate_tal_conflict", resolved["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
            resolved["quality_flags"],
        )
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "rejected_late_pose_core_candidate_conflict")
        self.assertEqual(diagnostic["candidate_conflict_evidence"]["conflict_keys"], ["A", "L", "T"])
        self.assertAlmostEqual(
            diagnostic["candidate_conflict_evidence"]["candidate_anchors"]["T"]["timestamp"],
            4.188,
        )

    def test_candidate_tal_conflict_rejects_nearby_semantic_when_late_pose_core_exceeds_tolerance(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": ["video_temporal_quality_retry_used"],
            "selected": [
                {"timestamp": 3.987, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                {"timestamp": 4.5, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 4.733, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_late_pose_core_reselected",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_weak_geometry",
                ],
                "T": {"timestamp": 4.188, "confidence": 0.34, "evidence": {"motion_score": 0.0148}},
                "A": {"timestamp": 4.812, "confidence": 0.34, "evidence": {"motion_score": 0.0114}},
                "L": {"timestamp": 4.875, "confidence": 0.34, "evidence": {"motion_score": 0.0124}},
            }
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores={"selected": []},
        )

        self.assertEqual(flags, ["semantic_keyframes_unreliable_candidate_tal_conflict"])
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "rejected_late_pose_core_candidate_conflict")
        self.assertEqual(diagnostic["candidate_conflict_evidence"]["conflict_keys"], ["A", "L", "T"])

    def test_unreliable_semantic_fallback_rejects_weak_late_pose_core_candidates(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "quality_flags": ["semantic_keyframes_unreliable_candidate_tal_conflict"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.6, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 3.9, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 4.253, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_late_pose_core_reselected",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_apex_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {"frame_id": "frame_0023", "timestamp": 4.188, "confidence": 0.34},
                "A": {"frame_id": "frame_0025", "timestamp": 4.812, "confidence": 0.34},
                "L": {"frame_id": "frame_0026", "timestamp": 4.875, "confidence": 0.34},
            }
        }

        updated = _apply_unreliable_semantic_selected_fallback(
            resolved,
            bio_data,
            analysis_profile="jump",
        )

        self.assertIs(updated, resolved)
        self.assertEqual(updated["source"], "video_ai_refined")
        self.assertEqual([item["timestamp"] for item in updated["selected"]], [3.6, 3.9, 4.253])
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", updated["quality_flags"])
        self.assertNotIn("rejected_semantic_selected", updated)

    def test_unreliable_semantic_fallback_allows_strong_late_pose_core_candidates(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "quality_flags": ["semantic_keyframes_unreliable_candidate_tal_conflict"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 3.6, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                {"frame_id": "semantic_0002", "timestamp": 3.9, "phase_code": "air", "key_moment": "A_air_sec"},
                {"frame_id": "semantic_0003", "timestamp": 4.253, "phase_code": "landing", "key_moment": "L_landing_sec"},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_late_pose_core_reselected",
                    "keyframe_candidates_tail_motion_window_reselected",
                ],
                "T": {"frame_id": "frame_0023", "timestamp": 4.188, "confidence": 0.62},
                "A": {"frame_id": "frame_0025", "timestamp": 4.812, "confidence": 0.58},
                "L": {"frame_id": "frame_0028", "timestamp": 5.125, "confidence": 0.61},
            }
        }

        updated = _apply_unreliable_semantic_selected_fallback(
            resolved,
            bio_data,
            analysis_profile="jump",
        )

        self.assertIs(updated, resolved)
        self.assertEqual(updated["source"], "skeleton_fallback")
        self.assertEqual([item["timestamp"] for item in updated["selected"]], [4.188, 4.812, 5.125])
        self.assertIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", updated["quality_flags"])
        self.assertEqual([item["timestamp"] for item in updated["rejected_semantic_selected"]], [3.6, 3.9, 4.253])

    def test_candidate_tal_conflict_records_motion_evidence_when_weak_candidate_ignored(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.82,
            "quality_flags": [],
            "selected": [
                {"timestamp": 6.50, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 6.85, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 7.15, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_takeoff_apex_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_core_gap_compressed",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {
                    "timestamp": 14.75,
                    "confidence": 0.62,
                    "evidence": {
                        "motion_score": 0.0791,
                        "motion_cluster_window": {"start_timestamp": 14.688, "end_timestamp": 14.938},
                    },
                    "warnings": ["tal_candidate_temporal_geometry_unreliable"],
                },
                "A": {
                    "timestamp": 14.812,
                    "confidence": 0.60,
                    "evidence": {
                        "motion_score": 0.0666,
                        "motion_cluster_window": {"start_timestamp": 14.688, "end_timestamp": 14.938},
                    },
                    "warnings": ["apex_local_minimum_not_clear", "tal_candidate_temporal_geometry_unreliable"],
                },
                "L": {
                    "timestamp": 14.875,
                    "confidence": 0.64,
                    "evidence": {
                        "motion_score": 0.0793,
                        "motion_cluster_window": {"start_timestamp": 14.688, "end_timestamp": 14.938},
                    },
                    "warnings": ["landing_geometry_weak", "tal_candidate_temporal_geometry_unreliable"],
                },
            }
        }
        motion_scores = {
            "selected": [
                {"frame_id": "semantic_t", "timestamp": 6.50, "motion_score": 0.0180},
                {"frame_id": "semantic_a", "timestamp": 6.85, "motion_score": 0.0220},
                {"frame_id": "semantic_l", "timestamp": 7.15, "motion_score": 0.0190},
                {"frame_id": "frame_0028", "timestamp": 14.688, "motion_score": 0.0626},
                {"frame_id": "frame_0029", "timestamp": 14.750, "motion_score": 0.0791},
                {"frame_id": "frame_0030", "timestamp": 14.812, "motion_score": 0.0666},
                {"frame_id": "frame_0031", "timestamp": 14.875, "motion_score": 0.0793},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_compressed_candidate",
            resolved["quality_flags"],
        )
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_compressed_candidate_motion_window_conflict")
        evidence = diagnostic["motion_window_conflict"]["candidate_conflict_evidence"]
        self.assertEqual(evidence["anchor_deltas_sec"], {"T": -8.25, "A": -7.962, "L": -7.725})
        self.assertEqual(evidence["candidate_span_sec"], 0.125)
        self.assertIn("tal_candidate_core_gap_compressed", evidence["untrusted_candidate_reasons"])
        motion_context = evidence["motion_context"]
        self.assertEqual(motion_context["global_peak_timestamp"], 14.875)
        self.assertEqual(motion_context["candidate_window"]["peak_ratio"], 1.0)
        self.assertLess(motion_context["semantic_window"]["peak_ratio"], 0.5)
        self.assertIn(
            "candidate_window_dominant_full_frame_motion_over_semantic_window",
            motion_context["diagnostic_labels"],
        )

    def test_candidate_tal_conflict_ignores_early_weak_geometry_when_main_motion_supports_semantic(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.70,
            "quality_flags": [],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 5.20, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.70},
                {"frame_id": "semantic_0002", "timestamp": 5.70, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.70},
                {"frame_id": "semantic_0003", "timestamp": 6.10, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.70},
            ],
            "video_ai": {
                "confidence": 0.70,
                "quality_flags": [],
                "key_moments": {"T_takeoff_sec": 5.20, "A_air_sec": 5.70, "L_landing_sec": 6.10},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_compressed_weak_motion_window_reselected",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {
                    "frame_id": "frame_0005",
                    "timestamp": 0.875,
                    "confidence": 0.616,
                    "warnings": ["knee_extension_weak", "takeoff_geometry_weak"],
                },
                "A": {
                    "frame_id": "frame_0008",
                    "timestamp": 1.500,
                    "confidence": 0.581,
                    "warnings": ["apex_local_minimum_not_clear"],
                },
                "L": {
                    "frame_id": "frame_0011",
                    "timestamp": 1.875,
                    "confidence": 0.444,
                    "warnings": ["landing_geometry_weak"],
                },
            },
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0005", "timestamp": 0.875, "motion_score": 0.0359},
                {"frame_id": "semantic_t", "timestamp": 5.200, "motion_score": 0.0400},
                {"frame_id": "frame_0020", "timestamp": 5.875, "motion_score": 0.0465},
                {"frame_id": "frame_0024", "timestamp": 6.125, "motion_score": 0.0441},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_tal_conflict_ignored_main_motion_supported_weak_geometry",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_tal_conflict", resolved["quality_flags"])
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(
            diagnostic["decision"],
            "ignored_early_weak_geometry_candidate_main_motion_supports_semantic_tal",
        )
        support = diagnostic["main_motion_support"]
        self.assertEqual(support["shifted_keys"], ["T", "A"])
        self.assertEqual(support["semantic_window"]["peak_motion_score"], 0.0465)
        self.assertEqual(support["candidate_window"]["peak_motion_score"], 0.0359)
        self.assertEqual(support["global_peak_timestamp"], 5.875)

    def test_candidate_motion_window_conflict_ignores_weak_geometry_candidate_with_semantic_support(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.70,
            "quality_flags": [],
            "selected": [
                {"timestamp": 2.12, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 2.50, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 3.00, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.70,
                "quality_flags": [],
                "key_moments": {"T_takeoff_sec": 2.12, "A_air_sec": 2.50, "L_landing_sec": 3.00},
            },
        }
        cluster = {"start_timestamp": 4.75, "end_timestamp": 6.15}
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_weak_geometry",
                ],
                "T": {
                    "timestamp": 4.875,
                    "confidence": 0.58,
                    "evidence": {"motion_score": 0.1153, "motion_cluster_window": cluster},
                    "warnings": ["tal_candidate_temporal_geometry_unreliable"],
                },
                "A": {
                    "timestamp": 4.938,
                    "confidence": 0.49,
                    "evidence": {"motion_score": 0.103, "motion_cluster_window": cluster},
                    "warnings": ["tal_candidate_temporal_geometry_unreliable"],
                },
                "L": {
                    "timestamp": 6.125,
                    "confidence": 0.35,
                    "evidence": {"motion_score": 0.084, "motion_cluster_window": cluster},
                    "warnings": ["landing_geometry_weak", "tal_candidate_temporal_geometry_unreliable"],
                },
            }
        }
        motion_scores = {
            "selected": [
                {"frame_id": "semantic_t", "timestamp": 2.12, "motion_score": 0.0703},
                {"frame_id": "semantic_a", "timestamp": 2.50, "motion_score": 0.0600},
                {"frame_id": "semantic_l", "timestamp": 3.00, "motion_score": 0.0680},
                {"frame_id": "frame_0077", "timestamp": 4.812, "motion_score": 0.1153},
                {"frame_id": "frame_0078", "timestamp": 4.875, "motion_score": 0.1040},
                {"frame_id": "frame_0098", "timestamp": 6.125, "motion_score": 0.0840},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_geometry_candidate",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_weak_geometry_candidate_motion_window_conflict")
        evidence = diagnostic["motion_window_conflict"]["candidate_conflict_evidence"]
        self.assertIn("candidate_pose_geometry_weak", evidence["motion_context"]["diagnostic_labels"])
        self.assertEqual(evidence["semantic_span_sec"], 0.88)

    def test_candidate_motion_window_conflict_ignores_unreliable_pose_weak_takeoff_geometry(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.75,
            "quality_flags": [],
            "selected": [
                {"timestamp": 3.82, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.75},
                {"timestamp": 4.30, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.70},
                {"timestamp": 4.687, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.75},
            ],
            "video_ai": {
                "confidence": 0.75,
                "quality_flags": ["video_temporal_not_high_confidence"],
                "key_moments": {"T_takeoff_sec": 3.82, "A_air_sec": 4.30, "L_landing_sec": 4.687},
            },
        }
        cluster = {"start_timestamp": 0.0, "end_timestamp": 2.062}
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                ],
                "T": {
                    "timestamp": 1.438,
                    "confidence": 0.418,
                    "evidence": {"motion_score": 0.0482, "motion_cluster_window": cluster},
                    "warnings": ["knee_extension_weak", "com_ascent_weak", "takeoff_geometry_weak"],
                },
                "A": {
                    "timestamp": 1.812,
                    "confidence": 0.553,
                    "evidence": {"motion_score": 0.0334, "motion_cluster_window": cluster},
                    "warnings": ["confidence_missing_knee_angle_change"],
                },
                "L": {
                    "timestamp": 2.062,
                    "confidence": 0.642,
                    "evidence": {"motion_score": 0.0183, "motion_cluster_window": cluster},
                    "warnings": ["knee_absorption_weak"],
                },
            }
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0010", "timestamp": 1.438, "motion_score": 0.0482},
                {"frame_id": "frame_0013", "timestamp": 1.812, "motion_score": 0.0334},
                {"frame_id": "frame_0014", "timestamp": 2.062, "motion_score": 0.0183},
                {"frame_id": "semantic_t", "timestamp": 3.812, "motion_score": 0.0212},
                {"frame_id": "semantic_a", "timestamp": 4.312, "motion_score": 0.0112},
                {"frame_id": "semantic_l", "timestamp": 4.688, "motion_score": 0.0238},
                {"frame_id": "tail_peak", "timestamp": 9.062, "motion_score": 0.0596},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_geometry_candidate",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_weak_geometry_candidate_motion_window_conflict")
        evidence = diagnostic["motion_window_conflict"]["candidate_conflict_evidence"]
        self.assertIn("candidate_pose_geometry_weak", evidence["motion_context"]["diagnostic_labels"])
        self.assertEqual(evidence["candidate_anchors"]["L"]["confidence"], 0.642)

    def test_candidate_motion_window_conflict_rejects_late_unreliable_pose_fallback_when_semantic_motion_is_weak(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.65,
            "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
            "selected": [
                {"timestamp": 2.937, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.65},
                {"timestamp": 3.350, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.60},
                {"timestamp": 3.550, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.65},
            ],
            "video_ai": {
                "confidence": 0.65,
                "fallback_recommendation": "use_video_timestamps",
                "quality_flags": ["video_temporal_not_high_confidence", "video_temporal_quality_retry"],
                "key_moments": {"T_takeoff_sec": 2.95, "A_air_sec": 3.35, "L_landing_sec": 3.55},
            },
        }
        cluster = {"start_timestamp": 4.062, "end_timestamp": 5.625}
        low_visibility_warning = "tal_candidate_motion_fallback_low_visibility_weak_boundary"
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    "keyframe_candidates_motion_fallback_low_visibility_weak_boundary",
                    low_visibility_warning,
                    "tal_candidate_confidence_low",
                ],
                "T": {
                    "frame_id": "frame_0025",
                    "timestamp": 4.125,
                    "confidence": 0.475,
                    "evidence": {"motion_score": 0.0365, "motion_cluster_window": cluster},
                    "warnings": [
                        "knee_extension_weak",
                        "keyframe_candidates_motion_fallback",
                        low_visibility_warning,
                    ],
                },
                "A": {
                    "frame_id": "frame_0027",
                    "timestamp": 4.250,
                    "confidence": 0.34,
                    "evidence": {"motion_score": 0.0280, "motion_fallback": True, "visibility_score": 0.0},
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "a_pose_signal_drifted",
                        low_visibility_warning,
                    ],
                },
                "L": {
                    "frame_id": "frame_0029",
                    "timestamp": 4.875,
                    "confidence": 0.34,
                    "evidence": {"motion_score": 0.0242, "motion_fallback": True, "visibility_score": 0.0},
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "l_pose_signal_drifted",
                        "keyframe_candidates_motion_fallback_unreliable_pose_state",
                        low_visibility_warning,
                    ],
                },
            }
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0017", "timestamp": 2.625, "motion_score": 0.0398},
                {"frame_id": "frame_0019", "timestamp": 2.750, "motion_score": 0.0202},
                {"frame_id": "frame_0020", "timestamp": 2.875, "motion_score": 0.0280},
                {"frame_id": "frame_0021", "timestamp": 3.438, "motion_score": 0.0289},
                {"frame_id": "frame_0022", "timestamp": 3.500, "motion_score": 0.0248},
                {"frame_id": "frame_0024", "timestamp": 4.062, "motion_score": 0.0419},
                {"frame_id": "frame_0025", "timestamp": 4.125, "motion_score": 0.0365},
                {"frame_id": "frame_0027", "timestamp": 4.250, "motion_score": 0.0280},
                {"frame_id": "frame_0029", "timestamp": 4.875, "motion_score": 0.0242},
                {"frame_id": "frame_0030", "timestamp": 5.625, "motion_score": 0.0454},
                {"frame_id": "frame_0032", "timestamp": 5.750, "motion_score": 0.0778},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, ["semantic_keyframes_unreliable_candidate_motion_window_conflict"])
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_candidate_tal_conflict_ignored_unreliable_pose_fallback",
            resolved["quality_flags"],
        )
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "rejected_candidate_motion_window_conflict")
        motion_conflict = diagnostic["motion_window_conflict"]
        self.assertTrue(motion_conflict["unreliable_pose_fallback_conflicts_used"])
        self.assertEqual(motion_conflict["shifted_keys"], ["T", "A", "L"])
        self.assertLess(motion_conflict["semantic_peak_ratio"], 0.45)
        self.assertGreater(motion_conflict["candidate_to_semantic_peak_ratio"], 1.8)

    def test_candidate_motion_window_conflict_rejects_weak_geometry_when_fallback_semantic_precedes_main_motion(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_video_fallback_recommended",
                "video_temporal_resolver_video_validation_not_clean",
            ],
            "selected": [
                {"timestamp": 3.153, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                {"timestamp": 3.400, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.85},
                {"timestamp": 3.767, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
            ],
            "video_ai": {
                "confidence": 0.8,
                "fallback_recommendation": "manual_review",
                "quality_flags": ["video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.0, "A_air_sec": 3.4, "L_landing_sec": 3.8},
            },
        }
        cluster = {"start_timestamp": 3.0, "end_timestamp": 6.438}
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                ],
                "T": {
                    "timestamp": 4.875,
                    "confidence": 0.49,
                    "evidence": {"motion_score": 0.0832, "motion_cluster_window": cluster},
                    "warnings": ["knee_extension_weak", "tal_candidate_temporal_geometry_unreliable"],
                },
                "A": {
                    "timestamp": 4.938,
                    "confidence": 0.461,
                    "evidence": {"motion_score": 0.0728, "motion_cluster_window": cluster},
                    "warnings": ["apex_local_minimum_not_clear", "tal_candidate_temporal_geometry_unreliable"],
                },
                "L": {
                    "timestamp": 6.125,
                    "confidence": 0.361,
                    "evidence": {"motion_score": 0.0798, "motion_cluster_window": cluster},
                    "warnings": ["landing_geometry_weak", "tal_candidate_landing_geometry_weak"],
                },
            }
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0015", "timestamp": 3.188, "motion_score": 0.0703},
                {"frame_id": "frame_0019", "timestamp": 4.75, "motion_score": 0.1138},
                {"frame_id": "frame_0020", "timestamp": 4.812, "motion_score": 0.1153},
                {"frame_id": "frame_0029", "timestamp": 6.375, "motion_score": 0.1045},
                {"frame_id": "frame_0032", "timestamp": 7.25, "motion_score": 0.0973},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, ["semantic_keyframes_unreliable_candidate_motion_window_conflict"])
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_weak_geometry_candidate",
            resolved["quality_flags"],
        )
        diagnostic = resolved["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "rejected_candidate_motion_window_conflict")
        evidence = diagnostic["motion_window_conflict"]["candidate_conflict_evidence"]
        self.assertEqual(evidence["motion_context"]["global_peak_timestamp"], 4.812)
        self.assertEqual(evidence["motion_context"]["candidate_window"]["peak_ratio"], 1.0)

    def test_reused_semantic_tal_survives_insufficient_pose_low_visibility_motion_fallback(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.78,
            "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
            "selected": [
                {"timestamp": 15.187, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.78},
                {"timestamp": 15.5, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.78},
                {"timestamp": 16.033, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.78},
            ],
            "video_ai": {
                "confidence": 0.78,
                "quality_flags": [],
                "key_moments": {"T_takeoff_sec": 15.187, "A_air_sec": 15.5, "L_landing_sec": 16.033},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_insufficient_pose",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                ],
                "T": {
                    "timestamp": 3.188,
                    "confidence": 0.518,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 3.438,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 3.625,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                },
                "motion_fallback_time_bounds": {
                    "start_timestamp": 3.188,
                    "end_timestamp": 3.625,
                },
            }
        }
        bio_data["quality_flags"] = [
            "person_tracker_target_lost",
            "person_tracker_relock_rejected",
            "person_tracker_final_unrecovered",
        ]
        bio_data["target_lock_quality_flags"] = [
            "person_tracker_target_lost",
            "person_tracker_relock_rejected",
            "person_tracker_final_unrecovered",
        ]
        motion_scores = {
            "selected": [
                {"timestamp": 3.188, "motion_score": 0.11},
                {"timestamp": 3.438, "motion_score": 0.2154},
                {"timestamp": 3.625, "motion_score": 0.2},
                {"timestamp": 15.187, "motion_score": 0.12},
                {"timestamp": 15.5, "motion_score": 0.1346},
                {"timestamp": 16.033, "motion_score": 0.13},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", validated["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_motion_fallback", validated["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose", validated["quality_flags"])
        self.assertIn(
            "semantic_keyframes_reused_ignored_low_visibility_bounded_motion_fallback",
            validated["quality_flags"],
        )
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_insufficient_pose_low_visibility_fallback",
            validated["quality_flags"],
        )
        self.assertIn(
            "semantic_keyframes_reuse_candidate_conflict_ignored_insufficient_pose_low_visibility_fallback",
            validated["quality_flags"],
        )
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["decision"],
            "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
        )
        self.assertEqual(
            validated["semantic_reuse_current_candidate_conflict"]["decision"],
            "ignored_insufficient_pose_low_visibility_motion_fallback_candidate",
        )
        self.assertEqual(validated["semantic_reuse_current_candidate_conflict"]["low_visibility_motion_fallback_keys"], ["A", "L", "T"])

    def test_full_context_video_tal_survives_late_takeoff_anchor_motion_fallback(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.80,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_refinement_phase_rejected",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                "video_temporal_quality_retry_motion_cluster_conflict",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 3.653,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.85,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 4.10,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.80,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 4.40,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.85,
                },
            ],
            "video_ai": {
                "confidence": 0.80,
                "fallback_recommendation": "use_video_timestamps",
                "analyzed_video_kind": "action_window_ai",
                "quality_flags": [],
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Toe Loop",
                    "confidence": 0.90,
                },
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 3.5, "time_end": 3.9, "confidence": 0.85},
                    {"phase_code": "air", "time_start": 3.9, "time_end": 4.3, "confidence": 0.80},
                    {"phase_code": "landing", "time_start": 4.3, "time_end": 4.6, "confidence": 0.85},
                ],
                "key_moments": {"T_takeoff_sec": 3.7, "A_air_sec": 4.1, "L_landing_sec": 4.4},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                ],
                "T": {
                    "frame_id": "frame_0019",
                    "timestamp": 7.000,
                    "confidence": 0.573,
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    ],
                },
                "A": {
                    "frame_id": "frame_0023",
                    "timestamp": 7.250,
                    "confidence": 0.539,
                    "evidence": {
                        "motion_fallback": True,
                        "visibility_score": 0.0,
                    },
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_skeleton_drifted_after_takeoff",
                    ],
                },
                "L": {
                    "frame_id": "frame_0026",
                    "timestamp": 7.812,
                    "confidence": 0.577,
                    "evidence": {
                        "motion_fallback": True,
                        "visibility_score": 0.0,
                    },
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                    ],
                },
            }
        }
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "input_window_mode": "full_context",
            "input_window_reason": "full_context",
            "input_window_duration_sec": 8.868,
            "selected": [
                {"frame_id": "frame_0059", "timestamp": 3.653, "motion_score": 0.0288},
                {"frame_id": "frame_0066", "timestamp": 4.100, "motion_score": 0.0264},
                {"frame_id": "frame_0070", "timestamp": 4.400, "motion_score": 0.0228},
                {"frame_id": "frame_0112", "timestamp": 7.000, "motion_score": 0.1060},
                {"frame_id": "frame_0116", "timestamp": 7.250, "motion_score": 0.1123},
                {"frame_id": "frame_0125", "timestamp": 7.812, "motion_score": 0.1183},
                {"frame_id": "frame_0127", "timestamp": 7.938, "motion_score": 0.1160},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_takeoff_anchor_fallback",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        self.assertEqual(
            resolved["semantic_candidate_tal_conflict"]["decision"],
            "ignored_full_context_takeoff_anchor_motion_fallback_tail_window",
        )
        self.assertTrue(semantic_keyframes_are_reliable(resolved))

    def test_reused_semantic_tal_survives_full_context_takeoff_anchor_motion_fallback(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.85,
            "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
            "selected": [
                {"frame_id": "semantic_0001", "timestamp": 2.620, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.80},
                {"frame_id": "semantic_0002", "timestamp": 3.100, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                {"frame_id": "semantic_0003", "timestamp": 3.667, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.80},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                ],
                "T": {
                    "frame_id": "frame_0112",
                    "timestamp": 7.000,
                    "confidence": 0.573,
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    ],
                },
                "A": {
                    "frame_id": "frame_0116",
                    "timestamp": 7.250,
                    "confidence": 0.539,
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_skeleton_drifted_after_takeoff",
                    ],
                },
                "L": {
                    "frame_id": "frame_0125",
                    "timestamp": 7.812,
                    "confidence": 0.577,
                    "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                    ],
                },
            }
        }
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "input_window_mode": "full_context",
            "input_window_reason": "full_context",
            "input_window_duration_sec": 8.868,
            "selected": [
                {"frame_id": "frame_0059", "timestamp": 3.653, "motion_score": 0.0288},
                {"frame_id": "frame_0066", "timestamp": 4.100, "motion_score": 0.0264},
                {"frame_id": "frame_0070", "timestamp": 4.400, "motion_score": 0.0228},
                {"frame_id": "frame_0112", "timestamp": 7.000, "motion_score": 0.1060},
                {"frame_id": "frame_0116", "timestamp": 7.250, "motion_score": 0.1123},
                {"frame_id": "frame_0125", "timestamp": 7.812, "motion_score": 0.1183},
                {"frame_id": "frame_0127", "timestamp": 7.938, "motion_score": 0.1160},
            ],
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_takeoff_anchor_fallback",
            validated["quality_flags"],
        )
        self.assertIn(
            "semantic_keyframes_reuse_candidate_conflict_ignored_full_context_takeoff_anchor_fallback",
            validated["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertEqual(
            validated["semantic_reuse_current_candidate_conflict"]["decision"],
            "ignored_reused_semantic_over_full_context_takeoff_anchor_motion_fallback",
        )

    def test_video_tal_survives_early_takeoff_anchor_motion_fallback(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.80,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 2.90,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.80,
                    "refinement_motion_score": 0.0175,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 3.50,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.70,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 4.00,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.80,
                    "refinement_motion_score": 0.0175,
                },
            ],
            "video_ai": {
                "confidence": 0.80,
                "fallback_recommendation": "use_video_timestamps",
                "analyzed_video_kind": "action_window_ai",
                "quality_flags": [],
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Toe Loop",
                    "confidence": 0.85,
                },
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 2.6, "time_end": 3.2, "confidence": 0.80},
                    {"phase_code": "air", "time_start": 3.2, "time_end": 3.8, "confidence": 0.70},
                    {"phase_code": "landing", "time_start": 3.8, "time_end": 4.5, "confidence": 0.80},
                ],
                "key_moments": {"T_takeoff_sec": 2.90, "A_air_sec": 3.50, "L_landing_sec": 4.00},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "keyframe_candidates_tail_motion_window_reselected",
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                ],
                "T": {
                    "frame_id": "frame_0002",
                    "timestamp": 0.062,
                    "confidence": 0.470,
                    "evidence": {
                        "motion_score": 0.0556,
                        "visibility_score": 0.969,
                        "motion_cluster_window": {
                            "start_timestamp": 0.0,
                            "end_timestamp": 3.625,
                        },
                    },
                    "warnings": [
                        "knee_extension_weak",
                        "com_ascent_weak",
                        "takeoff_timing_window_weak",
                        "keyframe_candidates_motion_fallback",
                    ],
                },
                "A": {
                    "frame_id": "frame_0005",
                    "timestamp": 0.250,
                    "confidence": 0.518,
                    "evidence": {
                        "motion_fallback": True,
                        "visibility_score": 0.0,
                    },
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "a_pose_signal_drifted",
                    ],
                },
                "L": {
                    "frame_id": "frame_0009",
                    "timestamp": 0.938,
                    "confidence": 0.486,
                    "evidence": {
                        "motion_fallback": True,
                        "visibility_score": 0.0,
                    },
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "l_pose_signal_drifted",
                    ],
                },
            }
        }
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "input_window_mode": "full_context",
            "input_window_reason": "full_context",
            "input_window_duration_sec": 6.235,
            "selected": [
                {"frame_id": "frame_0001", "timestamp": 0.000, "motion_score": 0.0500},
                {"frame_id": "frame_0002", "timestamp": 0.062, "motion_score": 0.0556},
                {"frame_id": "frame_0005", "timestamp": 0.250, "motion_score": 0.0410},
                {"frame_id": "frame_0009", "timestamp": 0.938, "motion_score": 0.0245},
                {"frame_id": "frame_0024", "timestamp": 3.625, "motion_score": 0.0175},
                {"frame_id": "frame_0030", "timestamp": 4.000, "motion_score": 0.0160},
                {"frame_id": "frame_0099", "timestamp": 6.188, "motion_score": 0.0738},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_early_takeoff_anchor_fallback",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        self.assertEqual(
            resolved["semantic_candidate_tal_conflict"]["decision"],
            "ignored_early_takeoff_anchor_motion_fallback_window",
        )
        self.assertTrue(semantic_keyframes_are_reliable(resolved))

    def test_video_tal_survives_early_approach_takeoff_anchor_window(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_refinement_phase_rejected",
                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 3.987,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.90,
                    "refinement_motion_score": 0.0205,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 4.400,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.90,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 4.700,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.90,
                    "refinement_motion_score": 0.0103,
                },
            ],
            "video_ai": {
                "confidence": 0.90,
                "fallback_recommendation": "use_video_timestamps",
                "quality_flags": ["video_temporal_phase_5_end_clamped_to_duration"],
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Toe Loop",
                    "confidence": 0.95,
                },
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 0.0, "time_end": 3.2, "confidence": 0.90},
                    {"phase_code": "preparation", "time_start": 3.2, "time_end": 3.9, "confidence": 0.90},
                    {"phase_code": "takeoff", "time_start": 3.9, "time_end": 4.2, "confidence": 0.90},
                    {"phase_code": "air", "time_start": 4.2, "time_end": 4.6, "confidence": 0.90},
                    {"phase_code": "landing", "time_start": 4.6, "time_end": 4.9, "confidence": 0.90},
                    {"phase_code": "glide_out", "time_start": 4.9, "time_end": 7.368, "confidence": 0.90},
                ],
                "key_moments": {"T_takeoff_sec": 4.0, "A_air_sec": 4.4, "L_landing_sec": 4.7},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "keyframe_candidates_tail_motion_window_reselected",
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
                ],
                "T": {
                    "frame_id": "frame_0015",
                    "timestamp": 1.438,
                    "confidence": 0.556,
                    "evidence": {
                        "motion_score": 0.0226,
                        "visibility_score": 0.851,
                        "motion_cluster_window": {
                            "start_timestamp": 0.0,
                            "end_timestamp": 4.25,
                        },
                    },
                    "warnings": ["keyframe_candidates_motion_fallback"],
                },
                "A": {
                    "frame_id": "frame_0016",
                    "timestamp": 1.625,
                    "confidence": 0.483,
                    "evidence": {"motion_score": 0.0206, "motion_fallback": True, "visibility_score": 0.0},
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                },
                "L": {
                    "frame_id": "frame_0019",
                    "timestamp": 2.188,
                    "confidence": 0.34,
                    "evidence": {"motion_score": 0.0304, "motion_fallback": True, "visibility_score": 0.0},
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "l_pose_signal_drifted",
                        "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    ],
                },
            }
        }
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "input_window_mode": "full_context",
            "input_window_reason": "full_context",
            "input_window_duration_sec": 7.368,
            "selected": [
                {"frame_id": "frame_0007", "timestamp": 0.375, "motion_score": 0.0633},
                {"frame_id": "frame_0015", "timestamp": 1.438, "motion_score": 0.0226},
                {"frame_id": "frame_0016", "timestamp": 1.625, "motion_score": 0.0206},
                {"frame_id": "frame_0019", "timestamp": 2.188, "motion_score": 0.0304},
                {"frame_id": "frame_0024", "timestamp": 4.25, "motion_score": 0.0239},
                {"frame_id": "frame_0025", "timestamp": 4.812, "motion_score": 0.0114},
                {"frame_id": "frame_0032", "timestamp": 7.312, "motion_score": 0.0675},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_early_candidate_approach_window",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        self.assertEqual(
            resolved["semantic_candidate_tal_conflict"]["decision"],
            "ignored_early_takeoff_anchor_approach_motion_window",
        )
        self.assertTrue(semantic_keyframes_are_reliable(resolved))

    def test_video_tal_survives_takeoff_anchor_phase_shifted_candidate(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.90,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_refinement_delta_rejected",
                "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 2.187,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.85,
                    "refinement_motion_score": 0.0200,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 2.700,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.80,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 3.200,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.85,
                    "refinement_motion_score": 0.0140,
                },
            ],
            "video_ai": {
                "confidence": 0.90,
                "fallback_recommendation": "use_video_timestamps",
                "quality_flags": ["video_temporal_phase_5_end_clamped_to_duration"],
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Toe Loop",
                    "confidence": 0.95,
                },
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 0.0, "time_end": 1.3, "confidence": 0.95},
                    {"phase_code": "preparation", "time_start": 1.3, "time_end": 2.0, "confidence": 0.90},
                    {"phase_code": "takeoff", "time_start": 2.0, "time_end": 2.5, "confidence": 0.85},
                    {"phase_code": "air", "time_start": 2.5, "time_end": 3.0, "confidence": 0.80},
                    {"phase_code": "landing", "time_start": 3.0, "time_end": 3.5, "confidence": 0.85},
                    {"phase_code": "glide_out", "time_start": 3.5, "time_end": 7.368, "confidence": 0.90},
                ],
                "key_moments": {"T_takeoff_sec": 2.3, "A_air_sec": 2.7, "L_landing_sec": 3.2},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "keyframe_candidates_tail_motion_window_reselected",
                    "tal_candidate_skeleton_drifted_after_takeoff",
                    "keyframe_candidates_motion_fallback",
                    "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    "tal_candidate_motion_fallback_unreliable_pose_low_confidence",
                ],
                "T": {
                    "frame_id": "frame_0015",
                    "timestamp": 1.438,
                    "confidence": 0.556,
                    "evidence": {
                        "motion_score": 0.0226,
                        "visibility_score": 0.851,
                        "motion_cluster_window": {
                            "start_timestamp": 0.0,
                            "end_timestamp": 4.25,
                        },
                    },
                    "warnings": ["keyframe_candidates_motion_fallback"],
                },
                "A": {
                    "frame_id": "frame_0016",
                    "timestamp": 1.625,
                    "confidence": 0.483,
                    "evidence": {"motion_score": 0.0206, "motion_fallback": True, "visibility_score": 0.0},
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                },
                "L": {
                    "frame_id": "frame_0019",
                    "timestamp": 2.188,
                    "confidence": 0.34,
                    "evidence": {"motion_score": 0.0304, "motion_fallback": True, "visibility_score": 0.0},
                    "warnings": [
                        "keyframe_candidates_motion_fallback",
                        "l_pose_signal_drifted",
                        "keyframe_candidates_motion_fallback_unreliable_pose_state",
                    ],
                },
            }
        }
        motion_scores = {
            "frame_rate": 16,
            "window_start": 0.0,
            "input_window_mode": "full_context",
            "input_window_reason": "full_context",
            "input_window_duration_sec": 7.368,
            "selected": [
                {"frame_id": "frame_0007", "timestamp": 0.375, "motion_score": 0.0633},
                {"frame_id": "frame_0015", "timestamp": 1.438, "motion_score": 0.0226},
                {"frame_id": "frame_0016", "timestamp": 1.625, "motion_score": 0.0206},
                {"frame_id": "frame_0019", "timestamp": 2.188, "motion_score": 0.0304},
                {"frame_id": "frame_0021", "timestamp": 2.938, "motion_score": 0.0240},
                {"frame_id": "frame_0024", "timestamp": 4.25, "motion_score": 0.0239},
                {"frame_id": "frame_0032", "timestamp": 7.312, "motion_score": 0.0675},
            ],
        }

        flags = _semantic_candidate_tal_conflict_flags(
            resolved,
            bio_data,
            analysis_profile="jump",
            motion_scores=motion_scores,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_takeoff_anchor_phase_shift",
            resolved["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", resolved["quality_flags"])
        self.assertEqual(
            resolved["semantic_candidate_tal_conflict"]["decision"],
            "ignored_takeoff_anchor_phase_shifted_candidate",
        )
        self.assertTrue(semantic_keyframes_are_reliable(resolved))

    def test_reused_semantic_tal_survives_weak_temporal_geometry_candidate_conflict(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.82,
            "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
            "selected": [
                {"timestamp": 3.453, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 3.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                {"timestamp": 4.033, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                ],
                "T": {"timestamp": 2.625, "confidence": 0.49, "warnings": ["knee_extension_weak"]},
                "A": {"timestamp": 2.688, "confidence": 0.49, "warnings": ["apex_local_minimum_not_clear"]},
                "L": {"timestamp": 4.062, "confidence": 0.404, "warnings": ["landing_geometry_weak"]},
            }
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores={"selected": []},
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertIn(
            "semantic_keyframes_reuse_candidate_conflict_ignored_weak_temporal_geometry",
            validated["quality_flags"],
        )
        self.assertEqual(
            validated["semantic_reuse_current_candidate_conflict"]["decision"],
            "ignored_weak_temporal_geometry_candidate",
        )

    def test_reused_semantic_tal_survives_long_unresolved_motion_fallback_candidate_conflict(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.6,
            "quality_flags": [
                "semantic_keyframes_reused_from_matching_video",
                "semantic_keyframes_reused_over_long_unresolved_motion_fallback",
            ],
            "selected": [
                {"timestamp": 5.953, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.5},
                {"timestamp": 6.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.5},
                {"timestamp": 7.134, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.5},
            ],
            "video_ai": {
                "confidence": 0.2,
                "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "keyframe_candidates_tail_motion_window_rejected",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "T": {
                    "timestamp": 1.375,
                    "confidence": 0.497,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0624, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 4.375,
                    "confidence": 0.473,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0502, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 7.688,
                    "confidence": 0.534,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0814, "visibility_score": 0.0},
                },
            }
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores={
                "selected": [
                    {"timestamp": 1.375, "motion_score": 0.0624},
                    {"timestamp": 4.375, "motion_score": 0.0502},
                    {"timestamp": 5.953, "motion_score": 0.0636},
                    {"timestamp": 7.134, "motion_score": 0.1146},
                    {"timestamp": 7.688, "motion_score": 0.0814},
                ]
            },
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertIn(
            "semantic_keyframes_reuse_candidate_conflict_ignored_long_unresolved_motion_fallback",
            validated["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertEqual(
            validated["semantic_reuse_current_candidate_conflict"]["decision"],
            "ignored_reused_semantic_over_long_unresolved_motion_fallback",
        )
        self.assertEqual(validated["semantic_reuse_current_candidate_conflict"]["candidate_tal_span_sec"], 6.313)

    def test_reused_semantic_tal_survives_current_motion_window_without_pose_support(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
            "selected": [
                {"timestamp": 6.567, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 7.2, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 7.6, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                "key_moments": {"T_takeoff_sec": 6.567, "A_air_sec": 7.2, "L_landing_sec": 7.6},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "tal_candidate_motion_fallback_low_motion_low_confidence",
                ],
                "motion_fallback_time_bounds": {"start_timestamp": 3.188, "end_timestamp": 5.038},
                "T": {
                    "timestamp": 3.188,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0999, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 3.438,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0998, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 3.688,
                    "confidence": 0.503,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.077, "visibility_score": 0.0},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 2.938, "motion_score": 0.0682},
                {"timestamp": 3.062, "motion_score": 0.1158},
                {"timestamp": 3.125, "motion_score": 0.1178},
                {"timestamp": 3.188, "motion_score": 0.0999},
                {"timestamp": 3.438, "motion_score": 0.0998},
                {"timestamp": 3.688, "motion_score": 0.077},
                {"timestamp": 6.125, "motion_score": 0.0155},
                {"timestamp": 6.375, "motion_score": 0.0159},
                {"timestamp": 8.125, "motion_score": 0.014},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", validated["quality_flags"])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_low_visibility_no_pose_support",
            validated["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertIn(
            "semantic_keyframes_reuse_candidate_conflict_ignored_low_visibility_no_pose_support",
            validated["quality_flags"],
        )
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["decision"],
            "ignored_low_visibility_current_motion_window_without_pose_support",
        )
        self.assertEqual(
            validated["semantic_reuse_current_candidate_conflict"]["decision"],
            "ignored_reused_semantic_current_motion_window_without_pose_support",
        )
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["current_motion_rejection"]["global_peak_timestamp"],
            3.125,
        )

    def test_reused_semantic_tal_rejects_near_late_main_motion_peak_without_pose_support(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
            "selected": [
                {"timestamp": 6.52, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.75},
                {"timestamp": 7.0, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 7.567, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                "key_moments": {"T_takeoff_sec": 6.52, "A_air_sec": 7.0, "L_landing_sec": 7.567},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 9.35},
                "T": {
                    "timestamp": 7.75,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.2264, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 7.938,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.25, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 8.0,
                    "confidence": 0.509,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.1439, "visibility_score": 0.0},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 7.562, "motion_score": 0.088},
                {"timestamp": 7.625, "motion_score": 0.1355},
                {"timestamp": 7.688, "motion_score": 0.2286},
                {"timestamp": 7.75, "motion_score": 0.2264},
                {"timestamp": 7.812, "motion_score": 0.259},
                {"timestamp": 7.938, "motion_score": 0.25},
                {"timestamp": 8.0, "motion_score": 0.1439},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertFalse(semantic_keyframes_are_reliable(validated))
        self.assertIn("semantic_keyframes_unreliable_candidate_tal_conflict", validated["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["decision"],
            "rejected_low_visibility_current_motion_window_conflict_without_pose_support",
        )
        self.assertEqual(
            validated["semantic_reuse_current_candidate_conflict"]["decision"],
            "rejected_reused_semantic_current_motion_window_conflict_without_pose_support",
        )
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["current_motion_rejection"]["near_candidate_window"],
            True,
        )
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["current_motion_rejection"]["semantic_peak_ratio"],
            0.34,
        )

    def test_current_video_semantic_tal_rejects_overlapping_late_main_motion_peak_without_pose_support(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_quality_retry",
                "semantic_keyframe_core_foreground_occlusion_repaired",
                "video_temporal_quality_retry_used",
            ],
            "selected": [
                {"timestamp": 6.753, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 7.25, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 7.767, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": ["video_temporal_quality_retry", "video_temporal_quality_retry_used"],
                "key_moments": {"T_takeoff_sec": 6.753, "A_air_sec": 7.25, "L_landing_sec": 7.767},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 9.35},
                "T": {
                    "timestamp": 7.75,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.2264, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 7.938,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.25, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 8.0,
                    "confidence": 0.509,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.1439, "visibility_score": 0.0},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 6.625, "motion_score": 0.0527},
                {"timestamp": 6.688, "motion_score": 0.0477},
                {"timestamp": 7.562, "motion_score": 0.088},
                {"timestamp": 7.625, "motion_score": 0.1355},
                {"timestamp": 7.688, "motion_score": 0.2286},
                {"timestamp": 7.75, "motion_score": 0.2264},
                {"timestamp": 7.812, "motion_score": 0.259},
                {"timestamp": 7.875, "motion_score": 0.191},
                {"timestamp": 7.938, "motion_score": 0.25},
                {"timestamp": 8.0, "motion_score": 0.1439},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertFalse(semantic_keyframes_are_reliable(validated))
        self.assertIn("semantic_keyframes_unreliable_candidate_tal_conflict", validated["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["decision"],
            "rejected_low_visibility_current_motion_window_conflict_without_pose_support",
        )
        rejection = validated["semantic_candidate_tal_conflict"]["current_motion_rejection"]
        self.assertEqual(rejection["global_peak_timestamp"], 7.812)
        self.assertEqual(rejection["local_core_motion_conflict"]["keys"], ["T", "A"])
        self.assertLess(rejection["semantic_peak_ratio"], 0.2)
        self.assertGreaterEqual(rejection["candidate_peak_ratio"], 0.99)

    def test_current_video_late_semantic_tal_falls_back_to_main_motion_candidates(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_quality_retry",
                "semantic_keyframe_core_foreground_occlusion_repaired",
                "video_temporal_quality_retry_rejected",
            ],
            "selected": [
                {"timestamp": 8.253, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 8.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 9.3, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": ["video_temporal_quality_retry", "video_temporal_quality_retry_rejected"],
                "key_moments": {"T_takeoff_sec": 8.253, "A_air_sec": 8.8, "L_landing_sec": 9.3},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 9.35},
                "T": {
                    "frame_id": "frame_0027",
                    "timestamp": 7.75,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.2264, "visibility_score": 0.0},
                },
                "A": {
                    "frame_id": "frame_0030",
                    "timestamp": 7.938,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.25, "visibility_score": 0.0},
                },
                "L": {
                    "frame_id": "frame_0031",
                    "timestamp": 8.0,
                    "confidence": 0.509,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.1439, "visibility_score": 0.0},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 7.562, "motion_score": 0.088},
                {"timestamp": 7.625, "motion_score": 0.1355},
                {"timestamp": 7.688, "motion_score": 0.2286},
                {"timestamp": 7.75, "motion_score": 0.2264},
                {"timestamp": 7.812, "motion_score": 0.259},
                {"timestamp": 7.875, "motion_score": 0.191},
                {"timestamp": 7.938, "motion_score": 0.25},
                {"timestamp": 8.0, "motion_score": 0.1439},
                {"timestamp": 8.253, "motion_score": 0.052},
                {"timestamp": 8.8, "motion_score": 0.02},
                {"timestamp": 9.3, "motion_score": 0.015},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertFalse(semantic_keyframes_are_reliable(validated))
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", validated["quality_flags"])
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["decision"],
            "rejected_low_visibility_current_motion_window_conflict_without_pose_support",
        )
        rejection = validated["semantic_candidate_tal_conflict"]["current_motion_rejection"]
        self.assertEqual(rejection["global_peak_timestamp"], 7.812)
        self.assertEqual(rejection["candidate_peak_ratio"], 1.0)
        self.assertLessEqual(rejection["semantic_peak_ratio"], 0.21)

        _apply_unreliable_semantic_selected_fallback(
            validated,
            bio_data,
            analysis_profile="jump",
        )

        self.assertEqual(validated["source"], "skeleton_fallback")
        anchors = {item["key_moment"][0]: item["timestamp"] for item in validated["selected"]}
        self.assertEqual(anchors, {"T": 7.75, "A": 7.938, "L": 8.0})
        self.assertIn(
            "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
            validated["quality_flags"],
        )

    def test_unreliable_semantic_fallback_ignores_long_unresolved_motion_candidates(self) -> None:
        resolved = {
            "source": "skeleton_fallback",
            "confidence": 0.75,
            "quality_flags": ["semantic_keyframes_unreliable_fallback_to_sampled_frames"],
            "selected": [
                {"timestamp": 2.125, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 2.3, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.7},
                {"timestamp": 2.438, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.7},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                ],
                "T": {"frame_id": "frame_0008", "timestamp": 1.375, "confidence": 0.497, "evidence": {"motion_fallback": True}},
                "A": {"frame_id": "frame_0016", "timestamp": 4.375, "confidence": 0.473, "evidence": {"motion_fallback": True}},
                "L": {"frame_id": "frame_0032", "timestamp": 7.688, "confidence": 0.534, "evidence": {"motion_fallback": True}},
            }
        }

        _apply_unreliable_semantic_selected_fallback(
            resolved,
            bio_data,
            analysis_profile="jump",
        )

        self.assertEqual([item["timestamp"] for item in resolved["selected"]], [2.125, 2.3, 2.438])
        self.assertNotIn(
            "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
            resolved["quality_flags"],
        )

    def test_unreliable_semantic_fallback_rejects_weak_takeoff_apex_candidate(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.55,
            "quality_flags": [
                "semantic_keyframes_unreliable_after_refinement",
                "semantic_keyframes_unreliable_fallback_to_sampled_frames",
            ],
            "selected": [
                {"timestamp": 5.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.55},
                {"timestamp": 6.1, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.50},
                {"timestamp": 6.4, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.55},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                ],
                "T": {
                    "frame_id": "frame_0024",
                    "timestamp": 5.938,
                    "confidence": 0.587,
                    "warnings": ["knee_extension_weak", "takeoff_geometry_weak"],
                },
                "A": {
                    "frame_id": "frame_0025",
                    "timestamp": 6.0,
                    "confidence": 0.526,
                    "warnings": [
                        "confidence_missing_knee_angle_change",
                        "apex_local_minimum_not_clear",
                        "apex_motion_bounded_unclear_fallback",
                    ],
                },
                "L": {"frame_id": "frame_0027", "timestamp": 7.812, "confidence": 0.65},
            }
        }

        _apply_unreliable_semantic_selected_fallback(
            resolved,
            bio_data,
            analysis_profile="jump",
        )

        self.assertEqual(resolved["source"], "video_ai_refined")
        self.assertEqual([item["timestamp"] for item in resolved["selected"]], [5.8, 6.1, 6.4])
        self.assertIn("semantic_keyframes_candidate_fallback_rejected_weak_takeoff_apex", resolved["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
            resolved["quality_flags"],
        )

    def test_unreliable_semantic_fallback_rejects_missing_knee_compressed_takeoff_apex(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.55,
            "quality_flags": [
                "semantic_keyframes_unreliable_after_retry_rejection",
                "semantic_keyframes_unreliable_after_refinement",
            ],
            "selected": [
                {"timestamp": 5.8, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.55},
                {"timestamp": 6.1, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.50},
                {"timestamp": 6.4, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.55},
            ],
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                ],
                "T": {
                    "frame_id": "frame_0016",
                    "timestamp": 4.25,
                    "confidence": 0.603,
                    "warnings": ["knee_extension_weak", "takeoff_geometry_weak"],
                },
                "A": {
                    "frame_id": "frame_0017",
                    "timestamp": 4.312,
                    "confidence": 0.602,
                    "warnings": ["confidence_missing_knee_angle_change"],
                },
                "L": {
                    "frame_id": "frame_0020",
                    "timestamp": 5.438,
                    "confidence": 0.744,
                    "warnings": ["knee_absorption_weak", "landing_timing_window_weak"],
                },
            }
        }

        _apply_unreliable_semantic_selected_fallback(
            resolved,
            bio_data,
            analysis_profile="jump",
        )

        self.assertEqual(resolved["source"], "video_ai_refined")
        self.assertEqual([item["timestamp"] for item in resolved["selected"]], [5.8, 6.1, 6.4])
        self.assertIn("semantic_keyframes_candidate_fallback_rejected_weak_takeoff_apex", resolved["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
            resolved["quality_flags"],
        )

    def test_current_video_semantic_tal_aligns_near_low_visibility_main_motion_candidates(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_resolver_skeleton_candidate_not_used",
                "semantic_keyframe_refinement_phase_rejected",
            ],
            "selected": [
                {"timestamp": 7.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 7.75, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                {"timestamp": 8.053, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": [],
                "key_moments": {"T_takeoff_sec": 7.45, "A_air_sec": 7.75, "L_landing_sec": 8.0},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "T": {
                    "timestamp": 7.75,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.2264, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 7.938,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.25, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 8.0,
                    "confidence": 0.509,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.1439, "visibility_score": 0.0},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 7.562, "motion_score": 0.088},
                {"timestamp": 7.625, "motion_score": 0.1355},
                {"timestamp": 7.688, "motion_score": 0.2286},
                {"timestamp": 7.75, "motion_score": 0.2264},
                {"timestamp": 7.812, "motion_score": 0.259},
                {"timestamp": 7.875, "motion_score": 0.191},
                {"timestamp": 7.938, "motion_score": 0.25},
                {"timestamp": 8.0, "motion_score": 0.1439},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        anchors = {item["key_moment"][0]: item["timestamp"] for item in validated["selected"]}
        self.assertEqual(anchors, {"T": 7.75, "A": 7.938, "L": 8.0})
        self.assertIn("semantic_keyframes_low_visibility_main_motion_candidate_aligned", validated["quality_flags"])
        self.assertEqual(
            validated["semantic_low_visibility_main_motion_alignment"]["decision"],
            "aligned_phase_range_tal_to_current_main_motion_candidates",
        )

    def test_current_video_semantic_tal_aligns_extended_takeoff_overlap_to_main_motion(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_resolver_takeoff_refinement_delta_expanded",
                "video_temporal_resolver_skeleton_candidate_not_used",
                "video_temporal_resolver_landing_refinement_phase_tolerance",
                "semantic_keyframe_refinement_phase_start_tolerance_used",
                "semantic_keyframes_candidate_tal_conflict_ignored_insufficient_pose_low_visibility_fallback",
            ],
            "selected": [
                {"timestamp": 6.953, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 7.567, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                {"timestamp": 8.133, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": [],
                "key_moments": {"T_takeoff_sec": 6.953, "A_air_sec": 7.567, "L_landing_sec": 8.133},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                ],
                "T": {
                    "timestamp": 7.75,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.2264, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 7.938,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.25, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 8.0,
                    "confidence": 0.509,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.1439, "visibility_score": 0.0},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 6.625, "motion_score": 0.0527},
                {"timestamp": 6.688, "motion_score": 0.0477},
                {"timestamp": 7.562, "motion_score": 0.088},
                {"timestamp": 7.625, "motion_score": 0.1355},
                {"timestamp": 7.688, "motion_score": 0.2286},
                {"timestamp": 7.75, "motion_score": 0.2264},
                {"timestamp": 7.812, "motion_score": 0.259},
                {"timestamp": 7.875, "motion_score": 0.191},
                {"timestamp": 7.938, "motion_score": 0.25},
                {"timestamp": 8.0, "motion_score": 0.1439},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        anchors = {item["key_moment"][0]: item["timestamp"] for item in validated["selected"]}
        self.assertEqual(anchors, {"T": 7.75, "A": 7.938, "L": 8.0})
        self.assertIn("semantic_keyframes_low_visibility_main_motion_candidate_aligned", validated["quality_flags"])
        alignment = validated["semantic_low_visibility_main_motion_alignment"]
        self.assertEqual(alignment["adjustments"][0]["alignment_mode"], "extended_overlap_takeoff")
        self.assertEqual(alignment["takeoff_after_semantic_landing_sec"], -0.383)

    async def test_pipeline_aligns_delta_rejected_takeoff_to_pose_supported_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.7,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_skeleton_candidate_not_used",
                    "semantic_keyframe_refinement_delta_rejected",
                ],
                "selected": [
                    {
                        "timestamp": 5.7,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "confidence": 0.7,
                        "refinement_method": "local_motion_peak_delta_rejected",
                        "refinement_candidate_timestamp": 5.853,
                        "refinement_candidate_delta_sec": 0.153,
                        "refinement_reject_reason": "delta",
                        "refinement_motion_score": 0.0938,
                    },
                    {
                        "timestamp": 6.05,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "confidence": 0.6,
                        "refinement_method": "apex_preserved",
                    },
                    {
                        "timestamp": 6.303,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.7,
                        "refinement_method": "local_motion_peak",
                    },
                ],
                "video_ai": {
                    "valid": True,
                    "confidence": 0.7,
                    "key_moments": {"T_takeoff_sec": 5.7, "A_air_sec": 6.05, "L_landing_sec": 6.35},
                    "quality_flags": ["video_temporal_not_high_confidence"],
                },
            }
            refined = [dict(item) for item in resolved["selected"]]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                    "T": {
                        "frame_id": "frame_0026",
                        "timestamp": 5.938,
                        "confidence": 0.838,
                        "evidence": {"motion_score": 0.1198},
                    },
                    "A": {
                        "frame_id": "frame_0027",
                        "timestamp": 6.0,
                        "confidence": 0.605,
                        "evidence": {"motion_score": 0.0627},
                        "warnings": ["confidence_missing_knee_angle_change"],
                    },
                    "L": {
                        "frame_id": "frame_0028",
                        "timestamp": 6.625,
                        "confidence": 0.617,
                        "evidence": {"motion_score": 0.0778},
                        "warnings": ["knee_absorption_weak"],
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0022", "timestamp": 5.688, "motion_score": 0.1124},
                    {"frame_id": "frame_0023", "timestamp": 5.75, "motion_score": 0.1009},
                    {"frame_id": "frame_0026", "timestamp": 5.938, "motion_score": 0.1198},
                    {"frame_id": "frame_0027", "timestamp": 6.0, "motion_score": 0.0627},
                    {"frame_id": "frame_0028", "timestamp": 6.625, "motion_score": 0.0778},
                ]
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined, ["semantic_keyframe_refinement_delta_rejected"])),
                ):
                    with patch(
                        "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                        AsyncMock(side_effect=_fake_extract_precise_frames),
                    ):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 8.235, 0.0, 8.235, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=8.235,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "blended")
        self.assertIn(
            "semantic_keyframes_pose_supported_takeoff_candidate_aligned",
            result.resolved_keyframes["quality_flags"],
        )
        anchors = {item["key_moment"][0]: item["timestamp"] for item in result.resolved_keyframes["selected"][:3]}
        self.assertEqual(anchors, {"T": 5.938, "A": 6.05, "L": 6.303})
        self.assertEqual(result.resolved_keyframes["video_ai"]["key_moments"]["T_takeoff_sec"], 5.938)
        diagnostic = result.resolved_keyframes["semantic_pose_supported_takeoff_alignment"]
        self.assertEqual(diagnostic["decision"], "aligned_delta_rejected_takeoff_to_pose_supported_candidate")
        self.assertEqual(diagnostic["refinement_candidate_timestamp"], 5.853)
        self.assertEqual(result.resolved_keyframes["selected"][0]["motion_alignment_source"], "pose_supported_takeoff_candidate")

    def test_reused_semantic_tal_rejects_when_current_motion_window_has_pose_support(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.8,
            "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
            "selected": [
                {"timestamp": 6.567, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                {"timestamp": 7.2, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 7.6, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                "key_moments": {"T_takeoff_sec": 6.567, "A_air_sec": 7.2, "L_landing_sec": 7.6},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                ],
                "motion_fallback_time_bounds": {"start_timestamp": 3.188, "end_timestamp": 5.038},
                "T": {
                    "timestamp": 3.188,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0999, "visibility_score": 0.42},
                },
                "A": {
                    "timestamp": 3.438,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0998, "visibility_score": 0.38},
                },
                "L": {
                    "timestamp": 3.688,
                    "confidence": 0.503,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.077, "visibility_score": 0.35},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 2.938, "motion_score": 0.0682},
                {"timestamp": 3.062, "motion_score": 0.1158},
                {"timestamp": 3.125, "motion_score": 0.1178},
                {"timestamp": 3.188, "motion_score": 0.0999},
                {"timestamp": 3.438, "motion_score": 0.0998},
                {"timestamp": 3.688, "motion_score": 0.077},
                {"timestamp": 6.125, "motion_score": 0.0155},
                {"timestamp": 6.375, "motion_score": 0.0159},
                {"timestamp": 8.125, "motion_score": 0.014},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertFalse(semantic_keyframes_are_reliable(validated))
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", validated["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertIn(
            validated["semantic_reuse_current_candidate_conflict"]["decision"],
            {
                "rejected_reused_semantic_current_motion_window_conflict",
                "rejected_reused_semantic_current_candidate_conflict",
            },
        )
        self.assertNotIn(
            "semantic_keyframes_reuse_candidate_conflict_ignored_low_visibility_no_pose_support",
            validated["quality_flags"],
        )

    def test_reused_semantic_tal_survives_sparse_track_stitched_motion_cluster(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "semantic_keyframes_reused_from_matching_video",
                "semantic_keyframes_reused_over_sparse_track_stitched_candidate",
            ],
            "selected": [
                {"timestamp": 5.187, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.75},
                {"timestamp": 5.6, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                {"timestamp": 5.953, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
            ],
            "video_ai": {
                "confidence": 0.8,
                "quality_flags": ["semantic_keyframes_reused_from_matching_video"],
                "key_moments": {"T_takeoff_sec": 5.187, "A_air_sec": 5.6, "L_landing_sec": 5.953},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_takeoff_geometry_weak",
                    "tal_candidate_apex_geometry_weak",
                    "tal_candidate_weak_geometry",
                    "tal_candidate_sparse_track_stitched",
                    "tal_candidate_unreliable_sparse_track_stitch",
                    "tal_candidate_confidence_low",
                ],
                "T": {
                    "timestamp": 5.75,
                    "confidence": 0.34,
                    "warnings": ["tal_candidate_sparse_track_stitched"],
                    "evidence": {
                        "motion_score": 0.0588,
                        "visibility_score": 0.679,
                        "motion_cluster_window": {"start_timestamp": 5.75, "end_timestamp": 7.688},
                    },
                },
                "A": {
                    "timestamp": 5.812,
                    "confidence": 0.34,
                    "warnings": ["tal_candidate_sparse_track_stitched"],
                    "evidence": {
                        "motion_score": 0.0682,
                        "visibility_score": 0.86,
                        "motion_cluster_window": {"start_timestamp": 5.75, "end_timestamp": 7.688},
                    },
                },
                "L": {
                    "timestamp": 7.688,
                    "confidence": 0.34,
                    "warnings": ["tal_candidate_sparse_track_stitched"],
                    "evidence": {
                        "motion_score": 0.0829,
                        "visibility_score": 0.907,
                        "motion_cluster_window": {"start_timestamp": 5.75, "end_timestamp": 7.688},
                    },
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 5.75, "motion_score": 0.0588},
                {"timestamp": 5.812, "motion_score": 0.0682},
                {"timestamp": 5.953, "motion_score": 0.0828},
                {"timestamp": 7.188, "motion_score": 0.177},
                {"timestamp": 7.438, "motion_score": 0.196},
                {"timestamp": 7.562, "motion_score": 0.186},
                {"timestamp": 7.688, "motion_score": 0.0829},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertNotIn("semantic_keyframes_unreliable_reused_current_candidate_conflict", validated["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_reused_motion_cluster_conflict", validated["quality_flags"])
        self.assertIn(
            "semantic_keyframes_reuse_motion_cluster_conflict_ignored_sparse_track_stitched_candidate",
            validated["quality_flags"],
        )
        self.assertEqual(
            validated["semantic_motion_cluster_conflict"]["decision"],
            "ignored_sparse_track_stitched_candidate_motion_cluster",
        )

    def test_current_video_semantic_tal_survives_low_visibility_motion_window_without_pose_support(self) -> None:
        resolved = {
            "source": "blended",
            "confidence": 0.6,
            "quality_flags": [
                "distance",
                "partial_occlusion",
                "video_temporal_not_high_confidence",
                "video_temporal_resolver_coherent_tal_used",
                "video_temporal_resolver_moderate_confidence_tal_used",
            ],
            "selected": [
                {
                    "timestamp": 7.6,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "confidence": 0.7,
                    "refinement_motion_score": 0.0116,
                },
                {"timestamp": 8.0, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
                {
                    "timestamp": 8.3,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.6,
                    "refinement_motion_score": 0.0124,
                },
            ],
            "video_ai": {
                "confidence": 0.6,
                "quality_flags": ["distance", "partial_occlusion", "video_temporal_not_high_confidence"],
                "key_moments": {"T_takeoff_sec": 6.3, "A_air_sec": 6.6, "L_landing_sec": 6.9},
            },
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_incomplete",
                    "tal_order_unresolved",
                    "keyframe_candidates_motion_fallback",
                    "tal_candidate_motion_fallback_low_precision",
                    "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                ],
                "motion_fallback_time_bounds": {"start_timestamp": 3.188, "end_timestamp": 5.038},
                "T": {
                    "timestamp": 3.188,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0999, "visibility_score": 0.0},
                },
                "A": {
                    "timestamp": 3.438,
                    "confidence": 0.54,
                    "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.0998, "visibility_score": 0.0},
                },
                "L": {
                    "timestamp": 3.688,
                    "confidence": 0.503,
                    "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    "evidence": {"motion_fallback": True, "motion_score": 0.077, "visibility_score": 0.0},
                },
            }
        }
        motion_scores = {
            "selected": [
                {"timestamp": 2.938, "motion_score": 0.0682},
                {"timestamp": 3.062, "motion_score": 0.1158},
                {"timestamp": 3.125, "motion_score": 0.1178},
                {"timestamp": 3.188, "motion_score": 0.0999},
                {"timestamp": 3.438, "motion_score": 0.0998},
                {"timestamp": 3.688, "motion_score": 0.077},
                {"timestamp": 6.125, "motion_score": 0.0155},
                {"timestamp": 6.375, "motion_score": 0.0159},
                {"timestamp": 6.875, "motion_score": 0.0166},
            ]
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", validated["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift", validated["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict", validated["quality_flags"])
        self.assertIn(
            "semantic_keyframes_low_visibility_bounded_motion_fallback_ignored_no_pose_support",
            validated["quality_flags"],
        )
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_low_visibility_no_pose_support",
            validated["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", validated["quality_flags"])
        self.assertIn(
            "semantic_keyframes_weak_refinement_late_candidate_conflict_ignored_low_visibility_no_pose_support",
            validated["quality_flags"],
        )
        self.assertEqual(
            validated["semantic_candidate_tal_conflict"]["decision"],
            "ignored_low_visibility_current_motion_window_without_pose_support",
        )
        self.assertEqual(
            validated["semantic_weak_refinement_late_candidate_conflict"]["decision"],
            "ignored_low_visibility_refinement_conflict_without_pose_support",
        )

    async def test_pipeline_keeps_ordered_semantic_tal_when_refinement_rejected_against_weak_temporal_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 1.43, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.9},
                    {"frame_id": "semantic_0002", "timestamp": 1.73, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.9},
                    {"frame_id": "semantic_0003", "timestamp": 2.03, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.9},
                ],
                "video_ai": {
                    "confidence": 0.90,
                    "quality_flags": [],
                    "key_moments": {"T_takeoff_sec": 1.43, "A_air_sec": 1.73, "L_landing_sec": 2.03},
                },
            }
            refined = [
                {**resolved["selected"][0], "timestamp": 1.517, "pre_refine_timestamp": 1.43, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0174, "refinement_delta_sec": 0.087},
                {**resolved["selected"][1], "pre_refine_timestamp": 1.73, "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {
                    **resolved["selected"][2],
                    "pre_refine_timestamp": 2.03,
                    "refinement_method": "local_motion_peak_order_rejected",
                    "refinement_motion_score": 0.0162,
                    "refinement_delta_sec": 0.0,
                    "refinement_candidate_timestamp": 1.763,
                    "refinement_candidate_delta_sec": -0.267,
                    "refinement_reject_reason": "order",
                },
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                    ],
                    "T": {"frame_id": "frame_0014", "timestamp": 1.312, "confidence": 0.726, "warnings": ["takeoff_timing_window_weak", "tal_candidate_temporal_geometry_unreliable"]},
                    "A": {"frame_id": "frame_0017", "timestamp": 2.438, "confidence": 0.607, "warnings": ["confidence_missing_knee_angle_change", "tal_candidate_temporal_geometry_unreliable"]},
                    "L": {"frame_id": "frame_0018", "timestamp": 2.5, "confidence": 0.667, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined, ["semantic_keyframe_refinement_order_rejected"])),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 3.858, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=8.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertIn(
            "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn(
            "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [1.517, 1.73, 2.03])
        self.assertEqual(
            result.resolved_keyframes["semantic_refinement_rejection"]["decision"],
            "ignored_weak_temporal_geometry_candidate",
        )

    async def test_pipeline_rejects_weak_geometry_semantic_tal_when_candidate_motion_window_is_stronger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.82,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.22, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 5.70, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0003", "timestamp": 6.33, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {"confidence": 0.82, "quality_flags": [], "key_moments": {"T_takeoff_sec": 5.22, "A_air_sec": 5.7, "L_landing_sec": 6.33}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.02, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.025, "refinement_delta_sec": 0.0},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_takeoff_apex_gap_unreliable",
                        "tal_candidate_weak_geometry",
                        "tal_candidate_landing_geometry_weak",
                    ],
                    "T": {"frame_id": "frame_0017", "timestamp": 6.375, "confidence": 0.65, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                    "A": {"frame_id": "frame_0025", "timestamp": 8.188, "confidence": 0.63, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                    "L": {"frame_id": "frame_0026", "timestamp": 8.25, "confidence": 0.70, "warnings": ["tal_candidate_temporal_geometry_unreliable", "landing_geometry_weak"]},
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0014", "timestamp": 5.625, "motion_score": 0.032},
                    {"frame_id": "frame_0016", "timestamp": 6.125, "motion_score": 0.038},
                    {"frame_id": "frame_0025", "timestamp": 8.188, "motion_score": 0.20},
                    {"frame_id": "frame_0026", "timestamp": 8.25, "motion_score": 0.18},
                    {"frame_id": "frame_0032", "timestamp": 9.875, "motion_score": 0.16},
                ]
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores=motion_scores,
                        sampling_metadata=VideoSamplingMetadata(0.0, 10.0, 0.0, 10.0, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=10.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [5.22, 5.7, 6.33])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "rejected_candidate_motion_window_conflict")
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["T", "A", "L"])
        self.assertEqual(diagnostic["motion_window_conflict"]["candidate_window"]["peak_motion_score"], 0.2)
        self.assertLess(diagnostic["motion_window_conflict"]["semantic_window"]["peak_motion_score"], 0.1)

    async def test_pipeline_keeps_semantic_tal_when_stronger_candidate_window_is_core_compressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.22, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 5.80, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                    {"frame_id": "semantic_0003", "timestamp": 6.10, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {"confidence": 0.75, "quality_flags": [], "key_moments": {"T_takeoff_sec": 5.22, "A_air_sec": 5.8, "L_landing_sec": 6.1}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0391, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.0389, "refinement_delta_sec": 0.0},
            ]
            cluster = {"start_timestamp": 8.188, "end_timestamp": 8.375}
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                    ],
                    "T": {
                        "frame_id": "frame_0025",
                        "timestamp": 8.188,
                        "confidence": 0.653,
                        "evidence": {"motion_cluster_window": cluster},
                        "warnings": ["tal_candidate_temporal_geometry_unreliable"],
                    },
                    "A": {
                        "frame_id": "frame_0027",
                        "timestamp": 8.312,
                        "confidence": 0.436,
                        "evidence": {"motion_cluster_window": cluster},
                        "warnings": ["tal_candidate_temporal_geometry_unreliable"],
                    },
                    "L": {
                        "frame_id": "frame_0028",
                        "timestamp": 8.375,
                        "confidence": 0.551,
                        "evidence": {"motion_cluster_window": cluster},
                        "warnings": ["tal_candidate_temporal_geometry_unreliable"],
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.22, "motion_score": 0.0391},
                    {"frame_id": "semantic_0003", "timestamp": 6.10, "motion_score": 0.0389},
                    {"frame_id": "frame_0025", "timestamp": 8.188, "motion_score": 0.1031},
                    {"frame_id": "frame_0027", "timestamp": 8.312, "motion_score": 0.1053},
                    {"frame_id": "frame_0031", "timestamp": 9.875, "motion_score": 0.1224},
                ]
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 10.0, 0.0, 10.0, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=10.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_compressed_candidate",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [5.22, 5.8, 6.1])
        self.assertEqual(
            result.resolved_keyframes["semantic_candidate_tal_conflict"]["decision"],
            "ignored_compressed_candidate_motion_window_conflict",
        )

    async def test_pipeline_rejects_absent_landing_semantic_tal_when_candidate_motion_window_is_stronger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.78,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.12, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0002", "timestamp": 5.70, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0003", "timestamp": 6.10, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.7},
                ],
                "video_ai": {"confidence": 0.78, "quality_flags": [], "key_moments": {"T_takeoff_sec": 5.12, "A_air_sec": 5.7, "L_landing_sec": 6.1}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.018, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.019, "refinement_delta_sec": 0.0},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_landing_geometry_absent",
                    ],
                    "T": {"frame_id": "frame_0009", "timestamp": 0.562, "confidence": 0.66},
                    "A": {"frame_id": "frame_0018", "timestamp": 1.125, "confidence": 0.61},
                    "L": {"frame_id": "frame_0036", "timestamp": 2.25, "confidence": 0.58, "warnings": ["tal_candidate_landing_geometry_absent"]},
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0003", "timestamp": 0.188, "motion_score": 0.16},
                    {"frame_id": "frame_0007", "timestamp": 0.438, "motion_score": 0.20},
                    {"frame_id": "frame_0018", "timestamp": 1.125, "motion_score": 0.14},
                    {"frame_id": "semantic_0001", "timestamp": 5.12, "motion_score": 0.035},
                    {"frame_id": "semantic_0003", "timestamp": 6.10, "motion_score": 0.032},
                ]
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores=motion_scores,
                        sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=8.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_candidate_tal_conflict_ignored_weak_geometry", result.resolved_keyframes["quality_flags"])
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [5.12, 5.7, 6.1])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "rejected_candidate_motion_window_conflict")
        self.assertIn("tal_candidate_landing_geometry_absent", diagnostic["candidate_quality_flags"])

    async def test_pipeline_rejects_absent_landing_semantic_tal_when_candidate_window_beats_secondary_semantic_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.80,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 4.287, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0002", "timestamp": 4.70, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0003", "timestamp": 5.12, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.6},
                ],
                "video_ai": {"confidence": 0.80, "quality_flags": [], "key_moments": {"T_takeoff_sec": 4.287, "A_air_sec": 4.7, "L_landing_sec": 5.12}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.0638, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.0615, "refinement_delta_sec": 0.0},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_landing_geometry_absent",
                        "tal_candidate_weak_geometry",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                    ],
                    "T": {"frame_id": "frame_0009", "timestamp": 0.562, "confidence": 0.60, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                    "A": {"frame_id": "frame_0010", "timestamp": 1.125, "confidence": 0.486, "warnings": ["tal_candidate_temporal_geometry_unreliable"]},
                    "L": {"frame_id": "frame_0012", "timestamp": 2.25, "confidence": 0.35, "warnings": ["tal_candidate_landing_geometry_absent", "tal_candidate_temporal_geometry_unreliable"]},
                }
            }
            motion_scores = {
                "frame_rate": 16,
                "window_start": 0.0,
                "scores": [0.0] * 96,
            }
            for timestamp, score in (
                (0.188, 0.0890),
                (0.312, 0.0832),
                (0.438, 0.0831),
                (2.188, 0.0743),
                (4.812, 0.0638),
                (4.875, 0.0615),
            ):
                motion_scores["scores"][round(timestamp * 16)] = score

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores=motion_scores,
                        sampling_metadata=VideoSamplingMetadata(0.0, 6.0, 0.0, 6.0, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=6.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [4.287, 4.7, 5.12])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]["motion_window_conflict"]
        self.assertEqual(diagnostic["candidate_window"]["peak_motion_score"], 0.0831)
        self.assertEqual(diagnostic["semantic_window"]["peak_motion_score"], 0.0638)
        self.assertGreaterEqual(diagnostic["candidate_to_semantic_peak_ratio"], 1.2)

    async def test_pipeline_keeps_strong_video_tal_when_weak_candidate_window_only_slightly_beats_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.90,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 4.35, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0002", "timestamp": 4.85, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0003", "timestamp": 5.20, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.90},
                ],
                "video_ai": {
                    "confidence": 0.90,
                    "quality_flags": [],
                    "key_moments": {"T_takeoff_sec": 4.35, "A_air_sec": 4.85, "L_landing_sec": 5.20},
                },
            }
            refined = [
                {**resolved["selected"][0], "timestamp": 4.303, "pre_refine_timestamp": 4.35, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0278, "refinement_delta_sec": -0.047},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "timestamp": 5.12, "pre_refine_timestamp": 5.20, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0377, "refinement_delta_sec": -0.08},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                    "T": {
                        "frame_id": "frame_0009",
                        "timestamp": 0.562,
                        "confidence": 0.60,
                        "warnings": ["takeoff_reselected_from_late_plausible_candidate"],
                    },
                    "A": {
                        "frame_id": "frame_0010",
                        "timestamp": 1.125,
                        "confidence": 0.486,
                        "warnings": ["confidence_missing_knee_angle_change", "apex_local_minimum_not_clear"],
                    },
                    "L": {
                        "frame_id": "frame_0011",
                        "timestamp": 1.688,
                        "confidence": 0.35,
                        "warnings": [
                            "ankle_return_weak",
                            "knee_absorption_weak",
                            "com_descent_weak",
                            "landing_weak_contact_early_candidate_selected",
                            "landing_confidence_low",
                            "confidence_floor_from_ordered_tal",
                            "landing_geometry_weak",
                        ],
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0003", "timestamp": 0.188, "motion_score": 0.0890},
                    {"frame_id": "frame_0007", "timestamp": 0.438, "motion_score": 0.0831},
                    {"frame_id": "frame_0010", "timestamp": 1.125, "motion_score": 0.0153},
                    {"frame_id": "frame_0014", "timestamp": 4.812, "motion_score": 0.0638},
                    {"frame_id": "frame_0015", "timestamp": 4.875, "motion_score": 0.0615},
                    {"frame_id": "frame_0018", "timestamp": 5.875, "motion_score": 0.0720},
                ],
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 10.0, 0.0, 10.0, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=10.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertIn("semantic_keyframes_candidate_motion_window_conflict_ignored_weak_candidate", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [4.303, 4.85, 5.12])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_weak_candidate_motion_window_conflict")

    async def test_pipeline_keeps_full_context_video_tal_when_weak_early_candidate_window_has_stronger_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 15.40, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 15.80, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                    {"frame_id": "semantic_0003", "timestamp": 16.20, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.8},
                ],
                "video_ai": {
                    "confidence": 0.85,
                    "quality_flags": [],
                    "key_moments": {"T_takeoff_sec": 15.40, "A_air_sec": 15.80, "L_landing_sec": 16.20},
                },
            }
            refined = [
                {**resolved["selected"][0], "timestamp": 15.52, "pre_refine_timestamp": 15.40, "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0218, "refinement_delta_sec": 0.12},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0307, "refinement_delta_sec": 0.0},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                    "T": {
                        "frame_id": "frame_0009",
                        "timestamp": 0.562,
                        "confidence": 0.60,
                        "warnings": ["takeoff_reselected_from_late_plausible_candidate"],
                    },
                    "A": {
                        "frame_id": "frame_0010",
                        "timestamp": 1.125,
                        "confidence": 0.486,
                        "warnings": ["confidence_missing_knee_angle_change", "apex_local_minimum_not_clear"],
                    },
                    "L": {
                        "frame_id": "frame_0011",
                        "timestamp": 1.688,
                        "confidence": 0.35,
                        "warnings": [
                            "ankle_return_weak",
                            "knee_absorption_weak",
                            "com_descent_weak",
                            "landing_weak_contact_early_candidate_selected",
                            "landing_confidence_low",
                            "confidence_floor_from_ordered_tal",
                            "landing_geometry_weak",
                        ],
                    },
                }
            }
            motion_scores = {
                "frame_rate": 16,
                "window_start": 0.0,
                "input_window_mode": "full_context",
                "input_window_reason": "full_context",
                "input_window_duration_sec": 17.803,
                "scores": [0.0] * 285,
            }
            for timestamp, score in (
                (0.188, 0.0890),
                (0.312, 0.0832),
                (0.438, 0.0831),
                (15.52, 0.0218),
                (16.188, 0.0307),
            ):
                motion_scores["scores"][round(timestamp * 16)] = score

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 17.803, 0.0, 17.803, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=17.803,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_full_context_weak_candidate",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [15.52, 15.8, 16.2])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_full_context_weak_candidate_motion_window_conflict")

    async def test_pipeline_keeps_video_tal_when_occluded_candidate_window_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.22, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0002", "timestamp": 6.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0003", "timestamp": 7.487, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
                ],
                "video_ai": {
                    "confidence": 0.85,
                    "quality_flags": ["video_temporal_quality_retry"],
                    "key_moments": {"T_takeoff_sec": 5.22, "A_air_sec": 6.8, "L_landing_sec": 7.487},
                },
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.1069, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.0923, "refinement_delta_sec": 0.0},
            ]
            contamination = {
                "unreliable_state_count": 3,
                "window_record_count": 17,
                "unreliable_state_ratio": 0.176,
                "peak_timestamp": 2.562,
                "peak_motion_score": 0.2293,
                "landing_contact": 0.131,
            }
            cluster = {"start_timestamp": 0.688, "end_timestamp": 3.625}
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_motion_window_occlusion_contaminated",
                        "tal_candidate_motion_window_unreliable_tracker_state",
                    ],
                    "T": {
                        "frame_id": "frame_0011",
                        "timestamp": 1.688,
                        "confidence": 0.39,
                        "evidence": {
                            "motion_score": 0.0489,
                            "motion_cluster_window": cluster,
                            "motion_window_occlusion_contamination": contamination,
                        },
                        "warnings": ["motion_window_occlusion_contaminated"],
                    },
                    "A": {
                        "frame_id": "frame_0012",
                        "timestamp": 2.0,
                        "confidence": 0.38,
                        "evidence": {
                            "motion_score": 0.0491,
                            "motion_cluster_window": cluster,
                            "motion_window_occlusion_contamination": contamination,
                        },
                        "warnings": ["confidence_missing_knee_angle_change", "apex_local_minimum_not_clear", "motion_window_occlusion_contaminated"],
                    },
                    "L": {
                        "frame_id": "frame_0018",
                        "timestamp": 2.75,
                        "confidence": 0.34,
                        "evidence": {
                            "motion_score": 0.1515,
                            "motion_cluster_window": cluster,
                            "motion_window_occlusion_contamination": contamination,
                            "score_components": {"landing_contact": 0.131},
                        },
                        "warnings": ["landing_geometry_weak", "motion_window_occlusion_contaminated"],
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0011", "timestamp": 1.688, "motion_score": 0.0489},
                    {"frame_id": "frame_0015", "timestamp": 2.562, "motion_score": 0.2293},
                    {"frame_id": "frame_0016", "timestamp": 2.625, "motion_score": 0.2258},
                    {"frame_id": "frame_0017", "timestamp": 2.688, "motion_score": 0.1997},
                    {"frame_id": "frame_0023", "timestamp": 5.188, "motion_score": 0.1069},
                    {"frame_id": "frame_0026", "timestamp": 6.625, "motion_score": 0.069},
                    {"frame_id": "frame_0029", "timestamp": 7.938, "motion_score": 0.0923},
                ],
                "input_window_mode": "full_context",
                "input_window_reason": "full_context",
                "input_window_duration_sec": 10.435,
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 10.435, 0.0, 10.435, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=10.435,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [5.22, 6.8, 7.487])
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_occlusion_contaminated_candidate",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_motion_cluster_conflict"]
        self.assertEqual(diagnostic["decision"], "ignored_occlusion_contaminated_candidate_motion_window")
        self.assertEqual(diagnostic["peak_timestamp"], 2.562)

    async def test_pipeline_falls_back_when_occluded_candidate_window_has_ordered_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 3.22, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.85},
                    {"frame_id": "semantic_0002", "timestamp": 3.8, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.8},
                    {"frame_id": "semantic_0003", "timestamp": 4.52, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.85},
                ],
                "video_ai": {
                    "confidence": 0.85,
                    "quality_flags": [],
                    "key_moments": {"T_takeoff_sec": 3.2, "A_air_sec": 3.8, "L_landing_sec": 4.4},
                },
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0368, "refinement_delta_sec": 0.02},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0295, "refinement_delta_sec": 0.12},
            ]
            contamination = {
                "unreliable_state_count": 4,
                "window_record_count": 17,
                "unreliable_state_ratio": 0.235,
                "peak_timestamp": 2.562,
                "peak_motion_score": 0.2293,
                "landing_contact": 0.131,
            }
            cluster = {"start_timestamp": 0.688, "end_timestamp": 3.625}
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_motion_window_occlusion_contaminated",
                        "tal_candidate_motion_window_unreliable_tracker_state",
                    ],
                    "T": {
                        "frame_id": "frame_0011",
                        "timestamp": 1.688,
                        "confidence": 0.633,
                        "evidence": {
                            "motion_score": 0.0489,
                            "motion_cluster_window": cluster,
                            "motion_window_occlusion_contamination": contamination,
                        },
                        "warnings": ["motion_window_occlusion_contaminated"],
                    },
                    "A": {
                        "frame_id": "frame_0012",
                        "timestamp": 2.0,
                        "confidence": 0.528,
                        "evidence": {
                            "motion_score": 0.0491,
                            "motion_cluster_window": cluster,
                            "motion_window_occlusion_contamination": contamination,
                        },
                        "warnings": [
                            "confidence_missing_knee_angle_change",
                            "apex_local_minimum_not_clear",
                            "motion_window_occlusion_contaminated",
                        ],
                    },
                    "L": {
                        "frame_id": "frame_0018",
                        "timestamp": 2.75,
                        "confidence": 0.433,
                        "evidence": {
                            "motion_score": 0.1515,
                            "motion_cluster_window": cluster,
                            "motion_window_occlusion_contamination": contamination,
                            "score_components": {"landing_contact": 0.131},
                        },
                        "warnings": [
                            "ankle_return_weak",
                            "knee_absorption_weak",
                            "com_descent_weak",
                            "landing_geometry_weak",
                            "motion_window_occlusion_contaminated",
                        ],
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0011", "timestamp": 1.688, "motion_score": 0.0489},
                    {"frame_id": "frame_0015", "timestamp": 2.562, "motion_score": 0.2293},
                    {"frame_id": "frame_0016", "timestamp": 2.625, "motion_score": 0.2258},
                    {"frame_id": "frame_0017", "timestamp": 2.688, "motion_score": 0.1997},
                    {"frame_id": "frame_0018", "timestamp": 2.75, "motion_score": 0.1515},
                    {"frame_id": "semantic_t", "timestamp": 3.22, "motion_score": 0.0368},
                    {"frame_id": "semantic_l", "timestamp": 4.52, "motion_score": 0.0295},
                ],
                "input_window_mode": "full_context",
                "input_window_reason": "full_context",
                "input_window_duration_sec": 10.435,
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores=motion_scores,
                        sampling_metadata=VideoSamplingMetadata(0.0, 10.435, 0.0, 10.435, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=10.435,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "skeleton_fallback")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [1.688, 2.0, 2.75])
        self.assertIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_motion_cluster_conflict"]
        self.assertEqual(diagnostic["decision"], "rejected_occlusion_contaminated_candidate_motion_window")
        self.assertEqual([item["key"] for item in diagnostic["candidate_support"]["conflicts"]], ["T", "A", "L"])

    async def test_pipeline_keeps_semantic_tal_when_candidate_is_sparse_track_stitch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.88,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.02, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.75},
                    {"frame_id": "semantic_0002", "timestamp": 5.30, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.75},
                    {"frame_id": "semantic_0003", "timestamp": 5.733, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.75},
                ],
                "video_ai": {
                    "confidence": 0.88,
                    "quality_flags": [],
                    "key_moments": {"T_takeoff_sec": 5.02, "A_air_sec": 5.3, "L_landing_sec": 5.733},
                },
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0389, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0287, "refinement_delta_sec": 0.0},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_sparse_track_stitched",
                        "tal_candidate_unreliable_sparse_track_stitch",
                    ],
                    "T": {"frame_id": "frame_0013", "timestamp": 4.125, "confidence": 0.34, "warnings": ["tal_candidate_sparse_track_stitched"]},
                    "A": {"frame_id": "frame_0014", "timestamp": 4.188, "confidence": 0.34, "warnings": ["apex_local_minimum_not_clear", "tal_candidate_sparse_track_stitched"]},
                    "L": {"frame_id": "frame_0030", "timestamp": 9.812, "confidence": 0.34, "warnings": ["landing_geometry_weak", "tal_candidate_sparse_track_stitched"]},
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0013", "timestamp": 4.125, "motion_score": 0.0582},
                    {"frame_id": "semantic_0001", "timestamp": 5.02, "motion_score": 0.0389},
                    {"frame_id": "semantic_0003", "timestamp": 5.733, "motion_score": 0.0287},
                    {"frame_id": "frame_0030", "timestamp": 9.812, "motion_score": 0.113},
                ]
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=resolved["video_ai"],
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 10.0, 0.0, 10.0, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=10.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "video_ai_refined")
        self.assertNotIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [5.02, 5.3, 5.733])

    async def test_pipeline_rejects_semantic_tal_when_candidate_cluster_window_beats_semantic_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.72,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used", "video_temporal_quality_retry_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 3.753, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0002", "timestamp": 4.10, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.6},
                    {"frame_id": "semantic_0003", "timestamp": 4.567, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.6},
                ],
                "video_ai": {"confidence": 0.72, "quality_flags": ["video_temporal_quality_retry"], "key_moments": {"T_takeoff_sec": 3.753, "A_air_sec": 4.1, "L_landing_sec": 4.567}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0546, "refinement_delta_sec": 0.0},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0527, "refinement_delta_sec": 0.0},
            ]
            cluster = {"start_timestamp": 8.688, "end_timestamp": 9.625}
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                    "T": {
                        "frame_id": "frame_0026",
                        "timestamp": 9.25,
                        "confidence": 0.493,
                        "evidence": {"motion_cluster_window": cluster},
                        "warnings": ["knee_extension_weak", "com_ascent_weak"],
                    },
                    "A": {
                        "frame_id": "frame_0028",
                        "timestamp": 9.375,
                        "confidence": 0.444,
                        "evidence": {"motion_cluster_window": cluster},
                        "warnings": ["apex_geometry_weak"],
                    },
                    "L": {
                        "frame_id": "frame_0029",
                        "timestamp": 9.438,
                        "confidence": 0.613,
                        "evidence": {"motion_cluster_window": cluster},
                        "warnings": ["knee_absorption_weak", "com_descent_weak"],
                    },
                }
            }
            motion_scores = {
                "frame_rate": 16,
                "window_start": 0.0,
                "scores": [0.0] * 170,
            }
            for timestamp, score in (
                (3.75, 0.0546),
                (3.688, 0.0527),
                (9.25, 0.0646),
                (9.312, 0.0652),
                (9.375, 0.0620),
                (9.438, 0.0627),
                (9.75, 0.0888),
            ):
                motion_scores["scores"][round(timestamp * 16)] = score

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores=motion_scores,
                        sampling_metadata=VideoSamplingMetadata(0.0, 10.0, 0.0, 10.0, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=10.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertIn("semantic_keyframes_unreliable_candidate_motion_window_conflict", result.resolved_keyframes["quality_flags"])
        self.assertEqual(result.resolved_keyframes["source"], "skeleton_fallback")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [9.25, 9.375, 9.438])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]["motion_window_conflict"]
        self.assertEqual(diagnostic["candidate_window"]["end_sec"], 9.625)
        self.assertEqual(diagnostic["candidate_window"]["peak_motion_score"], 0.0888)
        self.assertEqual(diagnostic["semantic_window"]["peak_motion_score"], 0.0546)

    async def test_pipeline_rejects_semantic_tal_when_takeoff_anchor_takeoff_and_landing_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.80,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 4.487, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0002", "timestamp": 4.9, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0003", "timestamp": 5.3, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.7},
                ],
                "video_ai": {"confidence": 0.80, "quality_flags": [], "key_moments": {"T_takeoff_sec": 4.487, "A_air_sec": 4.9, "L_landing_sec": 5.3}},
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0174, "refinement_delta_sec": 0.337},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak_delta_rejected", "refinement_motion_score": 0.0157, "refinement_delta_sec": 0.0},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_skeleton_drifted_after_takeoff",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "tal_candidate_motion_fallback_low_precision",
                    ],
                    "T": {"frame_id": "frame_0018", "timestamp": 4.875, "confidence": 0.542, "warnings": ["keyframe_candidates_motion_fallback"]},
                    "A": {"frame_id": "frame_0019", "timestamp": 5.0, "confidence": 0.472, "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"]},
                    "L": {"frame_id": "frame_0020", "timestamp": 5.875, "confidence": 0.475, "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"]},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 9.835, 0.0, 9.835, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=9.835,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertIn("semantic_keyframes_unreliable_candidate_tal_conflict", result.resolved_keyframes["quality_flags"])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]
        self.assertTrue(diagnostic["takeoff_anchor_core_conflict"])
        self.assertEqual([item["key"] for item in diagnostic["conflicts"]], ["T", "L"])

    async def test_pipeline_rejects_semantic_tal_when_only_takeoff_conflicts_with_stronger_candidate_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.7},
                    {"frame_id": "semantic_0002", "timestamp": 8.70, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.65},
                    {"frame_id": "semantic_0003", "timestamp": 8.817, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.7},
                ],
                "video_ai": {"confidence": 0.75, "quality_flags": [], "key_moments": {"T_takeoff_sec": 8.45, "A_air_sec": 8.7, "L_landing_sec": 8.817}},
            }
            refined = [
                {
                    **resolved["selected"][0],
                    "refinement_method": "local_motion_peak_backward_delta_rejected",
                    "refinement_motion_score": 0.0422,
                    "refinement_delta_sec": 0.0,
                    "refinement_candidate_timestamp": 8.303,
                    "refinement_candidate_delta_sec": -0.147,
                    "refinement_reject_reason": "backward_delta",
                },
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.1459, "refinement_delta_sec": -0.033},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_excluded_unreliable_pose_frames"],
                    "T": {
                        "frame_id": "frame_0018",
                        "timestamp": 8.625,
                        "confidence": 0.707,
                        "evidence": {
                            "motion_score": 0.106,
                            "motion_cluster_window": {"start_timestamp": 8.625, "end_timestamp": 8.938},
                        },
                    },
                    "A": {
                        "frame_id": "frame_0019",
                        "timestamp": 8.688,
                        "confidence": 0.614,
                        "evidence": {
                            "motion_score": 0.1672,
                            "motion_cluster_window": {"start_timestamp": 8.625, "end_timestamp": 8.938},
                        },
                    },
                    "L": {
                        "frame_id": "frame_0022",
                        "timestamp": 8.875,
                        "confidence": 0.647,
                        "evidence": {
                            "motion_score": 0.1427,
                            "motion_cluster_window": {"start_timestamp": 8.625, "end_timestamp": 8.938},
                        },
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0016", "timestamp": 8.45, "motion_score": 0.0422},
                    {"frame_id": "frame_0018", "timestamp": 8.625, "motion_score": 0.106},
                    {"frame_id": "frame_0019", "timestamp": 8.688, "motion_score": 0.1672},
                    {"frame_id": "frame_0022", "timestamp": 8.875, "motion_score": 0.1427},
                ],
                "scores": [
                    {"timestamp": 8.45, "motion_score": 0.0422},
                    {"timestamp": 8.625, "motion_score": 0.106},
                    {"timestamp": 8.688, "motion_score": 0.1672},
                    {"timestamp": 8.875, "motion_score": 0.1427},
                ],
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=root / "semantic_frames",
                        video_temporal=resolved["video_ai"],
                        motion_scores=motion_scores,
                        sampling_metadata=VideoSamplingMetadata(0.0, 14.868, 0.0, 14.868, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=14.868,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertIn("semantic_keyframes_unreliable_candidate_takeoff_single_conflict", result.resolved_keyframes["quality_flags"])
        self.assertEqual(result.resolved_keyframes["source"], "skeleton_fallback")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [8.625, 8.688, 8.875])
        diagnostic = result.resolved_keyframes["semantic_candidate_tal_conflict"]["takeoff_single_conflict"]
        self.assertEqual(diagnostic["conflict"]["key"], "T")
        self.assertGreater(diagnostic["candidate_takeoff_motion_score"], diagnostic["semantic_takeoff_motion_score"])

    async def test_pipeline_uses_motion_cluster_fallback_after_ai_motion_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            bio_data = {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0028", "timestamp": 8.025, "confidence": 0.747},
                    "A": {"frame_id": "frame_0024", "timestamp": 7.775, "confidence": 0.567},
                    "L": {"frame_id": "frame_0032", "timestamp": 8.838, "confidence": 0.311},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(side_effect=lambda _video, _work, records, **_kwargs: (records, []))):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=root / "semantic_frames",
                            video_temporal=_validated_latest_retry_early_main_motion_cluster_video(),
                            motion_scores=_glide_out_motion_scores(),
                            sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 6.739, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=9.568,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "skeleton_fallback")
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertIn("video_temporal_resolver_motion_cluster_fallback_used", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["phase_code"] for item in result.resolved_keyframes["selected"][:3]], ["takeoff", "air", "landing"])

    async def test_quality_gate_retry_replaces_rejected_video_temporal_when_second_pass_is_reliable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append(
                    {"frame_id": f"semantic_{index:04d}", "timestamp": 7.2 + index * 0.2, "phase_code": phase_code, "key_moment": f"{phase_code}_moment"}
                )

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.8,
                "key_moments": {"T_takeoff_sec": 6.12, "A_air_sec": 6.45, "L_landing_sec": 6.72},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.6, "L_landing_sec": 7.85},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "video_ai_refined",
                "confidence": 0.8,
                "quality_flags": ["video_temporal_resolver_coherent_tal_motion_conflict_rejected"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.12, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.45, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 6.72, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": first_video,
            }
            accepted = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.6, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.85, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            resolve_mock = patch(
                                "app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes",
                                side_effect=[rejected, accepted],
                            )
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with resolve_mock:
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={
                                                        "selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}],
                                                        "scores": [0.1, 0.2],
                                                    },
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry", result.video_temporal["quality_flags"])
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        retry_kwargs = analyze_mock.await_args_list[1].kwargs
        self.assertIn("retry_context", retry_kwargs)
        retry_context = retry_kwargs["retry_context"]
        self.assertEqual(retry_context["rejected_key_moments"], first_video["key_moments"])
        self.assertIn("retry_instruction_hints", retry_context)
        self.assertIn("resolver_quality_flags", retry_context)
        self.assertEqual(retry_context["top_motion_records"][0]["relation_to_rejected_tal"], "after_rejected_landing")
        self.assertEqual(retry_context["rejected_selected_frames"][0]["phase_code"], "takeoff")

    async def test_quality_gate_retry_runs_for_missing_phase_segments_and_core_tal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 7.1 + index * 0.2, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_missing_phase_segments"],
                "validation": {"valid": False, "errors": ["video_temporal_missing_phase_segments"], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "key_moments": {"T_takeoff_sec": 7.25, "A_air_sec": 7.6, "L_landing_sec": 7.85},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_no_semantic_selection"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 7.25, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.6, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.85, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_missing_phase_segments", retry_context["retry_reason_flags"])
        self.assertIn("video_temporal_missing_core_tal", retry_context["retry_reason_flags"])
        self.assertIn("video_temporal_resolver_no_semantic_selection", retry_context["retry_reason_flags"])

    async def test_quality_gate_retry_runs_for_non_jump_profile_mismatch_with_no_selected_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, (phase_code, timestamp) in enumerate(
                (("spin_entry", 5.2), ("spin_main", 6.4), ("spin_exit", 7.4)),
                start=1,
            ):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": timestamp, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Axel",
                    "jump_type": "Axel",
                    "confidence": 0.85,
                },
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 4.65, "time_end": 5.5, "key_frame_hint": 5.1, "confidence": 0.85},
                    {"phase_code": "takeoff", "time_start": 5.5, "time_end": 5.8, "key_frame_hint": 5.65, "confidence": 0.85},
                    {"phase_code": "air", "time_start": 5.8, "time_end": 6.1, "key_frame_hint": 5.95, "confidence": 0.85},
                    {"phase_code": "landing", "time_start": 6.1, "time_end": 6.4, "key_frame_hint": 6.25, "confidence": 0.85},
                ],
                "key_moments": {"T_takeoff_sec": 5.65, "A_air_sec": 5.95, "L_landing_sec": 6.25},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.82,
                "action_confirmation": {
                    "action_family": "spin",
                    "confirmed_action": "spin",
                    "jump_type": "",
                    "confidence": 0.86,
                },
                "phase_segments": [
                    {"phase_code": "spin_entry", "time_start": 4.65, "time_end": 5.8, "key_frame_hint": 5.2, "confidence": 0.82},
                    {"phase_code": "spin_main", "time_start": 5.8, "time_end": 7.0, "key_frame_hint": 6.4, "confidence": 0.84},
                    {"phase_code": "spin_exit", "time_start": 7.0, "time_end": 8.2, "key_frame_hint": 7.4, "confidence": 0.80},
                ],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "video_ai_refined",
                "confidence": 0.85,
                "quality_flags": ["video_temporal_resolver_no_selected_frames"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "video_ai_refined",
                "confidence": 0.82,
                "quality_flags": [],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 5.2, "phase_code": "spin_entry", "key_moment": None},
                    {"frame_id": "semantic_0002", "timestamp": 6.4, "phase_code": "spin_main", "key_moment": None},
                    {"frame_id": "semantic_0003", "timestamp": 7.4, "phase_code": "spin_exit", "key_moment": None},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=_visible_person_candidates(),
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="spin",
                                                    action_subtype=None,
                                                    motion_scores={"selected": []},
                                                    analysis_profile="spin",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry", result.video_temporal["quality_flags"])
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_profile_mismatch_retryable", retry_context["retry_reason_flags"])
        self.assertEqual(retry_context["requested_analysis_profile"], "spin")
        self.assertEqual(retry_context["provider_action_family"], "jump")
        self.assertEqual(retry_context["profile_mismatch"], {"requested": "spin", "provider_action_family": "jump"})
        self.assertTrue(any("spin_entry/spin_main/spin_exit" in hint for hint in retry_context["retry_instruction_hints"]))

    async def test_resolver_uses_detected_source_duration_when_cached_retry_lacks_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.80,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {
                    "action_family": "spin",
                    "confirmed_action": "spin",
                    "confidence": 0.85,
                },
                "phase_segments": [
                    {"phase_code": "spin_entry", "time_start": 5.9, "time_end": 7.1, "key_frame_hint": 6.5, "confidence": 0.8},
                    {"phase_code": "spin_main", "time_start": 7.1, "time_end": 8.5, "key_frame_hint": 7.8, "confidence": 0.65},
                ],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": [],
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied_records = []
                for index, record in enumerate(records, start=1):
                    path = output_dir / f"{prefix}_{index:04d}.jpg"
                    path.write_bytes(b"semantic")
                    paths.append(path)
                    copied_records.append({**record, "frame_id": f"{prefix}_{index:04d}"})
                return paths, copied_records

            with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", return_value=9.101667):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(side_effect=lambda *args, **kwargs: (args[2], []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(2.0, 10.0, 2.0, 10.0, 16.0, 30.0, False),
                            analysis_profile="spin",
                            video_duration_sec=None,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertNotIn("semantic_frame_extract_failed", result.resolved_keyframes["quality_flags"])
        self.assertEqual([item["phase_code"] for item in result.resolved_keyframes["selected"]], ["spin_entry", "spin_main", "spin_exit"])
        self.assertEqual(result.resolved_keyframes["selected"][2]["timestamp"], 8.761)

    async def test_quality_gate_retry_runs_for_retryable_low_confidence_jump_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, phase_code in enumerate(("takeoff", "air", "landing"), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append({"frame_id": f"semantic_{index:04d}", "timestamp": 6.2 + index * 0.25, "phase_code": phase_code})

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.50,
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 6.25, "time_end": 6.65, "confidence": 0.6},
                    {"phase_code": "air", "time_start": 6.65, "time_end": 7.05, "confidence": 0.5},
                    {"phase_code": "landing", "time_start": 7.05, "time_end": 7.35, "confidence": 0.55},
                ],
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_not_high_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.70,
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": [],
                "validation": {"valid": True, "errors": [], "warnings": []},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.50,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": first_video,
            }
            accepted = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 6.85, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.15, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[rejected, accepted]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(accepted["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry", result.video_temporal["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_low_confidence_retryable", retry_context["retry_reason_flags"])
        self.assertEqual(retry_context["rejected_key_moments"], first_video["key_moments"])

    async def test_quality_gate_retry_skips_very_low_confidence_jump_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.20,
                "key_moments": {"T_takeoff_sec": 1.0, "A_air_sec": 1.2, "L_landing_sec": 1.4},
                "quality_flags": ["video_temporal_low_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.20,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": first_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(return_value=first_video)
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=rejected):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=root / "semantic_frames",
                                        sampling_metadata=VideoSamplingMetadata(0.15, 4.75, 0.15, 4.75, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": []},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 1)
        self.assertNotIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])

    async def test_quality_gate_retry_runs_for_severe_occlusion_low_confidence_above_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.40,
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": ["severe_occlusion", "video_temporal_low_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.35,
                "key_moments": {"T_takeoff_sec": 6.45, "A_air_sec": 6.85, "L_landing_sec": 7.15},
                "quality_flags": ["severe_occlusion", "video_temporal_low_confidence"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            rejected = {
                "source": "skeleton_fallback",
                "confidence": 0.40,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": first_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=rejected):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=semantic_dir,
                                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": []},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_low_confidence_retryable", retry_context["retry_reason_flags"])

    async def test_quality_gate_retry_uses_low_confidence_retry_when_tal_is_coherent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            semantic_paths = []
            semantic_records = []
            for index, (phase_code, timestamp) in enumerate((("takeoff", 6.75), ("air", 7.05), ("landing", 7.35)), start=1):
                path = semantic_dir / f"semantic_{index:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"semantic")
                semantic_paths.append(path)
                semantic_records.append(
                    {"frame_id": f"semantic_{index:04d}", "timestamp": timestamp, "phase_code": phase_code, "key_moment": f"{phase_code}_moment"}
                )

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.30,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "validation": {"valid": False, "errors": [], "warnings": ["video_temporal_low_confidence"]},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.50,
                "fallback_recommendation": "manual_review",
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 4.65, "time_end": 6.45, "key_frame_hint": 5.65, "confidence": 0.8},
                    {"phase_code": "takeoff", "time_start": 6.45, "time_end": 6.85, "key_frame_hint": 6.65, "confidence": 0.7},
                    {"phase_code": "air", "time_start": 6.85, "time_end": 7.25, "key_frame_hint": 7.05, "confidence": 0.6},
                    {"phase_code": "landing", "time_start": 7.25, "time_end": 7.45, "key_frame_hint": 7.35, "confidence": 0.6},
                    {"phase_code": "glide_out", "time_start": 7.45, "time_end": 9.25, "key_frame_hint": 8.15, "confidence": 0.7},
                ],
                "key_moments": {"T_takeoff_sec": 6.75, "A_air_sec": 7.05, "L_landing_sec": 7.35},
                "quality_flags": [
                    "video_temporal_low_confidence",
                    "video_temporal_not_high_confidence",
                    "video_temporal_fallback_recommended",
                    "video_temporal_quality_retry",
                ],
                "validation": {
                    "valid": False,
                    "errors": [],
                    "warnings": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                },
            }
            first_resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.30,
                "quality_flags": [
                    "video_temporal_resolver_low_video_confidence",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                ],
                "video_ai": first_video,
            }
            retry_resolved = {
                "source": "blended",
                "confidence": 0.50,
                "quality_flags": [
                    "video_temporal_resolver_video_fallback_recommended",
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_moderate_confidence_tal_used",
                    "video_temporal_resolver_video_validation_not_clean",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 6.75, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                    {"frame_id": "semantic_0002", "timestamp": 7.05, "phase_code": "air", "key_moment": "A_air_sec"},
                    {"frame_id": "semantic_0003", "timestamp": 7.35, "phase_code": "landing", "key_moment": "L_landing_sec"},
                ],
                "video_ai": retry_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", side_effect=[first_resolved, retry_resolved]):
                                    with patch(
                                        "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                                        AsyncMock(return_value=(retry_resolved["selected"], [])),
                                    ):
                                        with patch(
                                            "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                                            AsyncMock(return_value=(semantic_paths, semantic_records)),
                                        ):
                                            with patch(
                                                "app.services.semantic_keyframe_pipeline.detect_person_candidates",
                                                return_value=[{"bbox": {"x": 0.4, "y": 0.3, "width": 0.07, "height": 0.18}, "confidence": 0.8}],
                                            ):
                                                result = await run_semantic_keyframe_pipeline(
                                                    video_path=video_path,
                                                    work_dir=root,
                                                    semantic_frames_dir=semantic_dir,
                                                    sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                                    action_type="jump",
                                                    action_subtype=None,
                                                    motion_scores={"selected": [{"frame_id": "frame_0024", "timestamp": 7.775, "motion_score": 0.2166}]},
                                                    analysis_profile="jump",
                                                    precheck=False,
                                                )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.resolved_keyframes["source"], "blended")
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_used", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_missing_core_tal", retry_context["retry_reason_flags"])
        self.assertIn("video_temporal_resolver_partial_skeleton_fallback", retry_context["retry_reason_flags"])

    async def test_quality_gate_retry_runs_for_partial_skeleton_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            first_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_missing_phase_segments"],
                "validation": {"valid": False, "errors": ["video_temporal_missing_phase_segments"], "warnings": []},
            }
            retry_video = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.70,
                "phase_segments": [],
                "key_moments": {"T_takeoff_sec": None, "A_air_sec": None, "L_landing_sec": None},
                "quality_flags": ["video_temporal_missing_phase_segments"],
                "validation": {"valid": False, "errors": ["video_temporal_missing_phase_segments"], "warnings": []},
            }
            partial_fallback = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_no_semantic_selection",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"frame_id": "semantic_0001", "timestamp": 8.025, "phase_code": "takeoff", "key_moment": "T_takeoff_sec"},
                ],
                "video_ai": first_video,
            }

            with patch("app.services.semantic_keyframe_pipeline.precheck_video", AsyncMock(return_value=None)):
                with patch("app.services.semantic_keyframe_pipeline.cut_action_window_ai_clip", AsyncMock(return_value=root / "action_window_ai.mp4")):
                    with patch("app.services.semantic_keyframe_pipeline.detect_video_duration", side_effect=[9.568, 4.6, 9.568, 4.6]):
                        with patch("app.services.semantic_keyframe_pipeline.detect_video_fps", return_value=15.0):
                            analyze_mock = AsyncMock(side_effect=[first_video, retry_video])
                            with patch("app.services.semantic_keyframe_pipeline.analyze_video_temporal", analyze_mock):
                                with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=partial_fallback):
                                    result = await run_semantic_keyframe_pipeline(
                                        video_path=video_path,
                                        work_dir=root,
                                        semantic_frames_dir=semantic_dir,
                                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                                        action_type="jump",
                                        action_subtype=None,
                                        motion_scores={"selected": []},
                                        analysis_profile="jump",
                                        precheck=False,
                                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(analyze_mock.await_count, 2)
        self.assertIn("video_temporal_quality_retry_rejected", result.resolved_keyframes["quality_flags"])
        retry_context = analyze_mock.await_args_list[1].kwargs["retry_context"]
        self.assertIn("video_temporal_resolver_partial_skeleton_fallback", retry_context["retry_reason_flags"])

    async def test_partial_core_semantic_candidates_are_extracted_as_diagnostics_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [semantic_dir / "partial_semantic_0001.jpg", semantic_dir / "partial_semantic_0002.jpg"]
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 5.9,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "confidence": 0.653,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                },
                {
                    "frame_id": "partial_semantic_0002",
                    "timestamp": 7.525,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "confidence": 0.792,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                },
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "fallback_recommendation": "use_sampled_frames",
                "quality_flags": ["video_temporal_fallback_recommended"],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_partial_skeleton_fallback",
                    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 5.838,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "confidence": 0.42,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 5.9,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "confidence": 0.653,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 7.525,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "confidence": 0.792,
                    },
                ],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([item["key_moment"] for item in records], ["A_air_sec", "L_landing_sec"])
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=9.568,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.semantic_records, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_partial_core_diagnostics_merge_missing_video_temporal_tal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [
                semantic_dir / "partial_semantic_0001.jpg",
                semantic_dir / "partial_semantic_0002.jpg",
                semantic_dir / "partial_semantic_0003.jpg",
            ]
            partial_records = [
                {"frame_id": f"partial_semantic_{index:04d}", **record}
                for index, record in enumerate(
                    (
                        {"timestamp": 6.65, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.5},
                        {"timestamp": 5.9, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.653},
                        {"timestamp": 7.525, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.792},
                    ),
                    start=1,
                )
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "use_sampled_frames",
                "quality_flags": ["video_temporal_low_confidence"],
                "key_moments": {"T_takeoff_sec": 6.65, "A_air_sec": 7.05, "L_landing_sec": 7.45},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.45, "time_end": 6.85, "confidence": 0.5},
                    {"phase_code": "air", "phase_label": "air", "time_start": 6.85, "time_end": 7.25, "confidence": 0.4},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 7.25, "time_end": 7.65, "confidence": 0.5},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": [
                    "video_temporal_resolver_low_video_confidence",
                    "video_temporal_resolver_partial_skeleton_fallback",
                ],
                "selected": [
                    {"timestamp": 5.9, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.653},
                    {"timestamp": 7.525, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.792},
                ],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([item["key_moment"] for item in records], ["T_takeoff_sec", "A_air_sec", "L_landing_sec"])
                self.assertEqual([item["timestamp"] for item in records], [6.65, 5.9, 7.525])
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(4.65, 9.25, 4.65, 9.25, 16.0, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=9.568,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_low_confidence_video_temporal_tal_extracts_partial_diagnostic_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [
                semantic_dir / "partial_semantic_0001.jpg",
                semantic_dir / "partial_semantic_0002.jpg",
                semantic_dir / "partial_semantic_0003.jpg",
            ]
            partial_records = [
                {"frame_id": f"partial_semantic_{index:04d}", **record}
                for index, record in enumerate(
                    (
                        {"timestamp": 4.45, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.2},
                        {"timestamp": 5.15, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.2},
                        {"timestamp": 5.65, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.2},
                    ),
                    start=1,
                )
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.2,
                "fallback_recommendation": "manual_review",
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 4.45, "A_air_sec": 5.15, "L_landing_sec": 5.65},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 4.15, "time_end": 4.85, "confidence": 0.2},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.85, "time_end": 5.45, "confidence": 0.2},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 5.45, "time_end": 5.95, "confidence": 0.2},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.2,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([item["key_moment"] for item in records], ["T_takeoff_sec", "A_air_sec", "L_landing_sec"])
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(2.65, 7.25, 2.65, 7.25, 6.739, 30.0, False),
                        analysis_profile="jump",
                        video_duration_sec=8.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_low_confidence_jump_partial_tal_promotes_when_visual_check_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(result.partial_semantic_frames, [])
        self.assertNotIn("partial_selected", result.resolved_keyframes)
        self.assertIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_advisory_low_confidence_overridden", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_low_confidence_zoomed_visual_check", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_low_confidence_visual_tal_promoted"] * 3,
        )
        self.assertEqual(
            [item["semantic_visibility"]["status"] for item in result.resolved_keyframes["selected"]],
            ["target_visible"] * 3,
        )

    async def test_low_confidence_jump_partial_tal_promotes_when_zoomed_visual_check_finds_small_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            def fake_candidates(_: Path, *, min_confidence: float = 0.25, include_zoomed_small_targets: bool = False):
                self.assertEqual(min_confidence, 0.25)
                if not include_zoomed_small_targets:
                    return []
                return [
                    {
                        "bbox": {"x": 0.45, "y": 0.49, "width": 0.034, "height": 0.10},
                        "confidence": 0.52,
                        "source": "yolo_zoomed_content",
                        "area": 0.0034,
                    }
                ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(len(result.semantic_frames), 3)
        self.assertEqual(
            [item["semantic_visibility"]["visibility_check_method"] for item in result.resolved_keyframes["selected"]],
            ["zoomed_yolo"] * 3,
        )
        self.assertIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_low_confidence_jump_partial_tal_repairs_nearby_zoomed_visible_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }
            inspected_names: list[str] = []
            repair_detected = False

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = []
                copied = []
                for index, record in enumerate(records, start=1):
                    frame_id = f"{prefix}_{index:04d}"
                    if prefix == "repair":
                        frame_id = f"{prefix}_{index:04d}_{int(float(record['timestamp']) * 1000):08d}"
                    path = output_dir / f"{frame_id}.jpg"
                    path.write_bytes(b"frame")
                    paths.append(path)
                    copied.append({**record, "frame_id": frame_id})
                return paths, copied

            def fake_candidates(frame_path: Path, *, min_confidence: float = 0.25, include_zoomed_small_targets: bool = False):
                nonlocal repair_detected
                inspected_names.append(frame_path.name)
                if not include_zoomed_small_targets:
                    return []
                if frame_path.name.startswith("repair_"):
                    repair_detected = True
                    return _visible_person_candidates()
                if frame_path.name in {"semantic_0001.jpg", "semantic_0002.jpg"} or (
                    frame_path.name == "semantic_0003.jpg" and repair_detected
                ):
                    return _visible_person_candidates()
                return []

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=fake_extract)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("video_temporal_resolver_low_confidence_visual_repair_used", result.resolved_keyframes["quality_flags"])
        landing = result.resolved_keyframes["selected"][2]
        self.assertEqual(landing["frame_id"], "semantic_0003")
        self.assertEqual(landing["semantic_visibility"]["status"], "target_visible")
        self.assertEqual(landing["visual_repair_method"], "nearby_zoomed_yolo_visible_frame")
        self.assertIn("semantic_0003.jpg", inspected_names)
        self.assertTrue(any(name.startswith("repair_") for name in inspected_names))

    async def test_low_confidence_jump_partial_tal_stays_partial_when_no_visual_target_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=[]):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_low_confidence_jump_partial_tal_stays_partial_when_visual_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Axel", "confidence": 0.85},
                "quality_flags": ["video_temporal_low_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.05, "A_air_sec": 3.65, "L_landing_sec": 4.05},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.65, "time_end": 3.25, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.25, "time_end": 3.95, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.95, "time_end": 4.95, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": ["video_temporal_resolver_low_video_confidence"],
                "selected": [],
                "video_ai": video_temporal,
            }
            occluded = [
                {"bbox": {"x": 0.38, "y": 0.19, "width": 0.28, "height": 0.79}, "confidence": 0.67, "area": 0.2212},
                {"bbox": {"x": 0.42, "y": 0.28, "width": 0.06, "height": 0.19}, "confidence": 0.35, "area": 0.0114},
            ]

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=occluded):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(1.15, 5.75, 1.15, 5.75, 16.0, 30.0, False),
                            analysis_profile="jump",
                            video_duration_sec=5.75,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_phase_range_video_tal_promotes_over_low_visibility_motion_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.8,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.82},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.45, "A_air_sec": 3.75, "L_landing_sec": 4.0},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 3.3, "time_end": 3.6, "confidence": 0.8},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.6, "time_end": 3.9, "confidence": 0.75},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.9, "time_end": 4.2, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.8,
                "quality_flags": [
                    "semantic_keyframes_unreliable_after_refinement",
                    "semantic_keyframes_unreliable_candidate_tal_conflict",
                    "semantic_keyframes_unreliable_weak_refinement_late_candidate_conflict",
                    "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                    "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                    "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                ],
                "selected": [
                    {
                        "frame_id": "partial_semantic_0001",
                        "timestamp": 3.45,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_motion_peak",
                        "confidence": 0.8,
                        "phase_time_start": 3.3,
                        "phase_time_end": 3.6,
                    },
                    {
                        "frame_id": "partial_semantic_0002",
                        "timestamp": 3.75,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_hint",
                        "confidence": 0.75,
                        "phase_time_start": 3.6,
                        "phase_time_end": 3.9,
                    },
                    {
                        "frame_id": "partial_semantic_0003",
                        "timestamp": 4.267,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_motion_peak",
                        "confidence": 0.8,
                        "phase_time_start": 3.9,
                        "phase_time_end": 4.2,
                    },
                ],
                "video_ai": video_temporal,
                "semantic_low_visibility_bounded_motion_fallback_drift": {
                    "decision": "rejected_low_visibility_bounded_motion_fallback_drift",
                    "conflicts": [
                        {"key": "T", "semantic_timestamp": 3.45, "candidate_timestamp": 0.625, "delta_sec": 2.825},
                        {"key": "A", "semantic_timestamp": 3.75, "candidate_timestamp": 0.812, "delta_sec": 2.938},
                    ],
                },
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "tal_candidate_motion_fallback_low_precision",
                    ],
                    "T": {
                        "frame_id": "frame_0009",
                        "timestamp": 0.625,
                        "confidence": 0.57,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback"],
                    },
                    "A": {
                        "frame_id": "frame_0010",
                        "timestamp": 0.812,
                        "confidence": 0.486,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                    },
                    "L": {
                        "frame_id": "frame_0015",
                        "timestamp": 1.438,
                        "confidence": 0.501,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"],
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 6.568, 0.0, 6.568, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=6.568,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [3.45, 3.75, 4.267])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_phase_range_visual_tal_promoted"] * 3,
        )
        self.assertIn("semantic_keyframes_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_candidate_tal_conflict", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_motion_fallback", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose", result.resolved_keyframes["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("partial_selected", result.resolved_keyframes)
        self.assertEqual(
            result.resolved_keyframes["semantic_phase_range_visual_promotion"]["decision"],
            "promoted_video_phase_range_tal_over_low_visibility_motion_fallback",
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_phase_range_visual_promotion"]["low_visibility_motion_fallback_keys"],
            ["A", "L", "T"],
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_low_visibility_bounded_motion_fallback_drift"]["decision"],
            "ignored_after_tracker_final_loss_visual_tal_promotion",
        )

    async def test_phase_range_video_tal_promotes_over_takeoff_anchor_low_visibility_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.8},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 1.938, "A_air_sec": 2.5, "L_landing_sec": 2.75},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 1.8, "time_end": 2.3, "confidence": 0.7},
                    {"phase_code": "air", "phase_label": "air", "time_start": 2.3, "time_end": 2.7, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 2.7, "time_end": 3.0, "confidence": 0.7},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.75,
                "quality_flags": [
                    "semantic_keyframes_unreliable_after_refinement",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                    "video_temporal_quality_retry_motion_cluster_conflict",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 1.938,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_motion_peak",
                        "confidence": 0.7,
                        "phase_time_start": 1.8,
                        "phase_time_end": 2.3,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 2.5,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_hint",
                        "confidence": 0.7,
                        "phase_time_start": 2.3,
                        "phase_time_end": 2.7,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 2.75,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_motion_peak",
                        "confidence": 0.7,
                        "phase_time_start": 2.7,
                        "phase_time_end": 3.0,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "keyframe_candidates_motion_fallback_low_visibility_weak_boundary",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_motion_fallback_low_visibility_weak_boundary",
                        "tal_candidate_skeleton_drifted_after_takeoff",
                    ],
                    "motion_fallback_low_visibility_weak_boundary": {
                        "reason": "takeoff_anchor_low_visibility_motion_only_boundary",
                        "low_visibility_motion_roles": ["A", "L"],
                    },
                    "T": {
                        "frame_id": "frame_0005",
                        "timestamp": 0.312,
                        "confidence": 0.614,
                        "evidence": {
                            "motion_score": 0.3185,
                            "visibility_score": 0.935,
                            "motion_fallback_low_visibility_weak_boundary": {
                                "reason": "takeoff_anchor_low_visibility_motion_only_boundary",
                                "low_visibility_motion_roles": ["A", "L"],
                            },
                            "score_components": {
                                "pose_visibility": 0.935,
                                "takeoff_timing": 0.0,
                                "takeoff_joint_extension_ascent": 0.0,
                                "takeoff_event": 0.277,
                            },
                        },
                        "warnings": [
                            "knee_extension_weak",
                            "takeoff_timing_window_weak",
                            "keyframe_candidates_motion_fallback",
                            "tal_candidate_motion_fallback_low_visibility_weak_boundary",
                        ],
                    },
                    "A": {
                        "frame_id": "frame_0008",
                        "timestamp": 0.625,
                        "confidence": 0.34,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted", "tal_candidate_motion_fallback_low_visibility_weak_boundary"],
                    },
                    "L": {
                        "frame_id": "frame_0011",
                        "timestamp": 1.062,
                        "confidence": 0.34,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted", "tal_candidate_motion_fallback_low_visibility_weak_boundary"],
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 6.8, 0.0, 6.8, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=6.8,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [1.938, 2.5, 2.75])
        self.assertIn("semantic_keyframes_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            result.resolved_keyframes["semantic_phase_range_visual_promotion"]["promotion_context"],
            "takeoff_anchor_low_visibility_boundary",
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_phase_range_visual_promotion"]["low_visibility_motion_fallback_keys"],
            ["A", "L"],
        )

    async def test_distant_full_context_phase_range_tal_promotes_over_compressed_motion_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.6,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "confidence": 0.6},
                "quality_flags": [
                    "distance_too_far",
                    "low_resolution",
                    "video_temporal_not_high_confidence",
                    "video_temporal_fallback_recommended",
                ],
                "key_moments": {"T_takeoff_sec": 7.6, "A_air_sec": 7.9, "L_landing_sec": 8.2},
                "phase_segments": [
                    {"phase_code": "approach", "phase_label": "approach", "time_start": 0.0, "time_end": 6.5, "confidence": 0.7},
                    {"phase_code": "preparation", "phase_label": "preparation", "time_start": 6.5, "time_end": 7.5, "confidence": 0.6},
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 7.5, "time_end": 7.8, "confidence": 0.6},
                    {"phase_code": "air", "phase_label": "air", "time_start": 7.8, "time_end": 8.1, "confidence": 0.5},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 8.1, "time_end": 8.4, "confidence": 0.6},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.6,
                "quality_flags": [
                    "video_temporal_resolver_video_fallback_recommended",
                    "video_temporal_resolver_advisory_fallback_overridden",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_moderate_confidence_tal_used",
                    "video_temporal_resolver_video_validation_not_clean",
                    "semantic_keyframes_tracker_final_loss_motion_fallback_ignored",
                    "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 7.6,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.6,
                        "phase_time_start": 7.5,
                        "phase_time_end": 7.8,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 7.9,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.5,
                        "phase_time_start": 7.8,
                        "phase_time_end": 8.1,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 8.2,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.6,
                        "phase_time_start": 8.1,
                        "phase_time_end": 8.4,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                        "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 3.188, "end_timestamp": 4.662},
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 3.188,
                        "confidence": 0.54,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    },
                    "A": {
                        "frame_id": "frame_0013",
                        "timestamp": 3.25,
                        "confidence": 0.427,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    },
                    "L": {
                        "frame_id": "frame_0014",
                        "timestamp": 3.312,
                        "confidence": 0.435,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    },
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 10.235, 0.0, 10.235, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=10.235,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [7.6, 7.9, 8.2])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_distant_full_context_visual_tal_promoted"] * 3,
        )
        self.assertIn("semantic_keyframes_distant_full_context_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose", result.resolved_keyframes["quality_flags"])

    async def test_phase_range_video_tal_promotes_over_weak_temporal_geometry_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.8},
                "quality_flags": ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 4.1, "A_air_sec": 4.5, "L_landing_sec": 4.9},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 3.9, "time_end": 4.3, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.3, "time_end": 4.7, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 4.7, "time_end": 5.1, "confidence": 0.7},
                ],
            }
            resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": [
                    "distance",
                    "occasional_occlusion",
                    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_partial_core_frames_available",
                    "video_temporal_quality_retry_rejected",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 4.1,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.75,
                        "phase_time_start": 3.9,
                        "phase_time_end": 4.3,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 4.5,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 4.3,
                        "phase_time_end": 4.7,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.9,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 4.7,
                        "phase_time_end": 5.1,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_takeoff_apex_gap_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                        "tal_candidate_confidence_low",
                    ],
                    "T": {
                        "frame_id": "frame_0027",
                        "timestamp": 5.875,
                        "confidence": 0.34,
                        "warnings": [
                            "knee_extension_weak",
                            "takeoff_timing_window_weak",
                            "tal_candidate_temporal_geometry_unreliable",
                            "tal_candidate_compressed_temporal_geometry",
                        ],
                    },
                    "A": {
                        "frame_id": "frame_0031",
                        "timestamp": 7.688,
                        "confidence": 0.34,
                        "warnings": [
                            "confidence_missing_knee_angle_change",
                            "apex_local_minimum_not_clear",
                            "tal_candidate_temporal_geometry_unreliable",
                            "tal_candidate_compressed_temporal_geometry",
                        ],
                    },
                    "L": {
                        "frame_id": "frame_0032",
                        "timestamp": 7.75,
                        "confidence": 0.34,
                        "warnings": [
                            "ankle_return_weak",
                            "knee_absorption_weak",
                            "com_descent_weak",
                            "landing_geometry_weak",
                            "tal_candidate_temporal_geometry_unreliable",
                            "tal_candidate_compressed_temporal_geometry",
                        ],
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=8.0,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [4.1, 4.5, 4.9])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_phase_range_visual_tal_promoted"] * 3,
        )
        self.assertIn("semantic_keyframes_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            result.resolved_keyframes["semantic_phase_range_visual_promotion"]["promotion_context"],
            "weak_temporal_geometry_candidate",
        )

    async def test_phase_range_video_tal_does_not_promote_over_late_pose_core_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.75,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.8},
                "quality_flags": ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 2.9, "A_air_sec": 3.3, "L_landing_sec": 3.6},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.8, "time_end": 3.1, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.1, "time_end": 3.5, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.5, "time_end": 3.8, "confidence": 0.7},
                ],
            }
            resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                    "semantic_keyframes_unreliable_candidate_tal_conflict",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_partial_core_frames_available",
                    "video_temporal_quality_retry_rejected",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 2.9,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.75,
                        "phase_time_start": 2.8,
                        "phase_time_end": 3.1,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 3.3,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 3.1,
                        "phase_time_end": 3.5,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 3.6,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 3.5,
                        "phase_time_end": 3.8,
                    },
                ],
                "video_ai": video_temporal,
                "semantic_candidate_tal_conflict": {
                    "conflicts": [
                        {"key": "T", "semantic_timestamp": 2.9, "candidate_timestamp": 4.188, "delta_sec": -1.288},
                        {"key": "A", "semantic_timestamp": 3.3, "candidate_timestamp": 4.812, "delta_sec": -1.512},
                        {"key": "L", "semantic_timestamp": 3.6, "candidate_timestamp": 4.875, "delta_sec": -1.275},
                    ],
                    "decision": "rejected_late_pose_core_candidate_conflict",
                },
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_late_pose_core_reselected",
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_confidence_low",
                    ],
                    "T": {"frame_id": "frame_0067", "timestamp": 4.188, "confidence": 0.43},
                    "A": {"frame_id": "frame_0077", "timestamp": 4.812, "confidence": 0.41},
                    "L": {"frame_id": "frame_0078", "timestamp": 4.875, "confidence": 0.42},
                }
            }

            self.assertFalse(
                _phase_range_motion_fallback_jump_partial_can_be_promoted(
                    resolved,
                    resolved["selected"],
                    analysis_profile="jump",
                    bio_data=bio_data,
                )
            )

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 6.568, 0.0, 6.568, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=6.568,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertEqual(result.resolved_keyframes["source"], "blended")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [2.9, 3.3, 3.6])
        flags = result.resolved_keyframes["quality_flags"]
        self.assertIn("semantic_keyframes_phase_range_visual_promotion_blocked_late_pose_core_conflict", flags)
        self.assertIn("semantic_keyframes_unreliable_candidate_tal_conflict", flags)
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", flags)
        self.assertNotIn("semantic_keyframes_phase_range_visual_tal_promoted", flags)
        self.assertNotIn("video_temporal_resolver_phase_range_visual_tal_promoted", flags)
        self.assertNotIn("semantic_phase_range_visual_promotion", result.resolved_keyframes)
        self.assertEqual(
            result.resolved_keyframes["semantic_candidate_tal_conflict"]["decision"],
            "rejected_late_pose_core_candidate_conflict",
        )

    async def test_retry_tail_motion_aligned_partial_tal_promotes_over_weak_temporal_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal, resolved, bio_data, motion_scores = _retry_tail_motion_aligned_phase_range_fixture()

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores=motion_scores,
                            sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=8.0,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [5.25, 5.5, 5.7])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_phase_range_visual_tal_promoted"] * 3,
        )
        flags = result.resolved_keyframes["quality_flags"]
        self.assertIn("semantic_keyframes_phase_range_visual_tal_promoted", flags)
        self.assertIn("semantic_keyframes_retry_tail_motion_aligned_visual_tal_promoted", flags)
        self.assertIn("video_temporal_resolver_phase_range_visual_tal_promoted", flags)
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", flags)
        self.assertNotIn("video_temporal_resolver_coherent_tal_motion_conflict_rejected", flags)
        self.assertNotIn("video_temporal_resolver_coherent_tal_retry_tail_motion_conflict", flags)
        promotion = result.resolved_keyframes["semantic_phase_range_visual_promotion"]
        self.assertEqual(
            promotion["decision"],
            "promoted_retry_tail_motion_aligned_video_tal_over_weak_temporal_geometry_candidate",
        )
        self.assertEqual(
            promotion["promotion_context"],
            "retry_tail_motion_aligned_weak_temporal_geometry_candidate",
        )
        self.assertEqual(
            promotion["retry_tail_motion_aligned_support"]["support_mode"],
            "retry_tail_motion_aligned_visual_tal_over_weak_temporal_geometry_candidate",
        )
        self.assertEqual(promotion["retry_tail_motion_aligned_support"]["peak_timestamp"], 4.812)

    async def test_retry_tail_motion_aligned_partial_tal_does_not_promote_foreground_occluded_takeoff(self) -> None:
        video_temporal, resolved, bio_data, motion_scores = _retry_tail_motion_aligned_phase_range_fixture(occluded=True)

        support = _retry_tail_motion_aligned_jump_partial_promotion_support(
            resolved,
            resolved["selected"],
            motion_scores,
            analysis_profile="jump",
            bio_data=bio_data,
        )

        self.assertIsNone(support)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_foreground_occluded_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores=motion_scores,
                            sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=8.0,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertNotIn("semantic_keyframes_retry_tail_motion_aligned_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_phase_range_video_tal_rejects_foreground_motion_cluster_when_core_motion_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "confidence": 0.8},
                "quality_flags": ["distance", "video_temporal_not_high_confidence"],
                "key_moments": {"T_takeoff_sec": 5.0, "A_air_sec": 5.3, "L_landing_sec": 5.6},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 4.8, "time_end": 5.2, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 5.2, "time_end": 5.5, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 5.5, "time_end": 6.0, "confidence": 0.75},
                ],
            }
            resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_resolver_moderate_confidence_tal_used",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 4.887,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.75,
                        "phase_time_start": 4.8,
                        "phase_time_end": 5.2,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 5.3,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 5.2,
                        "phase_time_end": 5.5,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 5.6,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.75,
                        "phase_time_start": 5.5,
                        "phase_time_end": 6.0,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined = [
                {
                    **resolved["selected"][0],
                    "pre_refine_timestamp": 5.0,
                    "refinement_delta_sec": -0.113,
                    "refinement_method": "local_motion_peak",
                    "refinement_motion_score": 0.0262,
                },
                {
                    **resolved["selected"][1],
                    "refinement_delta_sec": 0.0,
                    "refinement_method": "apex_preserved",
                    "refinement_motion_score": None,
                },
                {
                    **resolved["selected"][2],
                    "refinement_delta_sec": 0.0,
                    "refinement_method": "local_motion_peak_phase_rejected",
                    "refinement_motion_score": 0.0275,
                    "refinement_reject_reason": "phase",
                    "refinement_candidate_timestamp": 5.487,
                    "refinement_candidate_delta_sec": -0.113,
                },
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_takeoff_apex_gap_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                        "tal_candidate_confidence_low",
                    ],
                    "T": {
                        "frame_id": "frame_0027",
                        "timestamp": 5.875,
                        "confidence": 0.34,
                        "warnings": [
                            "knee_extension_weak",
                            "takeoff_timing_window_weak",
                            "tal_candidate_temporal_geometry_unreliable",
                            "tal_candidate_compressed_temporal_geometry",
                        ],
                    },
                    "A": {
                        "frame_id": "frame_0031",
                        "timestamp": 7.688,
                        "confidence": 0.34,
                        "warnings": [
                            "confidence_missing_knee_angle_change",
                            "apex_local_minimum_not_clear",
                            "tal_candidate_temporal_geometry_unreliable",
                            "tal_candidate_compressed_temporal_geometry",
                        ],
                    },
                    "L": {
                        "frame_id": "frame_0032",
                        "timestamp": 7.75,
                        "confidence": 0.34,
                        "warnings": [
                            "ankle_return_weak",
                            "knee_absorption_weak",
                            "com_descent_weak",
                            "landing_geometry_weak",
                            "tal_candidate_temporal_geometry_unreliable",
                            "tal_candidate_compressed_temporal_geometry",
                        ],
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0017", "timestamp": 3.562, "motion_score": 0.1279},
                    {"frame_id": "frame_0018", "timestamp": 3.625, "motion_score": 0.1510},
                    {"frame_id": "frame_0019", "timestamp": 3.688, "motion_score": 0.1760},
                    {"frame_id": "frame_0020", "timestamp": 3.75, "motion_score": 0.1799},
                    {"frame_id": "frame_0021", "timestamp": 3.812, "motion_score": 0.1271},
                    {"frame_id": "frame_0024", "timestamp": 4.688, "motion_score": 0.0476},
                    {"frame_id": "frame_0026", "timestamp": 5.625, "motion_score": 0.0449},
                    {"frame_id": "frame_0032", "timestamp": 7.75, "motion_score": 0.0716},
                ],
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined, ["semantic_keyframe_refinement_phase_rejected"])),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=video_temporal,
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.835, 0.0, 7.835, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=7.835,
                            )

        self.assertFalse(result.used_semantic_frames)
        self.assertIn(
            "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertIn(
            "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertIn("video_temporal_quality_retry_motion_cluster_conflict", result.resolved_keyframes["quality_flags"])
        self.assertNotIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        self.assertLess(
            result.resolved_keyframes["semantic_motion_cluster_conflict"]["core_peak_motion_score"],
            result.resolved_keyframes["semantic_motion_cluster_conflict"]["peak_motion_score"] * 0.35,
        )

    async def test_phase_range_video_tal_promotes_over_weak_geometry_foreground_motion_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.70,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Salchow", "confidence": 0.8},
                "quality_flags": ["distance", "video_temporal_not_high_confidence"],
                "key_moments": {"T_takeoff_sec": 4.4, "A_air_sec": 4.8, "L_landing_sec": 5.1},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 4.2, "time_end": 4.6, "confidence": 0.8},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.6, "time_end": 5.0, "confidence": 0.8},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 5.0, "time_end": 5.3, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "blended",
                "confidence": 0.70,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 4.553,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                        "phase_time_start": 4.2,
                        "phase_time_end": 4.6,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 4.8,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                        "phase_time_start": 4.6,
                        "phase_time_end": 5.0,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.9,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                        "phase_time_start": 5.0,
                        "phase_time_end": 5.3,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0476, "refinement_delta_sec": 0.153},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0476, "refinement_delta_sec": -0.2},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_takeoff_geometry_weak",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_weak_geometry",
                    ],
                    "T": {"frame_id": "frame_0019", "timestamp": 3.688, "confidence": 0.652, "warnings": ["knee_extension_weak", "takeoff_geometry_weak"]},
                    "A": {"frame_id": "frame_0020", "timestamp": 3.75, "confidence": 0.389, "warnings": ["apex_local_minimum_not_clear"]},
                    "L": {"frame_id": "frame_0023", "timestamp": 3.938, "confidence": 0.35, "warnings": ["landing_geometry_weak"]},
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0017", "timestamp": 3.562, "motion_score": 0.1279},
                    {"frame_id": "frame_0018", "timestamp": 3.625, "motion_score": 0.1510},
                    {"frame_id": "frame_0019", "timestamp": 3.688, "motion_score": 0.1760},
                    {"frame_id": "frame_0020", "timestamp": 3.75, "motion_score": 0.1799},
                    {"frame_id": "frame_0021", "timestamp": 3.812, "motion_score": 0.1271},
                    {"frame_id": "semantic_t", "timestamp": 4.553, "motion_score": 0.0476},
                    {"frame_id": "semantic_l", "timestamp": 4.9, "motion_score": 0.0476},
                ],
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=video_temporal,
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.835, 0.0, 7.835, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=7.835,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"][:3]], [4.553, 4.8, 4.9])
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_weak_temporal_geometry",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("video_temporal_quality_retry_motion_cluster_conflict", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            result.resolved_keyframes["semantic_motion_cluster_conflict"]["decision"],
            "ignored_weak_temporal_geometry_candidate_motion_cluster",
        )
        self.assertTrue(result.resolved_keyframes["semantic_motion_cluster_conflict"]["candidate_support"]["weak_geometry_only_context"])

    async def test_phase_range_video_tal_does_not_promote_foreground_occluded_takeoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "confidence": 0.8},
                "quality_flags": ["distance", "video_temporal_not_high_confidence"],
                "key_moments": {"T_takeoff_sec": 3.2, "A_air_sec": 4.4, "L_landing_sec": 5.1},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.5, "time_end": 4.0, "confidence": 0.8},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.0, "time_end": 4.8, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 4.8, "time_end": 5.5, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "blended",
                "confidence": 0.75,
                "quality_flags": [
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_partial_core_frames_available",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 3.741,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_skeleton_takeoff_anchor",
                        "confidence": 0.8,
                        "phase_time_start": 2.5,
                        "phase_time_end": 4.0,
                        "semantic_visibility": {"status": "foreground_person_occluded"},
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 4.4,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 4.0,
                        "phase_time_end": 4.8,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.9,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                        "phase_time_start": 4.8,
                        "phase_time_end": 5.5,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_takeoff_geometry_weak",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_weak_geometry",
                    ],
                    "T": {"frame_id": "frame_0019", "timestamp": 3.688, "confidence": 0.652, "warnings": ["takeoff_geometry_weak"]},
                    "A": {"frame_id": "frame_0020", "timestamp": 3.75, "confidence": 0.389, "warnings": ["apex_local_minimum_not_clear"]},
                    "L": {"frame_id": "frame_0023", "timestamp": 3.938, "confidence": 0.35, "warnings": ["landing_geometry_weak"]},
                }
            }

        self.assertFalse(
            _phase_range_motion_fallback_jump_partial_can_be_promoted(
                resolved,
                resolved["selected"],
                analysis_profile="jump",
                bio_data=bio_data,
            )
        )

    async def test_pipeline_repairs_foreground_occluded_phase_range_takeoff_with_zoomed_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.75,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "confidence": 0.8},
                "quality_flags": ["distance", "video_temporal_not_high_confidence"],
                "key_moments": {"T_takeoff_sec": 3.2, "A_air_sec": 4.4, "L_landing_sec": 5.1},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.5, "time_end": 4.0, "confidence": 0.8},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.0, "time_end": 4.8, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 4.8, "time_end": 5.5, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.75,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 3.741,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_skeleton_takeoff_anchor",
                        "confidence": 0.8,
                        "phase_time_start": 2.5,
                        "phase_time_end": 4.0,
                        "pre_refine_timestamp": 3.688,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 4.4,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 4.0,
                        "phase_time_end": 4.8,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 4.9,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                        "phase_time_start": 4.8,
                        "phase_time_end": 5.5,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined = [
                {**resolved["selected"][0], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.176, "refinement_delta_sec": 0.053},
                {**resolved["selected"][1], "refinement_method": "apex_preserved", "refinement_motion_score": None, "refinement_delta_sec": 0.0},
                {**resolved["selected"][2], "refinement_method": "local_motion_peak", "refinement_motion_score": 0.0476, "refinement_delta_sec": -0.2},
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_takeoff_geometry_weak",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_weak_geometry",
                    ],
                    "T": {"frame_id": "frame_0019", "timestamp": 3.688, "confidence": 0.652, "warnings": ["takeoff_geometry_weak"]},
                    "A": {"frame_id": "frame_0020", "timestamp": 3.75, "confidence": 0.389, "warnings": ["apex_local_minimum_not_clear"]},
                    "L": {"frame_id": "frame_0023", "timestamp": 3.938, "confidence": 0.35, "warnings": ["landing_geometry_weak"]},
                }
            }
            def fake_detect_person_candidates(*args, **kwargs):
                include_zoomed = bool(kwargs.get("include_zoomed_small_targets"))
                frame_path = Path(args[0]) if args else Path("")
                timestamp_hint = 0.0
                for part in frame_path.parts:
                    if part.startswith("repair_"):
                        try:
                            timestamp_hint = int(part.rsplit("_", 1)[-1]) / 1000.0
                        except ValueError:
                            continue
                if frame_path.name == "semantic_0001.jpg" and not include_zoomed:
                    return _foreground_occluded_person_candidates()
                if include_zoomed and timestamp_hint >= 3.9:
                    return _zoomed_visible_person_candidates()
                return []

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps", AsyncMock(return_value=(refined, []))):
                    with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_detect_person_candidates):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=root / "semantic_frames",
                                video_temporal=video_temporal,
                                motion_scores={"selected": []},
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.0, 0.0, 7.0, 30.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=7.0,
                            )

        self.assertTrue(result.used_semantic_frames)
        takeoff = result.resolved_keyframes["selected"][0]
        self.assertGreater(takeoff["timestamp"], 3.741)
        self.assertIn("semantic_keyframe_core_foreground_occlusion_repaired", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframe_core_foreground_occlusion", result.resolved_keyframes["quality_flags"])

    async def test_pipeline_ignores_early_approach_motion_peak_over_drifted_takeoff_anchor_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.8,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Toe Loop",
                    "confidence": 0.9,
                },
                "quality_flags": [],
                "phase_segments": [
                    {"phase_code": "approach", "phase_label": "approach", "time_start": 0.0, "time_end": 1.3, "key_frame_hint": 0.6, "confidence": 0.8},
                    {"phase_code": "preparation", "phase_label": "preparation", "time_start": 1.3, "time_end": 2.1, "key_frame_hint": 1.8, "confidence": 0.8},
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.1, "time_end": 2.5, "key_frame_hint": 2.3, "confidence": 0.7},
                    {"phase_code": "air", "phase_label": "air", "time_start": 2.5, "time_end": 2.9, "key_frame_hint": 2.7, "confidence": 0.7},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 2.9, "time_end": 3.2, "key_frame_hint": 3.0, "confidence": 0.8},
                    {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 3.2, "time_end": 4.5, "key_frame_hint": 3.8, "confidence": 0.8},
                ],
                "key_moments": {"T_takeoff_sec": 2.3, "A_air_sec": 2.7, "L_landing_sec": 3.0},
            }
            resolved = {
                "source": "video_ai_refined",
                "confidence": 0.8,
                "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 2.153,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 2.1,
                        "phase_time_end": 2.5,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 2.7,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                        "phase_time_start": 2.5,
                        "phase_time_end": 2.9,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 2.833,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                        "phase_time_start": 2.9,
                        "phase_time_end": 3.2,
                    },
                ],
                "video_ai": video_temporal,
            }
            refined = [
                {
                    **resolved["selected"][0],
                    "pre_refine_timestamp": 2.3,
                    "refinement_method": "local_motion_peak",
                    "refinement_delta_sec": -0.147,
                    "refinement_candidate_timestamp": None,
                    "refinement_candidate_delta_sec": -0.147,
                },
                {
                    **resolved["selected"][1],
                    "refinement_method": "apex_preserved",
                    "refinement_delta_sec": 0.0,
                },
                {
                    **resolved["selected"][2],
                    "pre_refine_timestamp": 3.0,
                    "refinement_method": "local_motion_peak",
                    "refinement_delta_sec": -0.167,
                },
            ]
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "tal_candidate_skeleton_drifted_after_takeoff",
                        "keyframe_candidates_motion_fallback",
                        "keyframe_candidates_motion_fallback_from_takeoff_anchor",
                        "tal_candidate_motion_fallback_low_precision",
                        "a_pose_signal_drifted",
                        "l_pose_signal_drifted",
                    ],
                    "T": {
                        "frame_id": "frame_0018",
                        "timestamp": 1.625,
                        "confidence": 0.806,
                        "evidence": {
                            "motion_score": 0.0614,
                            "motion_cluster_window": {
                                "start_timestamp": 0.0,
                                "end_timestamp": 3.188,
                            },
                        },
                        "warnings": ["keyframe_candidates_motion_fallback"],
                    },
                    "A": {
                        "frame_id": "frame_0019",
                        "timestamp": 1.875,
                        "confidence": 0.487,
                        "evidence": {"motion_score": 0.0492, "motion_fallback": True},
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                    },
                    "L": {
                        "frame_id": "frame_0023",
                        "timestamp": 2.312,
                        "confidence": 0.476,
                        "evidence": {"motion_score": 0.0385, "motion_fallback": True},
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"],
                    },
                }
            }
            motion_scores = {
                "selected": [
                    {"frame_id": "frame_0001", "timestamp": 0.312, "motion_score": 0.1481},
                    {"frame_id": "frame_0002", "timestamp": 0.375, "motion_score": 0.144},
                    {"frame_id": "frame_0003", "timestamp": 0.812, "motion_score": 0.1385},
                    {"frame_id": "frame_0004", "timestamp": 0.875, "motion_score": 0.1284},
                    {"frame_id": "frame_0018", "timestamp": 1.625, "motion_score": 0.0614},
                    {"frame_id": "frame_0020", "timestamp": 2.125, "motion_score": 0.0427},
                    {"frame_id": "frame_0022", "timestamp": 2.25, "motion_score": 0.0427},
                    {"frame_id": "frame_0024", "timestamp": 2.688, "motion_score": 0.0351},
                    {"frame_id": "frame_0025", "timestamp": 2.812, "motion_score": 0.0372},
                    {"frame_id": "frame_0026", "timestamp": 2.875, "motion_score": 0.0592},
                ],
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.refine_semantic_keyframe_timestamps",
                    AsyncMock(return_value=(refined, ["semantic_keyframe_refinement_phase_rejected"])),
                ):
                    with patch(
                        "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                        AsyncMock(side_effect=_fake_extract_precise_frames),
                    ):
                        with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                            result = await resolve_semantic_keyframe_pipeline(
                                video_path=video_path,
                                work_dir=root,
                                semantic_frames_dir=semantic_dir,
                                video_temporal=video_temporal,
                                motion_scores=motion_scores,
                                sampling_metadata=VideoSamplingMetadata(0.0, 7.3, 0.0, 7.3, 16.0, 30.0, False),
                                analysis_profile="jump",
                                bio_data=bio_data,
                                video_duration_sec=7.3,
                            )

        self.assertTrue(result.used_semantic_frames)
        self.assertTrue(semantic_keyframes_are_reliable(result.resolved_keyframes))
        self.assertIn(
            "semantic_keyframes_candidate_motion_window_conflict_ignored_early_approach_motion_peak",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            [item["timestamp"] for item in result.resolved_keyframes["selected"][:3]],
            [2.153, 2.7, 2.833],
        )

    async def test_distant_full_context_low_confidence_tal_promotes_over_compressed_motion_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "manual_review",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "confidence": 0.6},
                "quality_flags": [
                    "video_temporal_low_confidence",
                    "video_temporal_not_high_confidence",
                    "video_temporal_fallback_recommended",
                    "distance_too_far",
                    "low_resolution",
                ],
                "key_moments": {"T_takeoff_sec": 5.6, "A_air_sec": 5.9, "L_landing_sec": 6.2},
                "phase_segments": [
                    {"phase_code": "approach", "phase_label": "approach", "time_start": 0.0, "time_end": 4.5, "confidence": 0.7},
                    {"phase_code": "preparation", "phase_label": "preparation", "time_start": 4.5, "time_end": 5.5, "confidence": 0.6},
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 5.5, "time_end": 5.8, "confidence": 0.5},
                    {"phase_code": "air", "phase_label": "air", "time_start": 5.8, "time_end": 6.1, "confidence": 0.5},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 6.1, "time_end": 6.5, "confidence": 0.5},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": [
                    "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                    "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                    "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                    "video_temporal_resolver_low_video_confidence",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 5.6,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_temporal_low_confidence_partial_core",
                        "confidence": 0.5,
                        "partial_semantic_key": "T",
                        "phase_time_start": 5.5,
                        "phase_time_end": 5.8,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 5.9,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_temporal_low_confidence_partial_core",
                        "confidence": 0.5,
                        "partial_semantic_key": "A",
                        "phase_time_start": 5.8,
                        "phase_time_end": 6.1,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 6.2,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_temporal_low_confidence_partial_core",
                        "confidence": 0.5,
                        "partial_semantic_key": "L",
                        "phase_time_start": 6.1,
                        "phase_time_end": 6.5,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                        "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 3.188, "end_timestamp": 4.662},
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 3.188,
                        "confidence": 0.54,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    },
                    "A": {
                        "frame_id": "frame_0013",
                        "timestamp": 3.25,
                        "confidence": 0.427,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    },
                    "L": {
                        "frame_id": "frame_0014",
                        "timestamp": 3.312,
                        "confidence": 0.435,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    },
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 10.235, 0.0, 10.235, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=10.235,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [5.6, 5.9, 6.2])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_distant_full_context_visual_tal_promoted"] * 3,
        )
        self.assertIn("semantic_keyframes_distant_full_context_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates", result.resolved_keyframes["quality_flags"])

    async def test_phase_range_video_tal_does_not_promote_when_takeoff_candidate_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.8,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.82},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.45, "A_air_sec": 3.75, "L_landing_sec": 4.0},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 3.3, "time_end": 3.6, "confidence": 0.8},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.6, "time_end": 3.9, "confidence": 0.75},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 3.9, "time_end": 4.2, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.8,
                "quality_flags": [
                    "semantic_keyframes_unreliable_after_refinement",
                    "semantic_keyframes_unreliable_candidate_tal_conflict",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                ],
                "selected": [
                    {
                        "frame_id": "partial_semantic_0001",
                        "timestamp": 3.45,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                    },
                    {
                        "frame_id": "partial_semantic_0002",
                        "timestamp": 3.75,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.75,
                    },
                    {
                        "frame_id": "partial_semantic_0003",
                        "timestamp": 4.267,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.8,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_motion_fallback"],
                    "T": {
                        "frame_id": "frame_0009",
                        "timestamp": 0.625,
                        "confidence": 0.57,
                        "evidence": {"visibility_score": 0.937},
                        "warnings": ["keyframe_candidates_motion_fallback"],
                    },
                    "A": {
                        "frame_id": "frame_0010",
                        "timestamp": 0.812,
                        "confidence": 0.486,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_drifted"],
                    },
                    "L": {
                        "frame_id": "frame_0015",
                        "timestamp": 1.438,
                        "confidence": 0.501,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_drifted"],
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 6.568, 0.0, 6.568, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=6.568,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertNotIn("semantic_keyframes_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_non_phase_range_partial_tal_does_not_promote_over_motion_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.8,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.82},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.0, "time_end": 2.4, "confidence": 0.8},
                    {"phase_code": "air", "phase_label": "air", "time_start": 2.4, "time_end": 2.8, "confidence": 0.75},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 2.8, "time_end": 3.2, "confidence": 0.8},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.8,
                "quality_flags": [
                    "semantic_keyframes_unreliable_after_refinement",
                    "semantic_keyframes_unreliable_candidate_tal_conflict",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 2.312,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "post_vision_low_confidence_phase_anchor",
                        "confidence": 0.55,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 3.188,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "post_vision_low_confidence_phase_anchor",
                        "confidence": 0.55,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 3.688,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "post_vision_low_confidence_phase_anchor",
                        "confidence": 0.55,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": ["keyframe_candidates_motion_fallback"],
                    "T": {
                        "frame_id": "frame_0019",
                        "timestamp": 1.875,
                        "confidence": 0.702,
                        "evidence": {"visibility_score": 0.9},
                    },
                    "A": {
                        "frame_id": "frame_0022",
                        "timestamp": 2.25,
                        "confidence": 0.481,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    },
                    "L": {
                        "frame_id": "frame_0023",
                        "timestamp": 2.812,
                        "confidence": 0.35,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 6.0, 0.0, 6.0, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=6.0,
                        )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(len(result.partial_semantic_frames), 3)
        self.assertIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_resolver_low_confidence_visual_tal_promoted", result.resolved_keyframes["quality_flags"])

    async def test_full_video_tal_promotes_over_nearby_weak_skeleton_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.6,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop", "confidence": 0.7},
                "quality_flags": ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 4.4, "A_air_sec": 4.7, "L_landing_sec": 4.9},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 4.3, "time_end": 4.6, "confidence": 0.5},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.6, "time_end": 4.8, "confidence": 0.4},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 4.8, "time_end": 5.2, "confidence": 0.5},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.6,
                "quality_flags": [
                    "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                    "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                    "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                    "video_temporal_resolver_phase_takeoff_fallback",
                    "video_temporal_resolver_phase_air_fallback",
                    "video_temporal_resolver_phase_landing_fallback",
                    "semantic_keyframes_resolved_selected_fallback_to_keyframe_candidates",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                ],
                "selected": [
                    {
                        "frame_id": "frame_0023",
                        "timestamp": 4.188,
                        "phase_code": "takeoff",
                        "phase_label": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "fallback_to_keyframe_candidates",
                        "confidence": 0.34,
                    },
                    {
                        "frame_id": "frame_0025",
                        "timestamp": 4.812,
                        "phase_code": "air",
                        "phase_label": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "fallback_to_keyframe_candidates",
                        "confidence": 0.34,
                    },
                    {
                        "frame_id": "frame_0026",
                        "timestamp": 4.875,
                        "phase_code": "landing",
                        "phase_label": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "fallback_to_keyframe_candidates",
                        "confidence": 0.34,
                    },
                ],
                "video_ai": video_temporal,
                "semantic_candidate_tal_conflict": {
                    "decision": "rejected_late_pose_core_candidate_conflict",
                    "conflicts": [
                        {"key": "T", "semantic_timestamp": 4.4, "candidate_timestamp": 4.188, "delta_sec": 0.212},
                        {"key": "A", "semantic_timestamp": 4.7, "candidate_timestamp": 4.812, "delta_sec": -0.112},
                        {"key": "L", "semantic_timestamp": 4.9, "candidate_timestamp": 4.875, "delta_sec": 0.025},
                    ],
                },
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "keyframe_candidates_tail_motion_window_rejected",
                        "keyframe_candidates_tail_motion_window_reselected",
                        "keyframe_candidates_late_pose_core_reselected",
                        "tal_candidate_takeoff_geometry_weak",
                        "tal_candidate_apex_geometry_weak",
                        "tal_candidate_landing_geometry_weak",
                        "tal_candidate_weak_geometry",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_apex_landing_gap_unreliable",
                        "tal_candidate_apex_landing_gap_compressed",
                        "tal_candidate_confidence_low",
                    ],
                    "T": {
                        "frame_id": "frame_0023",
                        "timestamp": 4.188,
                        "confidence": 0.34,
                        "warnings": ["tal_candidate_takeoff_geometry_weak", "tal_candidate_weak_geometry"],
                    },
                    "A": {
                        "frame_id": "frame_0025",
                        "timestamp": 4.812,
                        "confidence": 0.34,
                        "warnings": [
                            "apex_geometry_weak",
                            "tal_candidate_weak_geometry",
                            "tal_candidate_temporal_geometry_unreliable",
                        ],
                    },
                    "L": {
                        "frame_id": "frame_0026",
                        "timestamp": 4.875,
                        "confidence": 0.34,
                        "warnings": [
                            "landing_geometry_weak",
                            "tal_candidate_weak_geometry",
                            "tal_candidate_temporal_geometry_unreliable",
                        ],
                    },
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch(
                    "app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps",
                    AsyncMock(side_effect=_fake_extract_precise_frames),
                ):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 7.368, 0.0, 7.368, 16.0, 15.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=7.368,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [4.4, 4.7, 4.9])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_phase_range_visual_tal_promoted"] * 3,
        )
        self.assertIn("semantic_keyframes_weak_skeleton_cluster_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertIn("video_temporal_resolver_weak_skeleton_cluster_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_phase_range_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_phase_range_visual_promotion_blocked_late_pose_core_conflict",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_phase_range_visual_promotion"]["promotion_context"],
            "weak_skeleton_cluster",
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_candidate_tal_conflict"]["decision"],
            "ignored_after_weak_skeleton_cluster_visual_promotion",
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_phase_range_visual_promotion"]["weak_skeleton_cluster_support"]["max_delta_sec"],
            0.212,
        )

    async def test_long_unresolved_motion_fallback_promotes_ordered_partial_tal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.5,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.7},
                "quality_flags": ["video_temporal_low_confidence"],
                "key_moments": {"T_takeoff_sec": 2.3, "A_air_sec": 2.6, "L_landing_sec": 2.9},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.1, "time_end": 2.4, "confidence": 0.5},
                    {"phase_code": "air", "phase_label": "air", "time_start": 2.4, "time_end": 2.75, "confidence": 0.5},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 2.75, "time_end": 3.1, "confidence": 0.5},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.5,
                "quality_flags": [
                    "video_temporal_resolver_low_video_confidence",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                ],
                "selected": [],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                        "keyframe_candidates_motion_fallback_filtered_unreliable_pose_records",
                    ],
                    "T": {"frame_id": "frame_0008", "timestamp": 1.375, "confidence": 0.497, "evidence": {"motion_fallback": True}},
                    "A": {"frame_id": "frame_0016", "timestamp": 4.375, "confidence": 0.473, "evidence": {"motion_fallback": True}},
                    "L": {"frame_id": "frame_0032", "timestamp": 7.688, "confidence": 0.534, "evidence": {"motion_fallback": True}},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=8.0,
                    )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual(result.partial_semantic_frames, [])
        self.assertNotIn("partial_selected", result.resolved_keyframes)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [2.3, 2.6, 2.9])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_long_unresolved_motion_fallback_partial_tal_promoted"] * 3,
        )
        self.assertIn(
            "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertIn(
            "video_temporal_resolver_long_unresolved_motion_fallback_partial_tal_promoted",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            result.resolved_keyframes["semantic_long_unresolved_motion_fallback_partial_promotion"]["decision"],
            "promoted_partial_video_tal_over_long_unresolved_motion_fallback",
        )

    async def test_long_unresolved_motion_fallback_promotes_moderate_confidence_skeleton_partial_tal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.6,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Salchow", "confidence": 0.6},
                "quality_flags": ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 4.1, "A_air_sec": 4.7, "L_landing_sec": 5.1},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 3.8, "time_end": 4.5, "confidence": 0.5},
                    {"phase_code": "air", "phase_label": "air", "time_start": 4.5, "time_end": 4.9, "confidence": 0.4},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 4.9, "time_end": 5.5, "confidence": 0.5},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.6,
                "quality_flags": [
                    "video_temporal_resolver_skeleton_t_below_anchor_confidence",
                    "video_temporal_resolver_skeleton_a_below_anchor_confidence",
                    "video_temporal_resolver_skeleton_l_below_anchor_confidence",
                    "video_temporal_resolver_video_fallback_recommended",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                ],
                "selected": [],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "T": {"frame_id": "frame_0008", "timestamp": 1.375, "confidence": 0.497, "evidence": {"motion_fallback": True}},
                    "A": {"frame_id": "frame_0016", "timestamp": 4.375, "confidence": 0.473, "evidence": {"motion_fallback": True}},
                    "L": {"frame_id": "frame_0032", "timestamp": 7.688, "confidence": 0.534, "evidence": {"motion_fallback": True}},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=8.0,
                    )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [4.1, 4.7, 5.1])
        self.assertIn(
            "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted",
            result.resolved_keyframes["quality_flags"],
        )

    async def test_long_unresolved_motion_fallback_promotes_blended_phase_range_after_refinement_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.7,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Salchow", "confidence": 0.7},
                "quality_flags": ["video_temporal_not_high_confidence", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 4.8, "A_air_sec": 5.3, "L_landing_sec": 5.7},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 4.5, "time_end": 5.2, "confidence": 0.6},
                    {"phase_code": "air", "phase_label": "air", "time_start": 5.2, "time_end": 5.5, "confidence": 0.5},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 5.5, "time_end": 6.0, "confidence": 0.7},
                ],
            }
            resolved = {
                "source": "blended",
                "confidence": 0.7,
                "quality_flags": [
                    "video_temporal_resolver_video_fallback_recommended",
                    "video_temporal_resolver_coherent_tal_used",
                    "video_temporal_quality_retry_motion_cluster_conflict",
                    "semantic_keyframes_unreliable_after_refinement",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                ],
                "selected": [
                    {
                        "frame_id": "semantic_0001",
                        "timestamp": 4.787,
                        "phase_code": "takeoff",
                        "key_moment": "T_takeoff_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.6,
                    },
                    {
                        "frame_id": "semantic_0002",
                        "timestamp": 5.3,
                        "phase_code": "air",
                        "key_moment": "A_air_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.5,
                    },
                    {
                        "frame_id": "semantic_0003",
                        "timestamp": 5.967,
                        "phase_code": "landing",
                        "key_moment": "L_landing_sec",
                        "selection_reason": "video_phase_range_key_moment",
                        "confidence": 0.7,
                    },
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "T": {"frame_id": "frame_0008", "timestamp": 1.375, "confidence": 0.497, "evidence": {"motion_fallback": True}},
                    "A": {"frame_id": "frame_0016", "timestamp": 4.375, "confidence": 0.473, "evidence": {"motion_fallback": True}},
                    "L": {"frame_id": "frame_0032", "timestamp": 7.688, "confidence": 0.534, "evidence": {"motion_fallback": True}},
                }
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                        analysis_profile="jump",
                        bio_data=bio_data,
                        video_duration_sec=8.0,
                    )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [4.787, 5.3, 5.967])
        self.assertIn(
            "semantic_keyframes_long_unresolved_motion_fallback_partial_tal_promoted",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertNotIn("semantic_keyframes_unreliable_after_refinement", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("video_temporal_quality_retry_motion_cluster_conflict", result.resolved_keyframes["quality_flags"])

    async def test_tracker_final_loss_low_visibility_motion_fallback_promotes_visible_video_tal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.8,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Waltz Jump", "confidence": 0.8},
                "quality_flags": ["distance", "partial_obstruction", "video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 6.3, "A_air_sec": 6.65, "L_landing_sec": 6.9},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 6.1, "time_end": 6.45, "confidence": 0.75},
                    {"phase_code": "air", "phase_label": "air", "time_start": 6.45, "time_end": 6.8, "confidence": 0.72},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 6.8, "time_end": 7.1, "confidence": 0.78},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.8,
                "quality_flags": [
                    "video_temporal_resolver_coherent_tal_motion_conflict_rejected",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                    "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                    "semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose",
                    "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
                ],
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 2.875, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.54},
                    {"frame_id": "frame_0013", "timestamp": 2.938, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.54},
                    {"frame_id": "frame_0014", "timestamp": 3.0, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.504},
                ],
                "video_ai": video_temporal,
                "semantic_low_visibility_bounded_motion_fallback_drift": {
                    "decision": "rejected_low_visibility_bounded_motion_fallback_drift",
                    "conflicts": [
                        {"key": "A", "semantic_timestamp": 6.65, "candidate_timestamp": 2.938, "delta_sec": 3.712},
                        {"key": "L", "semantic_timestamp": 6.9, "candidate_timestamp": 3.0, "delta_sec": 3.9},
                    ],
                },
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "motion_fallback_time_bounds": {"start_timestamp": 0.0, "end_timestamp": 4.1},
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 2.875,
                        "confidence": 0.54,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback", "t_pose_signal_insufficient"],
                    },
                    "A": {
                        "frame_id": "frame_0013",
                        "timestamp": 2.938,
                        "confidence": 0.54,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback", "a_pose_signal_insufficient"],
                    },
                    "L": {
                        "frame_id": "frame_0014",
                        "timestamp": 3.0,
                        "confidence": 0.504,
                        "evidence": {
                            "motion_fallback": True,
                            "visibility_score": 0.0,
                            "score_components": {"pose_visibility": 0.0},
                        },
                        "warnings": ["keyframe_candidates_motion_fallback", "l_pose_signal_insufficient"],
                    },
                },
            }

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", return_value=_visible_person_candidates()):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={
                                "selected": [
                                    {"frame_id": "frame_0013", "timestamp": 2.938, "motion_score": 0.1388},
                                    {"frame_id": "frame_0032", "timestamp": 11.25, "motion_score": 0.1402},
                                ]
                            },
                            sampling_metadata=VideoSamplingMetadata(0.0, 11.335, 0.0, 11.335, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=11.335,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertEqual(result.effective_source, "blended")
        self.assertEqual([item["timestamp"] for item in result.resolved_keyframes["selected"]], [6.3, 6.65, 6.9])
        self.assertEqual(
            [item["selection_reason"] for item in result.resolved_keyframes["selected"]],
            ["video_temporal_tracker_final_loss_visual_tal_promoted"] * 3,
        )
        self.assertIn("semantic_keyframes_tracker_final_loss_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_motion_fallback", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_tracker_final_loss_outside_reliable_pose", result.resolved_keyframes["quality_flags"])
        self.assertNotIn(
            "semantic_keyframes_unreliable_low_visibility_bounded_motion_fallback_drift",
            result.resolved_keyframes["quality_flags"],
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_tracker_final_loss_visual_promotion"]["decision"],
            "promoted_visible_video_tal_over_low_visibility_motion_fallback",
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_low_visibility_bounded_motion_fallback_drift"]["decision"],
            "ignored_after_tracker_final_loss_visual_tal_promotion",
        )
        self.assertEqual(
            result.resolved_keyframes["semantic_low_visibility_bounded_motion_fallback_drift"]["previous_decision"],
            "rejected_low_visibility_bounded_motion_fallback_drift",
        )
        self.assertEqual(
            [item["semantic_visibility"]["status"] for item in result.resolved_keyframes["selected"]],
            ["target_visible"] * 3,
        )

    async def test_tracker_final_loss_visual_promotion_accepts_small_target_partial_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": False,
                "confidence": 0.9,
                "fallback_recommendation": "use_sampled_frames",
                "action_confirmation": {"action_family": "jump", "confirmed_action": "Salchow", "confidence": 0.95},
                "quality_flags": ["video_temporal_fallback_recommended"],
                "key_moments": {"T_takeoff_sec": 3.3, "A_air_sec": 3.95, "L_landing_sec": 4.35},
                "phase_segments": [
                    {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 3.0, "time_end": 3.7, "confidence": 0.9},
                    {"phase_code": "air", "phase_label": "air", "time_start": 3.7, "time_end": 4.2, "confidence": 0.85},
                    {"phase_code": "landing", "phase_label": "landing", "time_start": 4.2, "time_end": 4.8, "confidence": 0.9},
                ],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.9,
                "quality_flags": [
                    "video_temporal_resolver_video_fallback_recommended",
                    "video_temporal_resolver_video_validation_not_clean",
                    "semantic_keyframes_unreliable_tracker_final_loss_motion_fallback",
                    "semantic_keyframes_unreliable_fallback_to_sampled_frames",
                ],
                "selected": [
                    {"frame_id": "frame_0012", "timestamp": 2.875, "phase_code": "takeoff", "key_moment": "T_takeoff_sec", "confidence": 0.54},
                    {"frame_id": "frame_0013", "timestamp": 2.938, "phase_code": "air", "key_moment": "A_air_sec", "confidence": 0.54},
                    {"frame_id": "frame_0014", "timestamp": 3.0, "phase_code": "landing", "key_moment": "L_landing_sec", "confidence": 0.504},
                ],
                "video_ai": video_temporal,
            }
            bio_data = {
                "quality_flags": [
                    "person_tracker_target_lost",
                    "person_tracker_relock_rejected",
                    "person_tracker_final_unrecovered",
                ],
                "key_frame_candidates": {
                    "quality_flags": [
                        "keyframe_candidates_excluded_unreliable_pose_frames",
                        "tal_candidate_incomplete",
                        "tal_order_unresolved",
                        "keyframe_candidates_motion_fallback",
                        "tal_candidate_motion_fallback_low_precision",
                        "keyframe_candidates_motion_fallback_bounded_to_reliable_pose",
                    ],
                    "T": {
                        "frame_id": "frame_0012",
                        "timestamp": 2.875,
                        "confidence": 0.54,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback"],
                    },
                    "A": {
                        "frame_id": "frame_0013",
                        "timestamp": 2.938,
                        "confidence": 0.54,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback"],
                    },
                    "L": {
                        "frame_id": "frame_0014",
                        "timestamp": 3.0,
                        "confidence": 0.504,
                        "evidence": {"motion_fallback": True, "visibility_score": 0.0},
                        "warnings": ["keyframe_candidates_motion_fallback"],
                    },
                },
            }

            def fake_candidates(frame_path: Path, *, min_confidence: float = 0.25, include_zoomed_small_targets: bool = False):
                if not include_zoomed_small_targets:
                    return []
                if frame_path.name == "semantic_0001.jpg":
                    return _visible_person_candidates()
                return []

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", AsyncMock(side_effect=_fake_extract_precise_frames)):
                    with patch("app.services.semantic_keyframe_pipeline.detect_person_candidates", side_effect=fake_candidates):
                        result = await resolve_semantic_keyframe_pipeline(
                            video_path=video_path,
                            work_dir=root,
                            semantic_frames_dir=semantic_dir,
                            video_temporal=video_temporal,
                            motion_scores={"selected": []},
                            sampling_metadata=VideoSamplingMetadata(0.0, 11.335, 0.0, 11.335, 16.0, 30.0, False),
                            analysis_profile="jump",
                            bio_data=bio_data,
                            video_duration_sec=11.335,
                        )

        self.assertTrue(result.used_semantic_frames)
        self.assertIn("semantic_keyframes_tracker_final_loss_visual_tal_promoted", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_tracker_final_loss_visual_tal_partial_visibility", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_unreliable_after_visibility_check", result.resolved_keyframes["quality_flags"])
        self.assertEqual(
            result.resolved_keyframes["semantic_tracker_final_loss_visual_promotion"]["visibility_decision"],
            "accepted_takeoff_or_landing_visible_with_small_target_core",
        )
        self.assertEqual(
            [item["semantic_visibility"]["status"] for item in result.resolved_keyframes["selected"]],
            ["target_visible", "target_not_detected", "target_not_detected"],
        )

    async def test_non_jump_profile_mismatch_extracts_partial_phase_diagnostics_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [semantic_dir / "partial_semantic_0001.jpg"]
            partial_records = [
                {
                    "frame_id": "partial_semantic_0001",
                    "timestamp": 3.5,
                    "phase_code": "step_sequence",
                    "confidence": 0.9,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                    "selection_reason": "video_temporal_profile_mismatch_partial_phase",
                }
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {
                    "action_family": "step",
                    "confirmed_action": "step_sequence",
                    "confidence": 0.9,
                },
                "phase_segments": [
                    {
                        "phase_code": "step_sequence",
                        "phase_label": "step sequence",
                        "time_start": 0.5,
                        "time_end": 7.7,
                        "key_frame_hint": 3.5,
                        "confidence": 0.9,
                    }
                ],
                "quality_flags": [],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_profile_mismatch_retryable",
                    "video_temporal_resolver_no_selected_frames",
                ],
                "selected": [],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["phase_code"], "step_sequence")
                self.assertEqual(records[0]["selection_reason"], "video_temporal_profile_mismatch_partial_phase")
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 8.0, 0.0, 8.0, 16.0, 30.0, False),
                        analysis_profile="spiral",
                        video_duration_sec=8.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertIn("semantic_keyframes_partial_profile_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_non_jump_provider_jump_mismatch_extracts_partial_action_frames_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_path = root / "source.mp4"
            video_path.write_bytes(b"fake-video")
            semantic_dir = root / "semantic_frames"
            partial_paths = [
                semantic_dir / "partial_semantic_0001.jpg",
                semantic_dir / "partial_semantic_0002.jpg",
                semantic_dir / "partial_semantic_0003.jpg",
            ]
            partial_records = [
                {
                    "frame_id": f"partial_semantic_{index:04d}",
                    "timestamp": timestamp,
                    "phase_code": phase_code,
                    "confidence": 0.9,
                    "partial_semantic_frame": True,
                    "selection_status": "partial_unreliable",
                    "selection_reason": "video_temporal_profile_mismatch_partial_action_phase",
                    "requested_profile": "spin",
                    "provider_action_family": "jump",
                }
                for index, (timestamp, phase_code) in enumerate(
                    [(1.2, "takeoff"), (1.5, "air"), (1.9, "landing")],
                    start=1,
                )
            ]
            video_temporal = {
                "schema_version": "video_temporal_v1",
                "valid": True,
                "confidence": 0.85,
                "fallback_recommendation": "use_video_timestamps",
                "action_confirmation": {
                    "action_family": "jump",
                    "confirmed_action": "Axel",
                    "confidence": 0.9,
                },
                "phase_segments": [
                    {"phase_code": "takeoff", "time_start": 1.0, "time_end": 1.3, "key_frame_hint": 1.2, "confidence": 0.9},
                    {"phase_code": "air", "time_start": 1.3, "time_end": 1.7, "key_frame_hint": 1.5, "confidence": 0.9},
                    {"phase_code": "landing", "time_start": 1.7, "time_end": 2.0, "key_frame_hint": 1.9, "confidence": 0.9},
                ],
                "quality_flags": [],
            }
            resolved = {
                "source": "skeleton_fallback",
                "confidence": 0.85,
                "quality_flags": [
                    "video_temporal_profile_mismatch_retryable",
                    "video_temporal_resolver_no_selected_frames",
                ],
                "selected": [],
                "video_ai": video_temporal,
            }

            async def fake_extract(_: Path, output_dir: Path, records: list[dict[str, object]], *, prefix: str = "semantic"):
                self.assertEqual(prefix, "partial_semantic")
                self.assertEqual([record["phase_code"] for record in records], ["takeoff", "air", "landing"])
                self.assertEqual(
                    [record["selection_reason"] for record in records],
                    ["video_temporal_profile_mismatch_partial_action_phase"] * 3,
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in partial_paths:
                    path.write_bytes(b"partial")
                return partial_paths, partial_records

            with patch("app.services.semantic_keyframe_pipeline.resolve_semantic_keyframes", return_value=resolved):
                extract_mock = AsyncMock(side_effect=fake_extract)
                with patch("app.services.semantic_keyframe_pipeline.extract_precise_frames_at_timestamps", extract_mock):
                    result = await resolve_semantic_keyframe_pipeline(
                        video_path=video_path,
                        work_dir=root,
                        semantic_frames_dir=semantic_dir,
                        video_temporal=video_temporal,
                        motion_scores={"selected": []},
                        sampling_metadata=VideoSamplingMetadata(0.0, 3.0, 0.0, 3.0, 16.0, 30.0, False),
                        analysis_profile="spin",
                        video_duration_sec=3.0,
                    )

        self.assertFalse(result.used_semantic_frames)
        self.assertEqual(result.semantic_frames, [])
        self.assertEqual(result.partial_semantic_frames, partial_paths)
        self.assertEqual(result.partial_semantic_records, partial_records)
        self.assertEqual(result.resolved_keyframes["partial_selected"], partial_records)
        self.assertNotIn("semantic_keyframes_partial_profile_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertNotIn("semantic_keyframes_partial_core_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_partial_mismatch_action_frames_available", result.resolved_keyframes["quality_flags"])
        self.assertIn("semantic_keyframes_unreliable_fallback_to_sampled_frames", result.resolved_keyframes["quality_flags"])
        extract_mock.assert_awaited_once()

    async def test_late_phase_range_tal_reanchors_to_preparation_motion_peak(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 2.6,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.8,
                    "pre_refine_timestamp": 2.6,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 3.1,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.75,
                    "pre_refine_timestamp": 3.1,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 3.5,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.8,
                    "pre_refine_timestamp": 3.5,
                },
            ],
            "video_ai": {
                "confidence": 0.8,
                "action_confirmation": {"action_family": "jump", "confidence": 0.8},
                "key_moments": {"T_takeoff_sec": 2.6, "A_air_sec": 3.1, "L_landing_sec": 3.5},
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 0.0, "time_end": 1.5, "confidence": 0.9},
                    {"phase_code": "preparation", "time_start": 1.5, "time_end": 2.4, "confidence": 0.85},
                    {"phase_code": "takeoff", "time_start": 2.4, "time_end": 2.8, "confidence": 0.8},
                    {"phase_code": "air", "time_start": 2.8, "time_end": 3.3, "confidence": 0.75},
                    {"phase_code": "landing", "time_start": 3.3, "time_end": 3.8, "confidence": 0.8},
                ],
            },
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0003", "timestamp": 0.188, "motion_score": 0.2585},
                {"frame_id": "frame_0005", "timestamp": 0.312, "motion_score": 0.3185},
                {"frame_id": "frame_0016", "timestamp": 1.812, "motion_score": 0.0364},
                {"frame_id": "frame_0017", "timestamp": 1.875, "motion_score": 0.0573},
                {"frame_id": "frame_0018", "timestamp": 1.938, "motion_score": 0.0817},
                {"frame_id": "frame_0019", "timestamp": 2.0, "motion_score": 0.0692},
                {"frame_id": "frame_0027", "timestamp": 2.625, "motion_score": 0.0659},
                {"frame_id": "frame_0030", "timestamp": 2.75, "motion_score": 0.0410},
            ]
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_landing_geometry_weak",
                ],
                "T": {"timestamp": 1.812, "confidence": 0.34},
                "A": {"timestamp": 2.0, "confidence": 0.34},
                "L": {"timestamp": 2.062, "confidence": 0.34},
            }
        }

        changed = _maybe_reanchor_late_phase_range_tal(
            resolved,
            bio_data,
            motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(changed)
        self.assertEqual([item["timestamp"] for item in resolved["selected"]], [1.938, 2.438, 2.758])
        self.assertIn("semantic_keyframes_phase_range_late_reanchored", resolved["quality_flags"])
        self.assertEqual(
            resolved["semantic_phase_range_late_reanchor"]["decision"],
            "reanchored_late_phase_range_tal_to_pre_takeoff_motion_peak",
        )
        self.assertEqual(resolved["video_ai"]["key_moments"]["T_takeoff_sec"], 1.938)

    async def test_late_phase_range_reanchor_ignores_approach_motion_cluster_conflict(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframes_phase_range_late_reanchored",
                "video_temporal_resolver_phase_range_late_reanchored",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 1.938,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.8,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 2.438,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.75,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 2.838,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.8,
                },
            ],
            "video_ai": {
                "confidence": 0.8,
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 0.0, "time_end": 1.5, "confidence": 0.9},
                    {"phase_code": "preparation", "time_start": 1.5, "time_end": 2.4, "confidence": 0.85},
                    {"phase_code": "takeoff", "time_start": 2.4, "time_end": 2.8, "confidence": 0.8},
                    {"phase_code": "air", "time_start": 2.8, "time_end": 3.3, "confidence": 0.75},
                    {"phase_code": "landing", "time_start": 3.3, "time_end": 3.8, "confidence": 0.8},
                ],
            },
            "semantic_phase_range_late_reanchor": {
                "decision": "reanchored_late_phase_range_tal_to_pre_takeoff_motion_peak",
                "preparation_peak_timestamp": 1.938,
                "preparation_peak_motion_score": 0.0817,
            },
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0003", "timestamp": 0.188, "motion_score": 0.2585},
                {"frame_id": "frame_0005", "timestamp": 0.312, "motion_score": 0.3185},
                {"frame_id": "frame_0018", "timestamp": 1.938, "motion_score": 0.0817},
                {"frame_id": "frame_0019", "timestamp": 2.0, "motion_score": 0.0692},
                {"frame_id": "frame_0027", "timestamp": 2.625, "motion_score": 0.0659},
                {"frame_id": "frame_0030", "timestamp": 2.75, "motion_score": 0.0410},
            ]
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_temporal_geometry_unreliable",
                ],
            }
        }

        flags = _semantic_motion_cluster_conflict_flags(
            resolved,
            motion_scores,
            analysis_profile="jump",
            bio_data=bio_data,
        )

        self.assertEqual(flags, [])
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor",
            resolved["quality_flags"],
        )
        self.assertEqual(
            resolved["semantic_motion_cluster_conflict"]["decision"],
            "ignored_approach_motion_after_phase_range_late_reanchor",
        )

    def test_retry_weak_phase_tal_ignores_early_approach_motion_cluster_over_compressed_candidates(self) -> None:
        video_temporal = {
            "schema_version": "video_temporal_v1",
            "confidence": 0.70,
            "fallback_recommendation": "use_video_timestamps",
            "action_confirmation": {
                "action_family": "jump",
                "confirmed_action": "Salchow",
                "jump_type": "Salchow",
                "confidence": 0.70,
            },
            "quality_flags": [
                "video_temporal_not_high_confidence",
                "video_temporal_quality_retry",
                "action_incomplete",
            ],
            "phase_segments": [
                {"phase_code": "approach", "phase_label": "approach", "time_start": 0.0, "time_end": 1.8, "key_frame_hint": 1.5, "confidence": 0.8},
                {"phase_code": "preparation", "phase_label": "preparation", "time_start": 1.8, "time_end": 2.3, "key_frame_hint": 2.1, "confidence": 0.6},
                {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 2.3, "time_end": 2.6, "key_frame_hint": 2.4, "confidence": 0.5},
                {"phase_code": "air", "phase_label": "air", "time_start": 2.6, "time_end": 2.9, "key_frame_hint": 2.7, "confidence": 0.4},
                {"phase_code": "landing", "phase_label": "landing", "time_start": 2.9, "time_end": 3.5, "key_frame_hint": 3.0, "confidence": 0.3},
                {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 3.5, "time_end": 4.5, "key_frame_hint": 4.0, "confidence": 0.4},
            ],
            "key_moments": {"T_takeoff_sec": 2.4, "A_air_sec": 2.7, "L_landing_sec": 3.0},
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_confidence_low",
                ],
                "T": {
                    "frame_id": "frame_0018",
                    "timestamp": 1.812,
                    "confidence": 0.34,
                    "warnings": ["tal_candidate_temporal_geometry_unreliable"],
                },
                "A": {
                    "frame_id": "frame_0019",
                    "timestamp": 2.25,
                    "confidence": 0.34,
                    "warnings": [
                        "apex_local_minimum_not_clear",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_compressed_temporal_geometry",
                    ],
                },
                "L": {
                    "frame_id": "frame_0020",
                    "timestamp": 2.312,
                    "confidence": 0.34,
                    "warnings": [
                        "landing_geometry_weak",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_compressed_temporal_geometry",
                    ],
                },
            }
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0008", "timestamp": 0.438, "motion_score": 0.3202},
                {"frame_id": "frame_0010", "timestamp": 0.562, "motion_score": 0.37},
                {"frame_id": "frame_0011", "timestamp": 0.625, "motion_score": 0.3602},
                {"frame_id": "frame_0012", "timestamp": 0.688, "motion_score": 0.3327},
                {"frame_id": "frame_0018", "timestamp": 1.812, "motion_score": 0.0934},
                {"frame_id": "frame_0019", "timestamp": 2.25, "motion_score": 0.0865},
                {"frame_id": "frame_0020", "timestamp": 2.312, "motion_score": 0.0911},
                {"frame_id": "frame_0021", "timestamp": 4.312, "motion_score": 0.0763},
            ],
        }

        resolved = resolve_semantic_keyframes(
            video_temporal,
            bio_data,
            motion_scores,
            video_duration_sec=11.133,
            analysis_profile="jump",
        )
        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        core = [item for item in validated["selected"] if item["phase_code"] in {"takeoff", "air", "landing"}]
        self.assertEqual([item["timestamp"] for item in core], [2.4, 2.7, 3.0])
        self.assertTrue(semantic_keyframes_are_reliable(validated))
        self.assertIn("video_temporal_resolver_retry_weak_phase_tal_preserved", validated["quality_flags"])
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_early_approach_motion_peak",
            validated["quality_flags"],
        )
        self.assertEqual(
            validated["semantic_motion_cluster_conflict"]["decision"],
            "ignored_retry_weak_phase_early_approach_motion_cluster",
        )

    def test_late_phase_range_tal_reanchors_after_compressed_candidate_window(self) -> None:
        video_temporal = {
            "schema_version": "video_temporal_v1",
            "confidence": 0.8,
            "fallback_recommendation": "use_video_timestamps",
            "action_confirmation": {
                "action_family": "jump",
                "confirmed_action": "Salchow",
                "jump_type": "Salchow",
                "confidence": 0.8,
            },
            "quality_flags": [],
            "key_moments": {"T_takeoff_sec": 4.0, "A_air_sec": 4.4, "L_landing_sec": 4.7},
            "phase_segments": [
                {"phase_code": "approach", "phase_label": "approach", "time_start": 0.0, "time_end": 2.5, "key_frame_hint": 1.0, "confidence": 0.9},
                {"phase_code": "preparation", "phase_label": "preparation", "time_start": 2.5, "time_end": 3.8, "key_frame_hint": 3.3, "confidence": 0.85},
                {"phase_code": "takeoff", "phase_label": "takeoff", "time_start": 3.8, "time_end": 4.3, "key_frame_hint": 4.0, "confidence": 0.75},
                {"phase_code": "air", "phase_label": "air", "time_start": 4.3, "time_end": 4.6, "key_frame_hint": 4.4, "confidence": 0.7},
                {"phase_code": "landing", "phase_label": "landing", "time_start": 4.6, "time_end": 4.8, "key_frame_hint": 4.7, "confidence": 0.75},
                {"phase_code": "glide_out", "phase_label": "glide_out", "time_start": 4.8, "time_end": 7.0, "key_frame_hint": 5.5, "confidence": 0.8},
            ],
        }
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": [
                "video_temporal_resolver_coherent_tal_used",
                "semantic_keyframe_refinement_delta_rejected",
                "semantic_keyframe_refinement_phase_rejected",
                "semantic_keyframe_refinement_rejection_ignored_weak_temporal_geometry",
                "semantic_keyframes_candidate_tal_conflict_ignored_weak_temporal_geometry",
            ],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 4.0,
                    "phase_code": "takeoff",
                    "phase_label": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.75,
                    "phase_time_start": 3.8,
                    "phase_time_end": 4.3,
                    "pre_refine_timestamp": 4.0,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 4.4,
                    "phase_code": "air",
                    "phase_label": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.7,
                    "phase_time_start": 4.3,
                    "phase_time_end": 4.6,
                    "pre_refine_timestamp": 4.4,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 4.7,
                    "phase_code": "landing",
                    "phase_label": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.75,
                    "phase_time_start": 4.6,
                    "phase_time_end": 4.8,
                    "pre_refine_timestamp": 4.7,
                },
                {
                    "frame_id": "semantic_0004",
                    "timestamp": 3.3,
                    "phase_code": "preparation",
                    "phase_label": "preparation",
                    "key_moment": None,
                    "selection_reason": "video_phase_range_key_hint",
                    "confidence": 0.85,
                    "phase_time_start": 2.5,
                    "phase_time_end": 3.8,
                    "pre_refine_timestamp": 3.3,
                },
            ],
            "video_ai": video_temporal,
        }
        bio_data = {
            "analysis_profile": "jump",
            "key_frames": {},
            "quality_flags": [],
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_landing_geometry_weak",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_apex_landing_gap_compressed",
                    "tal_candidate_confidence_low",
                ],
                "T": {
                    "frame_id": "frame_0018",
                    "timestamp": 1.812,
                    "confidence": 0.34,
                    "evidence": {
                        "motion_score": 0.0934,
                        "motion_cluster_window": {"start_timestamp": 0.0, "end_timestamp": 2.312},
                    },
                    "warnings": ["tal_candidate_temporal_geometry_unreliable", "tal_candidate_compressed_temporal_geometry"],
                },
                "A": {
                    "frame_id": "frame_0019",
                    "timestamp": 2.25,
                    "confidence": 0.34,
                    "evidence": {
                        "motion_score": 0.0865,
                        "motion_cluster_window": {"start_timestamp": 0.0, "end_timestamp": 2.312},
                    },
                    "warnings": [
                        "confidence_missing_knee_angle_change",
                        "apex_local_minimum_not_clear",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_compressed_temporal_geometry",
                    ],
                },
                "L": {
                    "frame_id": "frame_0020",
                    "timestamp": 2.312,
                    "confidence": 0.34,
                    "evidence": {
                        "motion_score": 0.0911,
                        "motion_cluster_window": {"start_timestamp": 0.0, "end_timestamp": 2.312},
                    },
                    "warnings": [
                        "ankle_return_weak",
                        "knee_absorption_weak",
                        "com_descent_weak",
                        "landing_confidence_low",
                        "confidence_floor_from_ordered_tal",
                        "landing_geometry_weak",
                        "tal_candidate_temporal_geometry_unreliable",
                        "tal_candidate_compressed_temporal_geometry",
                    ],
                },
            },
        }
        motion_scores = {
            "scores": [
                0.0,
                0.2459,
                0.2614,
                0.2343,
                0.2284,
                0.2494,
                0.2829,
                0.3202,
                0.2327,
                0.37,
                0.3602,
                0.3327,
                0.2963,
                0.268,
                0.2277,
                0.1985,
                0.1129,
                0.185,
                0.16,
                0.1543,
                0.1539,
                0.1405,
                0.1297,
                0.1273,
                0.0735,
                0.1282,
                0.1233,
                0.1149,
                0.0937,
                0.0934,
                0.1077,
                0.107,
                0.0581,
                0.0943,
                0.1005,
                0.0874,
                0.0865,
                0.0911,
                0.0818,
                0.0825,
                0.0513,
                0.0712,
                0.0782,
                0.0708,
                0.0703,
                0.0712,
                0.0695,
                0.0689,
                0.0405,
                0.0546,
                0.0606,
                0.062,
                0.0617,
                0.0619,
                0.0612,
                0.0551,
                0.0347,
                0.0558,
                0.0617,
                0.0651,
                0.0644,
                0.0647,
                0.0778,
                0.0751,
                0.0532,
                0.075,
                0.0748,
                0.0712,
                0.0717,
                0.0763,
                0.0765,
                0.0774,
                0.0548,
                0.0754,
                0.0705,
                0.0709,
                0.0755,
            ],
            "frame_rate": 16.0,
            "window_start": 0.0,
        }

        validated = validate_semantic_keyframes_against_current_evidence(
            resolved,
            bio_data=bio_data,
            motion_scores=motion_scores,
            analysis_profile="jump",
        )

        self.assertIsNotNone(validated)
        assert validated is not None
        core = [item for item in validated["selected"] if item["phase_code"] in {"takeoff", "air", "landing"}]
        self.assertEqual([item["timestamp"] for item in core], [2.392, 2.712, 3.012])
        self.assertIn("semantic_keyframes_phase_range_late_reanchored", validated["quality_flags"])
        self.assertIn(
            "video_temporal_quality_retry_motion_cluster_conflict_ignored_phase_range_late_reanchor",
            validated["quality_flags"],
        )
        self.assertEqual(
            validated["semantic_phase_range_late_reanchor"]["anchor_scope"],
            "post_candidate_motion_window",
        )
        self.assertEqual(
            validated["semantic_motion_cluster_conflict"]["decision"],
            "ignored_approach_motion_after_phase_range_late_reanchor",
        )
        self.assertTrue(semantic_keyframes_are_reliable(validated))

        synced = sync_key_frames_from_resolved_keyframes(bio_data, validated, analysis_profile="jump")
        self.assertEqual(synced["key_frame_timestamps"], {"T": 2.392, "A": 2.712, "L": 3.012})
        self.assertNotIn(
            "bio_key_frames_not_synced_unresolved_semantic_tal_conflict",
            synced.get("quality_flags", []),
        )

    async def test_late_phase_range_tal_uses_skeleton_near_peak_when_preparation_peak_is_shifted(self) -> None:
        resolved = {
            "source": "video_ai_refined",
            "confidence": 0.8,
            "quality_flags": ["video_temporal_resolver_coherent_tal_used"],
            "selected": [
                {
                    "frame_id": "semantic_0001",
                    "timestamp": 3.287,
                    "phase_code": "takeoff",
                    "key_moment": "T_takeoff_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.8,
                    "pre_refine_timestamp": 3.4,
                },
                {
                    "frame_id": "semantic_0002",
                    "timestamp": 3.8,
                    "phase_code": "air",
                    "key_moment": "A_air_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.8,
                    "pre_refine_timestamp": 3.8,
                },
                {
                    "frame_id": "semantic_0003",
                    "timestamp": 4.2,
                    "phase_code": "landing",
                    "key_moment": "L_landing_sec",
                    "selection_reason": "video_phase_range_key_moment",
                    "confidence": 0.75,
                    "pre_refine_timestamp": 4.2,
                },
            ],
            "video_ai": {
                "confidence": 0.8,
                "action_confirmation": {"action_family": "jump", "confidence": 0.8},
                "key_moments": {"T_takeoff_sec": 3.4, "A_air_sec": 3.8, "L_landing_sec": 4.2},
                "phase_segments": [
                    {"phase_code": "approach", "time_start": 0.0, "time_end": 2.5, "confidence": 0.9},
                    {"phase_code": "preparation", "time_start": 2.5, "time_end": 3.2, "confidence": 0.85},
                    {"phase_code": "takeoff", "time_start": 3.2, "time_end": 3.6, "confidence": 0.8},
                    {"phase_code": "air", "time_start": 3.6, "time_end": 4.1, "confidence": 0.8},
                    {"phase_code": "landing", "time_start": 4.1, "time_end": 4.4, "confidence": 0.75},
                ],
            },
        }
        motion_scores = {
            "selected": [
                {"frame_id": "frame_0017", "timestamp": 1.875, "motion_score": 0.0573},
                {"frame_id": "frame_0018", "timestamp": 1.938, "motion_score": 0.0817},
                {"frame_id": "frame_0019", "timestamp": 2.0, "motion_score": 0.0692},
                {"frame_id": "frame_0027", "timestamp": 2.625, "motion_score": 0.0659},
                {"frame_id": "frame_0030", "timestamp": 2.75, "motion_score": 0.0410},
                {"frame_id": "frame_0040", "timestamp": 4.312, "motion_score": 0.0700},
            ]
        }
        bio_data = {
            "key_frame_candidates": {
                "quality_flags": [
                    "keyframe_candidates_excluded_unreliable_pose_frames",
                    "tal_candidate_temporal_geometry_unreliable",
                    "tal_candidate_apex_landing_gap_unreliable",
                    "tal_candidate_landing_geometry_weak",
                ],
                "T": {"timestamp": 1.812, "confidence": 0.34},
                "A": {"timestamp": 2.0, "confidence": 0.34},
                "L": {"timestamp": 2.062, "confidence": 0.34},
            }
        }

        changed = _maybe_reanchor_late_phase_range_tal(
            resolved,
            bio_data,
            motion_scores,
            analysis_profile="jump",
        )

        self.assertTrue(changed)
        self.assertEqual([item["timestamp"] for item in resolved["selected"]], [1.938, 2.418, 2.738])
        self.assertEqual(
            resolved["semantic_phase_range_late_reanchor"]["anchor_scope"],
            "skeleton_takeoff_near_pre_takeoff",
        )


if __name__ == "__main__":
    unittest.main()
