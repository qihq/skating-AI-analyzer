from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis_v2.contracts import EvidenceClaim
from app.services.action_profiles import (
    attach_profile_evidence,
    infer_analysis_profile,
    profile_warning_from_evidence,
)
from app.services.llm_context import AnalysisPromptContext
from app.services.report import generate_report, local_fallback_report
from app.services.vision_prompt_templates import build_specialized_vision_prompt


def _frame(
    com_y: float,
    nose_y: float,
    left_ankle_y: float | None,
    right_ankle_y: float | None,
    *,
    center_x: float = 0.5,
    body_facing: float = 1.0,
    visibility: float | None = 0.99,
    frame_id: str | None = None,
    tracking_state: str | None = None,
) -> dict[str, object]:
    hip_y = com_y - 0.01
    shoulder_y = com_y + 0.01
    shoulder_half_width = 0.04 * body_facing
    hip_half_width = 0.025 * body_facing
    keypoints = [
        {"id": 0, "x": center_x, "y": nose_y, "visibility": visibility},
        {"id": 11, "x": center_x + shoulder_half_width, "y": shoulder_y, "visibility": visibility},
        {"id": 12, "x": center_x - shoulder_half_width, "y": shoulder_y, "visibility": visibility},
        {"id": 23, "x": center_x + hip_half_width, "y": hip_y, "visibility": visibility},
        {"id": 24, "x": center_x - hip_half_width, "y": hip_y, "visibility": visibility},
        {"id": 27, "x": center_x + 0.02, "y": left_ankle_y, "visibility": visibility},
        {"id": 28, "x": center_x - 0.02, "y": right_ankle_y, "visibility": visibility},
    ]
    frame: dict[str, object] = {"keypoints": keypoints}
    if frame_id is not None:
        frame["frame"] = frame_id
    if tracking_state is not None:
        frame["tracking_state"] = tracking_state
    return frame


def _rotation_pose() -> dict[str, object]:
    return {
        "frames": [
            _frame(0.60, 0.20, 0.80, 0.80, body_facing=facing)
            for facing in (1.0, 0.2, -1.0, -0.2, 1.0, 0.2, -1.0)
        ]
    }


def _airborne_pose() -> dict[str, object]:
    return {
        "frames": [
            _frame(0.60, 0.20, 0.80, 0.80),
            _frame(0.595, 0.20, 0.66, 0.65),
            _frame(0.59, 0.20, 0.64, 0.63),
            _frame(0.598, 0.20, 0.79, 0.80),
        ]
    }


def _step_pose() -> dict[str, object]:
    return {
        "frames": [
            _frame(0.60, 0.20, 0.80, 0.80, center_x=0.20),
            _frame(0.60, 0.20, 0.80, 0.80, center_x=0.42),
            _frame(0.60, 0.20, 0.80, 0.80, center_x=0.68),
            _frame(0.60, 0.20, 0.80, 0.80, center_x=0.82),
        ]
    }


def _mixed_spin_evidence() -> dict[str, object]:
    _, evidence = infer_analysis_profile(
        "自由滑",
        "节目片段",
        _rotation_pose(),
        {"scores": [0.02, 0.08, 0.09, 0.07, 0.08, 0.09, 0.07]},
    )
    return evidence


def _provider() -> SimpleNamespace:
    return SimpleNamespace(
        id="profile-report-provider",
        slot="report",
        name="profile-report-provider",
        provider="openai_compatible",
        base_url="https://example.com/v1",
        model_id="test-report-model",
        vision_model=None,
        api_key="test-key",
        notes=None,
    )


def _report_json() -> str:
    return """
    {
      "summary": "动作整体稳定。",
      "issues": [],
      "improvements": [{"target": "轴心", "action": "保持基础练习"}],
      "training_focus": "稳定轴心。",
      "subscores": {
        "takeoff_power": 90,
        "rotation_axis": 80,
        "arm_coordination": 70,
        "landing_absorption": 60,
        "core_stability": 50
      },
      "data_quality": "good"
    }
    """


def _claim() -> EvidenceClaim:
    return EvidenceClaim(
        analysis_id="analysis-1",
        event_id="analysis-1:event:0",
        claim_type="action_profile",
        value="jump",
        sources=("deterministic",),
        source_fingerprints={"deterministic": "sha256:deterministic"},
        definition_version="deterministic-action-profile.v2",
        compatibility_group="action-profile/family/v2",
        confidence=0.9,
        observability="observed",
        status="confirmed",
    )


