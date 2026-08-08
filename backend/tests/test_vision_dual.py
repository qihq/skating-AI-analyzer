from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import base64

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError
from app.services.llm_context import AnalysisPromptContext
from app.services.video import FramePayload
from app.services.vision_dual import analyze_frames_dual, dual_path_summary
from app.analysis_v2.facts import AnalysisFactV2, AnalysisFactsV2
from app.analysis_v2.presentation import present_analysis_experience


def _payloads(count: int) -> list[FramePayload]:
    return [
        FramePayload(
            frame_id=f"frame_{index + 1:04d}",
            data_url=f"data:image/jpeg;base64,{index}",
            timestamp_sec=index * 0.1,
        )
        for index in range(count)
    ]


def _path_a_result() -> dict:
    return {
        "path": "A",
        "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        "action_phase_summary": {"detected_phases": ["takeoff"]},
        "pure_vision_subscores": {
            "takeoff_power": 80,
            "rotation_axis": 80,
            "arm_coordination": 80,
            "landing_absorption": 80,
            "core_stability": 80,
        },
    }


def _path_b_result() -> dict:
    return {
        "path": "B",
        "n_frames": 1,
        "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        "action_phase_summary": {"detected_phases": ["takeoff"]},
        "subscores": {
            "takeoff_power": 80,
            "rotation_axis": 80,
            "arm_coordination": 80,
            "landing_absorption": 80,
            "core_stability": 80,
        },
    }


