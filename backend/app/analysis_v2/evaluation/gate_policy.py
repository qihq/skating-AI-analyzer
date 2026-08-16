from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, model_validator

from app.analysis_v2.contracts import ContractModel


class CountRange(ContractModel):
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> "CountRange":
        if self.maximum < self.minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        return self


class GoldenGatePolicy(ContractModel):
    schema_version: Literal["golden-gate-policy.v2"] = "golden-gate-policy.v2"
    effective_date: Literal["2026-08-15"] = "2026-08-15"
    evidence_scope: Literal["limited_sample"] = "limited_sample"
    g1_source_video_minimum: int = 18
    g1_valid_event_minimum: int = 18
    g1_profile_minimums: dict[str, int] = Field(
        default_factory=lambda: {"jump": 10, "spin": 4, "step": 2, "spiral": 2}
    )
    g1_scene_minimums: dict[str, int] = Field(default_factory=lambda: {
        "normal": 1,
        "multi-skater": 1,
        "crossing/occlusion": 1,
        "small/distant target": 1,
        "pan/zoom": 1,
        "blur/compression": 1,
    })
    g1_recording_session_minimum: int = 5
    g1_delayed_review_minimum: int = 2
    g2_event_range: CountRange = Field(default_factory=lambda: CountRange(minimum=24, maximum=30))
    g2_profile_ranges: dict[str, CountRange] = Field(default_factory=lambda: {
        "jump": CountRange(minimum=10, maximum=14),
        "spin": CountRange(minimum=6, maximum=8),
        "step": CountRange(minimum=4, maximum=5),
        "spiral": CountRange(minimum=4, maximum=5),
    })
    pose_frame_range: CountRange = Field(default_factory=lambda: CountRange(minimum=24, maximum=40))
    subtype_reporting_minimum: int = 4
    subtype_reporting_target: int = 6


GOLDEN_GATE_POLICY = GoldenGatePolicy()
LEGACY_GATE_POLICY_VERSION = "golden-gate-policy.v1"


def artifact_gate_policy_version(payload: Mapping[str, object]) -> str:
    value = payload.get("gate_policy_version")
    return str(value) if isinstance(value, str) and value else LEGACY_GATE_POLICY_VERSION


def artifact_uses_current_policy(payload: Mapping[str, object]) -> bool:
    return artifact_gate_policy_version(payload) == GOLDEN_GATE_POLICY.schema_version


def gate_policy_summary() -> dict[str, object]:
    return GOLDEN_GATE_POLICY.model_dump(mode="json")


def classify_limited_sample_evidence(
    applicable_n: int,
    thresholds_met: bool,
    protocol_met: bool,
) -> tuple[str, bool]:
    if applicable_n <= 0:
        return "insufficient_sample", False
    if thresholds_met and protocol_met:
        return "limited_sample_candidate_pass", True
    if thresholds_met:
        return "blocked_waiting_for_frozen_candidate", False
    return "diagnostic_failed_or_insufficient", False


def limited_sample_gate_metadata(
    applicable_n: int,
    thresholds_met: bool,
    protocol_met: bool,
) -> dict[str, object]:
    status, gate_passed = classify_limited_sample_evidence(applicable_n, thresholds_met, protocol_met)
    return {
        "gate_policy_version": GOLDEN_GATE_POLICY.schema_version,
        "evidence_scope": GOLDEN_GATE_POLICY.evidence_scope,
        "status": status,
        "gate_passed": gate_passed,
        "release_claim": False,
    }