class ProfileAmbiguityTests(unittest.TestCase):
    def test_mixed_rotation_without_airborne_is_low_confidence_ambiguous_spin_route(self) -> None:
        profile, evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            _rotation_pose(),
            {"scores": [0.02, 0.08, 0.09, 0.07, 0.08, 0.09, 0.07]},
        )

        self.assertEqual(profile, "spin")
        self.assertEqual(evidence["airborne_frames_detected"], 0)
        self.assertEqual(evidence["profile_confidence"], "low")
        self.assertTrue(evidence["profile_route_only"])
        self.assertTrue(evidence["jump_spin_ambiguous"])
        self.assertIn("jump_spin_ambiguous", evidence["quality_flags"])
        self.assertIn("mixed_action_profile_inferred_spin_from_rotation", evidence["quality_flags"])
        constraints = " ".join(evidence["negative_constraints"])
        self.assertIn("不能排除跳跃", constraints)
        self.assertIn("周数", constraints)
        warning = profile_warning_from_evidence(evidence)
        self.assertIn("原始骨架", warning)
        self.assertIn("不能确认动作类型", warning)
        self.assertNotIn("系统仅按旋转方向路由分析", warning)

    def test_mixed_default_step_is_route_only_and_does_not_deny_jump(self) -> None:
        profile, evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            _step_pose(),
            {"scores": [0.02, 0.08, 0.09, 0.07]},
        )

        self.assertEqual(profile, "step")
        self.assertEqual(evidence["profile_confidence"], "low")
        self.assertTrue(evidence["profile_route_only"])
        constraints = " ".join(evidence["negative_constraints"])
        self.assertIn("未检出不代表", constraints)
        self.assertIn("不能据此否定跳跃", constraints)
        warning = profile_warning_from_evidence(evidence)
        self.assertIn("仅凭这些线索不能判断当前动作", warning)
        self.assertNotIn("暂按步法路由分析", warning)

    def test_mixed_jump_gate_is_heuristic_candidate_not_confirmation(self) -> None:
        profile, evidence = infer_analysis_profile(
            "自由滑",
            "节目片段",
            _airborne_pose(),
            {"scores": [0.02, 0.03, 0.04, 0.02]},
        )

        self.assertEqual(profile, "jump")
        self.assertTrue(evidence["mixed_jump_gate_passed"])
        self.assertEqual(evidence["profile_confidence"], "medium")
        self.assertTrue(evidence["profile_route_only"])
        constraints = " ".join(evidence["negative_constraints"])
        self.assertIn("候选", constraints)
        self.assertIn("不等同于冰刀离冰事实", constraints)

    def test_explicit_jump_label_controls_route_but_is_not_confirmation(self) -> None:
        gate_profile, gate_evidence = infer_analysis_profile(
            "跳跃",
            "单跳",
            _airborne_pose(),
            {"scores": [0.02, 0.03, 0.04, 0.02]},
        )
        no_gate_profile, no_gate_evidence = infer_analysis_profile(
            "跳跃",
            "单跳",
            _rotation_pose(),
            {"scores": [0.02, 0.08, 0.09, 0.07, 0.08, 0.09, 0.07]},
        )

        self.assertEqual(gate_profile, "jump")
        self.assertTrue(gate_evidence["jump_gate_passed"])
        self.assertTrue(gate_evidence["profile_route_only"])
        gate_warning = profile_warning_from_evidence(gate_evidence)
        self.assertIn("用户输入标签", gate_warning)
        self.assertIn("不代表动作已自动确认", gate_warning)

        self.assertEqual(no_gate_profile, "jump")
        self.assertFalse(no_gate_evidence["jump_gate_passed"])
        self.assertEqual(no_gate_evidence["profile_confidence"], "low")
        self.assertTrue(no_gate_evidence["profile_route_only"])
        self.assertIn("jump_gate_not_passed", no_gate_evidence["quality_flags"])
        no_gate_warning = profile_warning_from_evidence(no_gate_evidence)
        self.assertIn("用户输入标签", no_gate_warning)
        self.assertIn("不能确认", no_gate_warning)

    def test_video_family_recovery_does_not_upgrade_original_skeleton_evidence(self) -> None:
        evidence = copy.deepcopy(_mixed_spin_evidence())
        evidence["video_ai_action_family"] = "jump"
        evidence["video_ai_action_family_confidence"] = 0.95

        warning = profile_warning_from_evidence(evidence)
        attached = attach_profile_evidence({}, evidence)

        self.assertIn("原始骨架", warning)
        self.assertIn("不能确认动作类型", warning)
        self.assertIn("不能排除跳跃", warning)
        self.assertIn("不改变原始骨架的置信度、腾空门槛或动作确认状态", warning)
        self.assertNotIn("系统仅按旋转方向路由分析", warning)
        self.assertEqual(attached["profile_evidence"]["profile_confidence"], "low")
        self.assertEqual(attached["profile_evidence"]["jump_gate_passed"], False)
        self.assertEqual(attached["profile_evidence"]["airborne_frames_detected"], 0)
        self.assertEqual(attached["profile_evidence"]["video_ai_action_family"], "jump")


