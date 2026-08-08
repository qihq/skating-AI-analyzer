from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.analysis_v2.contracts import EvidenceClaim
from app.analysis_v2.claim_report import constrain_report_payload
from app.services.llm_context import AnalysisPromptContext
from app.services.report import generate_report


def _provider() -> SimpleNamespace:
    return SimpleNamespace(
        id="v2-report",
        slot="report",
        provider="openai_compatible",
        model_id="test-model",
        notes=None,
    )


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


class ClaimReportAuthorityTests(unittest.TestCase):
    def test_report_exact_timestamp_and_turns_must_match_claim_values(self) -> None:
        timestamp_claim = EvidenceClaim(
            analysis_id="analysis-1",
            event_id="analysis-1:event:0",
            claim_type="key_moment",
            value={"phase": "T", "pts_sec": 12.3},
            sources=("key_moment", "deterministic"),
            source_fingerprints={"deterministic": "fp"},
            definition_version="deterministic-key-moment.v2",
            compatibility_group="key-moment/source-pts/v2",
            unit="source_pts",
            confidence=.9,
            observability="observed",
            status="confirmed",
        )
        rotation_claim = EvidenceClaim(
            analysis_id="analysis-1",
            event_id="analysis-1:event:0",
            claim_type="rotation",
            value={"value_turns": 2.5},
            sources=("rotation_estimator",),
            source_fingerprints={"rotation_estimator": "fp"},
            definition_version="airborne-body-rotation.source-pts.v1",
            compatibility_group="rotation/airborne-body/source-pts/v1",
            unit="turns",
            convention="airborne_body_rotation",
            confidence=.9,
            observability="observed",
            status="confirmed",
        )
        claims = (timestamp_claim, rotation_claim)
        exact = constrain_report_payload({"timestamp": 12.3, "turns": 2.5}, claims)
        self.assertEqual(exact.get("timestamp"), 12.3)
        self.assertEqual(exact.get("turns"), 2.5)
        self.assertEqual(exact["unsupported_claims"], [])

        invented = constrain_report_payload({"timestamp": 12.4, "turns": 3}, claims)
        self.assertNotIn("timestamp", invented)
        self.assertNotIn("turns", invented)
        self.assertEqual(
            invented["unsupported_claims"],
            ["invented_timestamp", "invented_rotation"],
        )

    def test_uncertain_or_path_a_values_cannot_authorize_exact_report_fields(self) -> None:
        claims = (
            EvidenceClaim(
                analysis_id="analysis-1",
                claim_type="key_moment",
                value={"pts_sec": 4.0},
                sources=("path_a",),
                source_fingerprints={"path_a": "fp"},
                confidence=.8,
                observability="observed",
                status="confirmed",
            ),
            EvidenceClaim(
                analysis_id="analysis-1",
                claim_type="rotation",
                value={"value_turns": 1.5},
                sources=("rotation_estimator",),
                source_fingerprints={"rotation_estimator": "fp"},
                confidence=.4,
                observability="partial",
                status="uncertain",
            ),
        )
        constrained = constrain_report_payload({"timestamp": 4.0, "turns": 1.5}, claims)
        self.assertNotIn("timestamp", constrained)
        self.assertNotIn("turns", constrained)
        self.assertEqual(
            constrained["unsupported_claims"],
            ["invented_timestamp", "invented_rotation"],
        )

    def test_action_family_support_does_not_authorize_invented_concrete_label(self) -> None:
        family = _claim()
        invented = constrain_report_payload(
            {"action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop"}},
            (family,),
        )
        self.assertEqual(invented["action_confirmation"]["action_family"], "jump")
        self.assertNotIn("confirmed_action", invented["action_confirmation"])
        self.assertEqual(invented["unsupported_claims"], ["invented_action"])

        label = EvidenceClaim(
            analysis_id="analysis-1",
            event_id="analysis-1:event:0",
            claim_type="action_label",
            value="Toe Loop",
            sources=("human_confirmation",),
            source_fingerprints={"human_confirmation": "fp"},
            confidence=1,
            observability="observed",
            status="confirmed",
        )
        supported = constrain_report_payload(
            {"action_confirmation": {"action_family": "jump", "confirmed_action": "Toe Loop"}},
            (family, label),
        )
        self.assertEqual(supported["action_confirmation"]["confirmed_action"], "Toe Loop")
        self.assertEqual(supported["unsupported_claims"], [])

    def test_v2_report_prompt_is_claim_only_and_unsupported_fields_are_removed(self) -> None:
        response = (
            '{"summary":"ok","issues":[{"category":"invented","description":"invented defect",'
            '"severity":"high"}],"improvements":[],"training_focus":"review",'
            '"subscores":{"takeoff_power":70,"rotation_axis":70,"arm_coordination":70,'
            '"landing_absorption":70,"core_stability":70},"data_quality":"good",'
            '"action_confirmation":{"action_family":"spin"},"timestamp":12.3,"turns":3}'
        )
        request = AsyncMock(return_value=response)
        async def _run() -> dict[str, object]:
            with (
                patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.report.build_memory_context", AsyncMock(return_value="")),
                patch("app.services.report.request_text_completion", request),
            ):
                return await generate_report(
                    "jump",
                    {"raw_vision_secret": "must-not-leak"},
                    {"raw_bio_secret": "must-not-leak"},
                    fused_claims=(_claim(),),
                )

        report = asyncio.run(_run())

        prompt = request.await_args.kwargs["messages"][1]["content"]
        self.assertNotIn("must-not-leak", prompt)
        self.assertNotIn("raw_vision_secret", prompt)
        self.assertNotIn("raw_bio_secret", prompt)
        self.assertIn("deterministic-action-profile.v2", prompt)
        self.assertNotIn("action_confirmation", report)
        self.assertNotIn("timestamp", report)
        self.assertNotIn("turns", report)
        self.assertEqual(
            report["unsupported_claims"],
            ["invented_action", "invented_timestamp", "invented_rotation", "invented_technique_defect"],
        )
        self.assertEqual(report["evidence_claims"]["claims"][0]["value"], "jump")

    def test_v2_report_does_not_render_legacy_prompt_context_or_memory(self) -> None:
        request = AsyncMock(
            return_value=(
                '{"summary":"ok","issues":[],"improvements":[],"training_focus":"review",'
                '"subscores":{"takeoff_power":70,"rotation_axis":70,"arm_coordination":70,'
                '"landing_absorption":70,"core_stability":70},"data_quality":"good"}'
            )
        )
        context = AnalysisPromptContext(
            action_type="LEGACY_ACTION_TYPE_SENTINEL",
            action_subtype="LEGACY_SUBTYPE_SENTINEL",
            skill_category="LEGACY_SKILL_SENTINEL",
            analysis_profile="LEGACY_PROFILE_SENTINEL",
            profile_evidence={"secret": "LEGACY_PROFILE_EVIDENCE_SENTINEL"},
            motion_features={"secret": "LEGACY_MOTION_SENTINEL"},
            bio_data={"secret": "LEGACY_BIO_SENTINEL"},
            user_note="FAMILY_SAFE_USER_QUESTION_SENTINEL",
            memory_context="LEGACY_MEMORY_SENTINEL",
        )
        memory = AsyncMock(side_effect=AssertionError("V2 claim-only report must not resolve Snowball memory"))

        async def _run() -> dict[str, object]:
            with (
                patch("app.services.report.get_active_provider", AsyncMock(return_value=_provider())),
                patch("app.services.report.build_memory_context", memory),
                patch(
                    "app.services.report.render_prompt_context",
                    side_effect=AssertionError("V2 claim-only report must not render legacy prompt context"),
                ) as render_context,
                patch("app.services.report.request_text_completion", request),
            ):
                result = await generate_report(
                    "jump",
                    {"raw_vision_secret": "LEGACY_VISION_SENTINEL"},
                    {"raw_bio_secret": "LEGACY_RAW_BIO_SENTINEL"},
                    "skater-1",
                    prompt_context=context,
                    fused_claims=(_claim(),),
                )
                render_context.assert_not_called()
                return result

        asyncio.run(_run())

        memory.assert_not_awaited()
        messages = request.await_args.kwargs["messages"]
        prompt = messages[1]["content"]
        self.assertIn("FAMILY_SAFE_USER_QUESTION_SENTINEL", prompt)
        for sentinel in (
            "LEGACY_ACTION_TYPE_SENTINEL",
            "LEGACY_SUBTYPE_SENTINEL",
            "LEGACY_SKILL_SENTINEL",
            "LEGACY_PROFILE_SENTINEL",
            "LEGACY_PROFILE_EVIDENCE_SENTINEL",
            "LEGACY_MOTION_SENTINEL",
            "LEGACY_BIO_SENTINEL",
            "LEGACY_MEMORY_SENTINEL",
            "LEGACY_VISION_SENTINEL",
            "LEGACY_RAW_BIO_SENTINEL",
        ):
            self.assertNotIn(sentinel, prompt)
            self.assertNotIn(sentinel, messages[0]["content"])
