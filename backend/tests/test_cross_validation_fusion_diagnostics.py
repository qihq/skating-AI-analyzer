from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np

from app.services.cross_validator import build_fusion_diagnostics, cross_validate
from app.services.video import FramePayload
from app.services.vision_dual import analyze_frames_dual, dual_path_summary


def _payloads(count: int) -> list[FramePayload]:
    return [
        FramePayload(
            frame_id=f"frame_{index + 1:04d}",
            data_url=f"data:image/jpeg;base64,{index}",
            timestamp_sec=index * 0.1,
        )
        for index in range(count)
    ]


def _provider() -> SimpleNamespace:
    return SimpleNamespace(api_key="test-key", base_url="https://example.com/v1", model_id="test-model")


def _write_frames(root: Path, count: int = 1) -> list[Path]:
    frames_dir = root / "frames"
    frames_dir.mkdir()
    paths: list[Path] = []
    for index in range(count):
        path = frames_dir / f"frame_{index + 1:04d}.jpg"
        image = np.full((32, 32, 3), 255, dtype=np.uint8)
        assert cv2.imwrite(str(path), image)
        paths.append(path)
    return paths


def _path_a_with_fusion(conflict_level: str = "high") -> dict[str, object]:
    return {
        "path": "A",
        "fusion_version": "v3_weighted_router",
        "conflict_level": conflict_level,
        "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        "action_phase_summary": {"detected_phases": ["takeoff"]},
        "pure_vision_subscores": {
            "takeoff_power": 80,
            "rotation_axis": 80,
            "arm_coordination": 80,
            "landing_absorption": 80,
            "core_stability": 80,
        },
        "fusion_decisions": [
            {
                "frame_id": "frame_0001",
                "conflict_level": conflict_level,
                "candidates": [
                    {
                        "provider": "qwen",
                        "rule_flags": ["rule_high_confidence_key_frame_conflict"],
                    }
                ],
            }
        ],
        "fusion_model_results": [
            {
                "provider": "qwen",
                "auto_eval": {
                    "key_frame_order_valid": False,
                    "phase_sequence_valid": False,
                    "high_confidence_conflicts": [{"frame_id": "frame_0001"}],
                },
            }
        ],
    }


def _path_b() -> dict[str, object]:
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


def test_high_conflict_fusion_requires_human_review() -> None:
    report = cross_validate(_path_a_with_fusion("high"), _path_b())

    diagnostics = report.fusion_diagnostics

    assert diagnostics["conflict_level"] == "high"
    assert diagnostics["needs_human_review"] is True
    assert diagnostics["key_frame_order_invalid"] is True
    assert "weighted_fusion_high_conflict" in diagnostics["downgraded_reasons"]
    assert "key_frame_order_invalid" in diagnostics["downgraded_reasons"]
    encoded = report.to_dict()
    assert encoded["fusion_diagnostics"]["needs_human_review"] is True
    json.dumps(encoded, ensure_ascii=False)


def test_path_b_failure_still_outputs_fusion_diagnostics(tmp_path: Path) -> None:
    frame_paths = _write_frames(tmp_path)

    with (
        patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a_with_fusion("medium"))),
        patch(
            "app.services.vision_dual.analyze_path_b",
            new=AsyncMock(return_value={"path": "B", "error": "offline"}),
        ),
    ):
        result = asyncio.run(
            analyze_frames_dual(
                "jump",
                frame_paths,
                _payloads(1),
                pose_data=None,
                bio_data=None,
                provider_path_a=_provider(),
                provider_path_b=_provider(),
                annotated_dir=tmp_path / "annotated",
            )
        )

    diagnostics = result.dual_path_meta["fusion_diagnostics"]
    summary = dual_path_summary(result)

    assert result.validation.recommended_path == "A"
    assert diagnostics["path_b"]["available"] is False
    assert diagnostics["path_b"]["downgraded_reasons"] == ["path_b_failed"]
    assert result.dual_path_meta["needs_human_review"] is True
    assert summary["needs_human_review"] is True
    assert summary["conflict_level"] == "high"
    json.dumps(summary, ensure_ascii=False)


def test_build_fusion_diagnostics_accepts_explicit_fusion_payload() -> None:
    diagnostics = build_fusion_diagnostics(
        {"path": "A", "frame_analysis": []},
        {"path": "B", "frame_analysis": []},
        {
            "fusion_version": "v3_weighted_router",
            "conflict_level": "low",
            "fusion_model_results": [{"auto_eval": {"key_frame_order_valid": False}}],
        },
    )

    assert diagnostics["weighted_fusion"]["available"] is True
    assert diagnostics["weighted_fusion"]["conflict_level"] == "low"
    assert diagnostics["needs_human_review"] is True
    assert diagnostics["key_frame_order_invalid"] is True