def _write_frames(root: Path, count: int = 1) -> list[Path]:
    frames_dir = root / "frames"
    frames_dir.mkdir()
    paths: list[Path] = []
    for index in range(count):
        path = frames_dir / f"frame_{index + 1:04d}.jpg"
        image = np.full((32, 32, 3), 255, dtype=np.uint8)
        cv2.putText(image, str(index), (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        assert cv2.imwrite(str(path), image)
        paths.append(path)
    return paths


class VisionDualTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_single_motion_proposal_uses_one_canonical_presenter_event(self) -> None:
        """The ordinary one-event path must not render proposal + canonical duplicates."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_paths = _write_frames(root, 1)
            provider = SimpleNamespace(
                api_key="key",
                base_url="https://example.com/v1",
                model_id="model",
                fingerprint="provider:fixture",
            )
            motion = {
                "window_end": 2.0,
                "selected": [{"frame_id": "frame_0001", "source_thumb_index": 10, "timestamp": 1.0, "motion_score": 0.9}],
            }
            lock = {
                "status": "auto_locked",
                "selected_bbox": {"x": .25, "y": .2, "width": .25, "height": .6},
            }
            policy = {
                "identity_state": "confirmed",
                "crop_bbox": (.25, .2, .25, .6),
                "context_before_sec": .5,
                "context_after_sec": .5,
                "includes_travel_context": True,
                "includes_ice_contact_context": True,
                "target_marking": "tracked_bbox_overlay",
            }
            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    pose_data=None,
                    bio_data=None,
                    provider_path_a=provider,
                    provider_path_b=provider,
                    annotated_dir=root / "annotated",
                    frame_motion_scores=motion,
                    analysis_profile="jump",
                    v2_mode=True,
                    analysis_id="analysis-single",
                    target_lock=lock,
                    target_clip_policy=policy,
                    identity_state="confirmed",
                )

        assert result.dual_path_meta["event_proposal_count"] == 1
        assert result.dual_path_meta["event_ids"] == ["analysis-single:event:0"]
        assert result.fused_claims
        assert all(claim.event_id in {"analysis-single:event:0", None} for claim in result.fused_claims)
        facts = AnalysisFactsV2(
            analysis_id="analysis-single",
            authority="v2",
            facts=tuple(
                AnalysisFactV2(
                    analysis_id=claim.analysis_id or "analysis-single",
                    event_id=claim.event_id,
                    claim_type=claim.claim_type,
                    value=claim.value,
                    authority="v2",
                    source_pipeline_fingerprint=str(claim.source_fingerprints.get("fusion") or "sha256:fixture"),
                    definition_version=claim.definition_version,
                    compatibility_group=claim.compatibility_group,
                    unit=claim.unit,
                    convention=claim.convention,
                    status=claim.status,
                    observability={"observed": "observable", "partial": "partially_observable", "unobservable": "unobservable"}[claim.observability],
                    confidence=claim.confidence,
                    sources=claim.sources,
                    conflicts=claim.conflicts,
                    source_fingerprints=claim.source_fingerprints,
                    provenance=claim.provenance,
                    source_references=claim.source_references,
                )
                for claim in result.fused_claims
            ),
        )
        rendered = present_analysis_experience({
            "id": "analysis-single",
            "facts_authority": "v2",
            "source_fact_hash": facts.source_fact_hash,
            "analysis_facts": {"schema_version": "analysis-facts.v2", **facts.model_dump(mode="json")},
        })
        assert [event.event_id for event in rendered.events] == ["analysis-single:event:0"]

    async def test_v2_multi_motion_proposals_keep_order_and_scope_exact_key_moments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_paths = _write_frames(root, 4)
            payloads = _payloads(4)
            provider = SimpleNamespace(
                api_key="key", base_url="https://example.com/v1", model_id="model", fingerprint="provider:fixture"
            )
            motion = {
                "window_end": 8.0,
                "selected": [
                    {"frame_id": "frame_0001", "source_thumb_index": 10, "timestamp": 1.0, "motion_score": .9},
                    {"frame_id": "frame_0002", "source_thumb_index": 11, "timestamp": 1.2, "motion_score": .8},
                    {"frame_id": "frame_0003", "source_thumb_index": 40, "timestamp": 4.0, "motion_score": .95},
                    {"frame_id": "frame_0004", "source_thumb_index": 41, "timestamp": 4.2, "motion_score": .85},
                ],
            }
            bio = {
                "key_frames": {"T": "frame_0001", "A": "frame_0003"},
                "key_frame_timestamps": {"T": 1.1, "A": 4.1},
            }
            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                result = await analyze_frames_dual(
                    "jump", frame_paths, payloads, None, bio, provider, provider,
                    annotated_dir=root / "annotated", frame_motion_scores=motion,
                    analysis_profile="jump", v2_mode=True, analysis_id="analysis-multi",
                )

        assert result.dual_path_meta["event_proposal_count"] == 2
        proposal_ids = result.dual_path_meta["event_ids"]
        assert len(proposal_ids) == 2
        assert result.fused_claims
        moment_claims = [claim for claim in result.fused_claims if claim.claim_type == "key_moment"]
        assert len(moment_claims) == 2
        assert [claim.event_id for claim in moment_claims] == proposal_ids
        action_claims = [claim for claim in result.fused_claims if claim.claim_type == "action_profile"]
        assert len(action_claims) == 1
        assert action_claims[0].event_id is None

    async def test_happy_path_and_summary_are_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    pose_data=None,
                    bio_data=None,
                    provider_path_a=provider,
                    provider_path_b=provider,
                    annotated_dir=Path(tmp) / "annotated",
                    timestamps={"frame_0001": 1.25},
                )

        self.assertEqual(result.path_a["path"], "A")
        self.assertEqual(result.path_b["path"], "B")
        self.assertIn(result.validation.recommended_path, {"blend", "A", "B"})
        self.assertEqual(result.used_key_frames, set())
        self.assertEqual(result.dual_path_meta["path_b_failed"], False)
        json.dumps(result.dual_path_meta, ensure_ascii=False)
        json.dumps(dual_path_summary(result), ensure_ascii=False)

    async def test_path_b_metadata_reports_stage_balanced_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 30)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            payloads = _payloads(30)
            evidence = {
                "records": [
                    {"timestamp": 1.0, "source": "mimo_key_moment", "phase": "takeoff"},
                    {"timestamp": 1.2, "source": "pose_candidate", "phase": "air"},
                    {"timestamp": 1.4, "source": "mimo_key_moment", "phase": "landing"},
                ]
            }
            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    payloads,
                    pose_data=None,
                    bio_data=None,
                    provider_path_a=provider,
                    provider_path_b=provider,
                    annotated_dir=Path(tmp) / "annotated",
                    analysis_profile="jump",
                    frame_motion_scores={"evidence_frames_v1": evidence},
                    timestamps={payload.frame_id: payload.timestamp_sec for payload in payloads},
                )

        self.assertEqual(result.dual_path_meta["path_b_stage_counts"], {"takeoff": 1, "air": 1, "landing": 1})
        self.assertEqual(result.dual_path_meta["path_b_evidence_sources"], ["mimo_key_moment", "pose_candidate"])
        self.assertTrue(result.dual_path_meta["path_b_cap_reason"].startswith("stage_quota"))

    async def test_path_b_error_is_soft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch(
                    "app.services.vision_dual.analyze_path_b",
                    new=AsyncMock(return_value={"path": "B", "error": "bad provider"}),
                ),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                )

        self.assertEqual(result.path_b["error"], "bad provider")
        self.assertEqual(result.validation.recommended_path, "A")
        self.assertEqual(result.dual_path_meta["path_b_failed"], True)

    async def test_path_a_parse_error_uses_path_b(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            with (
                patch(
                    "app.services.vision_dual.analyze_path_a",
                    new=AsyncMock(
                        side_effect=AnalysisPipelineError(
                            AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
                            "bad a",
                        )
                    ),
                ),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                )

        self.assertEqual(result.path_a["error"], "path_a_parse_failed")
        self.assertEqual(result.validation.recommended_path, "B")
        self.assertEqual(result.dual_path_meta["path_a_failed"], True)
        self.assertIn("path_a_parse_failed", result.dual_path_meta["path_a_error"])

    async def test_path_a_non_parse_error_is_hard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            with (
                patch(
                    "app.services.vision_dual.analyze_path_a",
                    new=AsyncMock(
                        side_effect=AnalysisPipelineError(
                            AnalysisErrorCode.UNKNOWN_ERROR,
                            "provider unavailable",
                        )
                    ),
                ),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
            ):
                with self.assertRaises(AnalysisPipelineError) as caught:
                    await analyze_frames_dual(
                        "jump",
                        frame_paths,
                        _payloads(1),
                        None,
                        None,
                        provider,
                        provider,
                        annotated_dir=Path(tmp) / "annotated",
                    )

        self.assertEqual(caught.exception.code, AnalysisErrorCode.UNKNOWN_ERROR)

    async def test_bio_none_and_pose_none_degrade_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            mock_b = AsyncMock(return_value=_path_b_result())

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=mock_b),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                )

        kwargs = mock_b.await_args.kwargs
        self.assertEqual(kwargs["frame_bio_context"], {})
        self.assertEqual(kwargs["key_frame_stems"], set())
        self.assertEqual(kwargs["jump_metrics_text"], "")
        self.assertEqual(result.used_key_frames, set())

    async def test_path_a_receives_bio_data_and_motion_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            bio_data = {
                "key_frame_candidates": {
                    "T": {"frame_id": "frame_0001", "confidence": 0.7},
                    "A": {"frame_id": "frame_0001", "confidence": 0.8},
                    "L": {"frame_id": "frame_0001", "confidence": 0.6},
                }
            }
            frame_motion_scores = {
                "sample_count": 3,
                "scores": [0.1, 0.8, 0.3],
                "selected": [{"frame_id": "frame_0001", "motion_score": 0.8}],
            }
            mock_a = AsyncMock(return_value=_path_a_result())

            with (
                patch("app.services.vision_dual.analyze_path_a", new=mock_a),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=_payloads(1))),
            ):
                await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    bio_data,
                    provider,
                    provider,
                    frame_motion_scores=frame_motion_scores,
                    annotated_dir=Path(tmp) / "annotated",
                )

        kwargs = mock_a.await_args.kwargs
        self.assertEqual(kwargs["bio_data"], bio_data)
        self.assertEqual(kwargs["motion_features"]["sample_count"], 3)
        self.assertEqual(kwargs["motion_features"]["score_summary"]["max"], 0.8)
        self.assertEqual(kwargs["motion_features"]["selected"], frame_motion_scores["selected"])

    async def test_timestamps_are_passed_to_annotated_encode_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            timestamps = {"frame_0001": 1.25}

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b_result())),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=_payloads(1))) as mock_encode,
            ):
                await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                    timestamps=timestamps,
                )

        self.assertEqual(mock_encode.await_args.kwargs["timestamps"], timestamps)

    async def test_path_b_timeout_preserves_annotated_frame_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 2)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")

            async def slow_b(*args: object, **kwargs: object) -> dict:
                await asyncio.sleep(0.05)
                return _path_b_result()

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())) as mock_a,
                patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(side_effect=slow_b)),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=_payloads(2))),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(2),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                    path_b_timeout=0.001,
                )

        self.assertEqual(result.path_b["error"], "path_b_timeout")
        self.assertEqual(result.path_b["n_frames"], 2)
        self.assertEqual(result.path_b["annotated_frame_count"], 2)
        self.assertEqual(result.dual_path_meta["annotated_frame_count"], 2)
        self.assertEqual(mock_a.await_count, 1)

    async def test_sampled_fallback_limits_path_b_payload_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 32)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            mock_b = AsyncMock(return_value={**_path_b_result(), "n_frames": 16})

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=mock_b),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=_payloads(32))),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(32),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=Path(tmp) / "annotated",
                )

        self.assertEqual(len(mock_b.await_args.kwargs["annotated_frame_payloads"]), 16)
        self.assertEqual(result.dual_path_meta["annotated_frame_count"], 16)
        self.assertEqual(result.dual_path_meta["annotated_frame_count_raw"], 32)

    async def test_path_b_payloads_are_compressed_without_changing_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_paths = []
            for index in range(6):
                path = root / "frames" / f"semantic_{index + 1:04d}.jpg"
                path.parent.mkdir(parents=True, exist_ok=True)
                image = np.full((720, 1280, 3), 255 - index, dtype=np.uint8)
                self.assertTrue(cv2.imwrite(str(path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 95]))
                frame_paths.append(path)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            selected = [
                {"frame_id": "semantic_0001", "timestamp": 1.0, "phase_code": "takeoff", "confidence": 0.8},
                {"frame_id": "semantic_0002", "timestamp": 1.2, "phase_code": "air", "confidence": 0.8},
                {"frame_id": "semantic_0003", "timestamp": 1.4, "phase_code": "landing", "confidence": 0.8},
            ]
            mock_b = AsyncMock(return_value={**_path_b_result(), "n_frames": 6})
            encoded_payloads = [
                FramePayload(
                    frame_id=f"semantic_{index + 1:04d}",
                    data_url="data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii"),
                    timestamp_sec=float(index),
                )
                for index, path in enumerate(frame_paths)
            ]

            with (
                patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_result())),
                patch("app.services.vision_dual.analyze_path_b", new=mock_b),
                patch("app.services.vision_dual._semantic_pose_for_annotation", return_value={"frames": [], "connections": []}),
                patch("app.services.vision_dual.annotate_frames_batch", return_value=frame_paths),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=encoded_payloads)),
            ):
                result = await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(6),
                    None,
                    None,
                    provider,
                    provider,
                    annotated_dir=root / "annotated",
                    resolved_keyframes={"source": "video_ai_refined", "selected": selected},
                )

        payloads = mock_b.await_args.kwargs["annotated_frame_payloads"]
        self.assertEqual(len(payloads), 6)
        self.assertEqual(result.dual_path_meta["annotated_frame_count"], 6)
        raw = base64.b64decode(payloads[0].data_url.split(",", maxsplit=1)[1])
        decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertLessEqual(decoded.shape[1], 640)

    async def test_prompt_context_keeps_pose_evidence_out_of_path_a(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(api_key="key", base_url="https://example.com/v1", model_id="model")
            mock_a = AsyncMock(return_value=_path_a_result())
            mock_b = AsyncMock(return_value=_path_b_result())
            profile_evidence = {
                "mixed_jump_gate_passed": True,
                "airborne_frames_detected": 7,
                "relative_vertical_range": 0.91,
                "hip_rotation_signal": 0.73,
                "jump_subtype_evidence": {
                    "toe_pick_pulse": 0.2,
                    "sentinel": "PATH_A_PROFILE_EVIDENCE_SENTINEL",
                },
            }
            context = AnalysisPromptContext(
                action_type="跳跃",
                action_subtype="Axel",
                skill_category="前进燕式",
                analysis_profile="jump",
                profile_evidence=profile_evidence,
                motion_features={"sample_count": 32},
                bio_data={"quality_flags": [], "sentinel": "PATH_A_BIO_SENTINEL"},
                user_note="今天起跳有点犹豫",
                memory_context="长期训练目标：稳定落冰。",
            )

            with (
                patch("app.services.vision_dual.analyze_path_a", new=mock_a),
                patch("app.services.vision_dual.analyze_path_b", new=mock_b),
                patch("app.services.vision_dual.encode_frames", new=AsyncMock(return_value=_payloads(1))),
            ):
                await analyze_frames_dual(
                    "跳跃",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    provider,
                    provider,
                    action_subtype="Axel",
                    analysis_profile="jump",
                    profile_evidence=profile_evidence,
                    skill_category="前进燕式",
                    prompt_context=context,
                    annotated_dir=Path(tmp) / "annotated",
                )

        context_text_a = mock_a.await_args.kwargs["memory_context"]
        context_text_b = mock_b.await_args.kwargs["memory_context"]
        self.assertIn("action_type: 跳跃", context_text_a)
        self.assertIn("action_subtype: Axel", context_text_a)
        self.assertIn("skill_category: 前进燕式", context_text_a)
        self.assertIn("上传备注/额外 comments: 今天起跳有点犹豫", context_text_a)
        self.assertIn("长期训练目标：稳定落冰", context_text_a)
        self.assertNotIn("PATH_A_BIO_SENTINEL", context_text_a)
        self.assertNotIn("PATH_A_PROFILE_EVIDENCE_SENTINEL", context_text_a)
        self.assertNotIn("profile_evidence", context_text_a)
        self.assertIn("PATH_A_BIO_SENTINEL", context_text_b)
        self.assertIn("PATH_A_PROFILE_EVIDENCE_SENTINEL", context_text_b)
        self.assertIn("profile_evidence", context_text_b)
        self.assertIsNone(mock_a.await_args.kwargs["profile_evidence"])
        self.assertEqual(
            mock_b.await_args.kwargs["profile_evidence"]["hip_rotation_signal"],
            0.73,
        )
        self.assertEqual(mock_b.await_args.kwargs["skill_category"], "前进燕式")


    async def test_v2_reviewers_do_not_receive_legacy_prompt_context(self) -> None:
        """V2 Path A/B inputs stay inside their dedicated contracts."""
        with tempfile.TemporaryDirectory() as tmp:
            frame_paths = _write_frames(Path(tmp), 1)
            provider = SimpleNamespace(
                api_key="key",
                base_url="https://example.com/v1",
                model_id="model",
                fingerprint="provider:fixture",
            )
            context = AnalysisPromptContext(
                action_type="jump",
                action_subtype="Axel",
                skill_category="jump",
                analysis_profile="jump",
                profile_evidence={"sentinel": "LEGACY_PROFILE_SENTINEL"},
                motion_features={"sentinel": "LEGACY_MOTION_SENTINEL"},
                bio_data={"sentinel": "LEGACY_BIO_SENTINEL"},
                user_note="LEGACY_NOTE_SENTINEL",
                memory_context="LEGACY_MEMORY_SENTINEL",
            )
            mock_a = AsyncMock(return_value=_path_a_result())
            mock_b = AsyncMock(return_value=_path_b_result())
            policy = {
                "identity_state": "confirmed",
                "crop_bbox": (.25, .2, .25, .6),
                "context_before_sec": .5,
                "context_after_sec": .5,
                "includes_travel_context": True,
                "includes_ice_contact_context": True,
                "target_marking": "tracked_bbox_overlay",
            }
            with (
                patch("app.services.vision_dual.analyze_path_a", new=mock_a),
                patch("app.services.vision_dual.analyze_path_b", new=mock_b),
            ):
                await analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    pose_data=None,
                    bio_data={"key_frame_candidates": {}},
                    provider_path_a=provider,
                    provider_path_b=provider,
                    prompt_context=context,
                    structured_measurements={
                        "knee_angle": {"value": 42, "provenance": "measured", "joint": "knee"},
                    },
                    required_joints=("knee",),
                    annotated_dir=Path(tmp) / "annotated",
                    v2_mode=True,
                    analysis_id="analysis-prompt-boundary",
                    target_lock={"status": "confirmed", "selected_bbox": {"x": .25, "y": .2, "width": .25, "height": .6}},
                    target_clip_policy=policy,
                    identity_state="confirmed",
                )

        self.assertEqual(mock_a.await_args.kwargs["memory_context"], "")
        self.assertEqual(mock_b.await_args.kwargs["memory_context"], "")

if __name__ == "__main__":
    unittest.main()