class AttachProfileEvidenceTests(unittest.TestCase):
    def test_helper_does_not_mutate_inputs_and_is_idempotent(self) -> None:
        evidence = _mixed_spin_evidence()
        bio = {
            "quality_flags": ["legacy_flag", "legacy_flag"],
            "jump_metrics_warning": "旧指标限制保持可见",
            "nested": {"value": 1},
        }
        bio_before = copy.deepcopy(bio)
        evidence_before = copy.deepcopy(evidence)

        attached = attach_profile_evidence(bio, evidence)

        self.assertIsNot(attached, bio)
        self.assertEqual(bio, bio_before)
        self.assertEqual(evidence, evidence_before)
        self.assertIn("legacy_flag", attached["quality_flags"])
        self.assertEqual(attached["quality_flags"].count("legacy_flag"), 1)
        self.assertIsNot(attached["profile_evidence"], evidence)
        self.assertEqual(attached["profile_evidence"], evidence)
        self.assertEqual(attached["profile_evidence"]["jump_gate_passed"], False)
        self.assertEqual(attached["profile_evidence"]["airborne_frames_detected"], 0)
        self.assertEqual(attached["jump_metrics_warning"], "旧指标限制保持可见")
        self.assertTrue(attached["profile_warning"])
        self.assertNotIn("jump_spin_ambiguous", attached["profile_warning"])
        self.assertNotIn("mixed_action_profile_", attached["profile_warning"])
        self.assertEqual(attached["profile_evidence"]["negative_constraints"], evidence["negative_constraints"])

        attached_again = attach_profile_evidence(attached, evidence)

        self.assertEqual(attached_again["quality_flags"], attached["quality_flags"])
        self.assertEqual(attached_again["profile_evidence"], attached["profile_evidence"])
        self.assertEqual(attached_again["profile_warning"], attached["profile_warning"])
        self.assertEqual(
            attached_again["profile_evidence"]["negative_constraints"],
            evidence["negative_constraints"],
        )

    def test_local_fallback_keeps_profile_warning_after_summary_override(self) -> None:
        attached = attach_profile_evidence({"quality_flags": []}, _mixed_spin_evidence())
        warning = attached["profile_warning"]

        report = local_fallback_report("自由滑", {"frame_analysis": []}, attached)

        self.assertEqual(report["profile_warning"], warning)
        self.assertIn(warning, report["summary"])
        self.assertTrue(
            any(
                isinstance(issue, dict) and issue.get("category") == "动作分类边界"
                for issue in report["issues"]
            )
        )

    def test_vision_prompt_treats_profile_as_route_not_fact(self) -> None:
        evidence = _mixed_spin_evidence()
        _, user_prompt = build_specialized_vision_prompt(
            "自由滑",
            "节目片段",
            "spin",
            profile_evidence=evidence,
        )

        self.assertIn("不是已确认动作", user_prompt)
        self.assertIn("不能循环确证 jump", user_prompt)
        self.assertIn("不能排除跳跃", profile_warning_from_evidence(evidence))
        self.assertNotIn("请勿推翻", user_prompt)


class ReportProfileBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_report_prompt_and_fallback_consume_profile_boundary(self) -> None:
        attached = attach_profile_evidence({}, _mixed_spin_evidence())
        warning = attached["profile_warning"]
        request_mock = AsyncMock(return_value=_report_json())

        async def _run() -> dict[str, object]:
            with (
                patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.report.request_text_completion", request_mock),
            ):
                return await generate_report("自由滑", {"frame_analysis": []}, bio_data=attached)

        report = await _run()
        prompt = request_mock.await_args.kwargs["messages"][1]["content"]

        self.assertIn("动作分类路由边界", prompt)
        self.assertIn("标签来源", prompt)
        self.assertIn("候选线索", prompt)
        self.assertIn("未排除边界", prompt)
        self.assertIn("jump_features 或几何候选不能循环证明", prompt)
        self.assertIn(warning, prompt)
        self.assertEqual(report["profile_warning"], warning)
        self.assertIn(warning, report["summary"])
        self.assertTrue(
            any(
                isinstance(issue, dict) and issue.get("category") == "动作分类边界"
                for issue in report["issues"]
            )
        )

    async def test_claim_only_report_does_not_consume_legacy_profile(self) -> None:
        attached = attach_profile_evidence(
            {"raw_bio_secret": "LEGACY_PROFILE_SENTINEL"},
            _mixed_spin_evidence(),
        )
        request_mock = AsyncMock(return_value=_report_json())

        async def _run() -> dict[str, object]:
            with (
                patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.report.request_text_completion", request_mock),
            ):
                return await generate_report(
                    "jump",
                    {"raw_vision_secret": "LEGACY_VISION_SENTINEL"},
                    attached,
                    fused_claims=(_claim(),),
                )

        report = await _run()
        prompt = request_mock.await_args.kwargs["messages"][1]["content"]
        serialized_report = json.dumps(report, ensure_ascii=False, default=str)

        for sentinel in (
            "LEGACY_PROFILE_SENTINEL",
            "LEGACY_VISION_SENTINEL",
            "profile_warning",
            "profile_evidence",
        ):
            self.assertNotIn(sentinel, prompt)
            self.assertNotIn(sentinel, serialized_report)

    async def test_native_v2_ai_disabled_is_claim_only_for_empty_and_nonempty_claims(self) -> None:
        sentinels = (
            "LEGACY_PROFILE_SENTINEL",
            "LEGACY_VISION_SENTINEL",
            "LEGACY_DUAL_SENTINEL",
            "LEGACY_PROMPT_SENTINEL",
        )
        for claims in ((_claim(),), ()):
            with self.subTest(claim_count=len(claims)):
                attached = attach_profile_evidence(
                    {"legacy_marker": sentinels[0]},
                    _mixed_spin_evidence(),
                )
                provider_mock = AsyncMock(side_effect=AssertionError("native V2 must not resolve provider"))
                memory_mock = AsyncMock(side_effect=AssertionError("native V2 must not resolve memory"))
                request_mock = AsyncMock(side_effect=AssertionError("native V2 must not call AI"))
                prompt_context = AnalysisPromptContext(
                    action_type=sentinels[3],
                    action_subtype=sentinels[3],
                    skill_category=sentinels[3],
                    analysis_profile=sentinels[3],
                    profile_evidence={"secret": sentinels[3]},
                    motion_features={"secret": sentinels[3]},
                    bio_data={"secret": sentinels[3]},
                    user_note=sentinels[3],
                    memory_context=sentinels[3],
                )

                with (
                    patch("app.trial.external_ai_allowed", return_value=False),
                    patch("app.services.report.get_active_provider", provider_mock),
                    patch("app.services.report.build_memory_context", memory_mock),
                    patch("app.services.report.request_text_completion", request_mock),
                ):
                    report = await generate_report(
                        "jump",
                        {"raw_vision_secret": sentinels[1]},
                        attached,
                        "skater-1",
                        dual_path_meta={"legacy_marker": sentinels[2]},
                        prompt_context=prompt_context,
                        fused_claims=claims,
                    )

                serialized_report = json.dumps(report, ensure_ascii=False, default=str)
                for sentinel in sentinels:
                    self.assertNotIn(sentinel, serialized_report)
                self.assertNotIn("profile_warning", report)
                self.assertNotIn("profile_evidence", report)
                self.assertIn("unsupported_claims", report)
                self.assertIn("evidence_claims", report)
                self.assertIn("report_source_fact_hash", report)
                provider_mock.assert_not_awaited()
                memory_mock.assert_not_awaited()
                request_mock.assert_not_awaited()

    async def test_legacy_native_ai_disabled_still_emits_profile_warning(self) -> None:
        attached = attach_profile_evidence({}, _mixed_spin_evidence())
        warning = attached["profile_warning"]
        provider_mock = AsyncMock(side_effect=AssertionError("legacy local fallback must not resolve provider"))

        with patch("app.trial.external_ai_allowed", return_value=False), patch(
            "app.services.report.get_active_provider", provider_mock
        ):
            report = await generate_report("自由滑", {"frame_analysis": []}, attached)

        self.assertEqual(report["profile_warning"], warning)
        self.assertIn(warning, report["summary"])
        self.assertTrue(
            any(
                isinstance(issue, dict) and issue.get("category") == "动作分类边界"
                for issue in report["issues"]
            )
        )
        provider_mock.assert_not_awaited()

    def test_normalize_report_preserves_optional_profile_warning(self) -> None:
        from app.services.report import normalize_report

        warning = "当前动作分类仅作为分析路由，不代表已确认具体动作或周数。"
        report = normalize_report(
            {
                "summary": "ok",
                "issues": [],
                "improvements": [],
                "training_focus": "focus",
                "profile_warning": warning,
            },
            bio_data=None,
        )

        self.assertEqual(report["profile_warning"], warning)


if __name__ == "__main__":
    unittest.main()
