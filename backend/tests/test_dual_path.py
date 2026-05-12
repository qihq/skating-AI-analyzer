from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import (  # noqa: E402
    analyze_frames_dual,
    build_frame_bio_context,
    compute_blend_weights,
    cross_validate,
    dual_path_summary,
    extract_key_frame_stems,
    summarize_jump_metrics,
)
from app.services.analysis_errors import AnalysisErrorCode, AnalysisPipelineError  # noqa: E402
from app.services.frame_annotator import annotate_frames_batch, build_pose_by_stem  # noqa: E402
from app.services.video import FramePayload, encode_frames  # noqa: E402


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


def _path_a(**subscores: int) -> dict:
    base = {
        "takeoff_power": 80,
        "rotation_axis": 80,
        "arm_coordination": 80,
        "landing_absorption": 80,
        "core_stability": 80,
    }
    base.update(subscores)
    return {
        "path": "A",
        "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        "action_phase_summary": {"detected_phases": ["takeoff"]},
        "pure_vision_subscores": base,
    }


def _path_b(**subscores: int) -> dict:
    base = {
        "takeoff_power": 80,
        "rotation_axis": 80,
        "arm_coordination": 80,
        "landing_absorption": 80,
        "core_stability": 80,
    }
    base.update(subscores)
    return {
        "path": "B",
        "n_frames": 1,
        "frame_analysis": [{"frame_id": "frame_0001", "phase": "takeoff"}],
        "action_phase_summary": {"detected_phases": ["takeoff"]},
        "subscores": base,
    }


def _write_frame(path: Path, value: int = 255) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.full((32, 32, 3), value, dtype=np.uint8)
    assert cv2.imwrite(str(path), image)
    return path


def _write_frames(root: Path, count: int = 1) -> list[Path]:
    return [_write_frame(root / "frames" / f"frame_{index + 1:04d}.jpg") for index in range(count)]


def test_happy_path(tmp_path: Path) -> None:
    """A/B both return valid JSON-like dicts -> blend, path_b_failed=False."""
    frame_paths = _write_frames(tmp_path)

    with (
        patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a())),
        patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b())),
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

    assert result.validation.recommended_path == "blend"
    assert result.dual_path_meta["recommended_path"] == "blend"
    assert result.dual_path_meta["path_b_failed"] is False


def test_path_b_soft_failure_isolation(tmp_path: Path) -> None:
    """Path B soft error must not mutate or hide Path A frame_analysis."""
    frame_paths = _write_frames(tmp_path)
    path_a = _path_a()

    with (
        patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=path_a)),
        patch(
            "app.services.vision_dual.analyze_path_b",
            new=AsyncMock(return_value={"path": "B", "error": "ConnectionError: offline"}),
        ),
    ):
        result = asyncio.run(
            analyze_frames_dual(
                "jump",
                frame_paths,
                _payloads(1),
                None,
                None,
                _provider(),
                _provider(),
                annotated_dir=tmp_path / "annotated",
            )
        )

    assert result.path_b["error"]
    assert result.path_a["frame_analysis"] == path_a["frame_analysis"]
    assert result.validation.recommended_path == "A"
    assert result.dual_path_meta["path_b_failed"] is True


def test_path_a_hard_failure_raises(tmp_path: Path) -> None:
    """Path A parse failures are hard pipeline errors."""
    frame_paths = _write_frames(tmp_path)

    with (
        patch(
            "app.services.vision_dual.analyze_path_a",
            new=AsyncMock(
                side_effect=AnalysisPipelineError(
                    AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL,
                    "invalid json",
                )
            ),
        ),
        patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b())),
    ):
        with pytest.raises(AnalysisPipelineError) as caught:
            asyncio.run(
                analyze_frames_dual(
                    "jump",
                    frame_paths,
                    _payloads(1),
                    None,
                    None,
                    _provider(),
                    _provider(),
                    annotated_dir=tmp_path / "annotated",
                )
            )

    assert caught.value.code == AnalysisErrorCode.AI_RESPONSE_PARSE_FAIL


def test_objective_disagreement_triggers_likely_wrong() -> None:
    """rotation_axis diff 30 and core_stability diff 25 -> likely_wrong, A."""
    report = cross_validate(_path_a(), _path_b(rotation_axis=50, core_stability=55))

    assert report.skeleton_reliability_signal == "likely_wrong"
    assert report.recommended_path == "A"


def test_subjective_only_disagreement_stays_uncertain() -> None:
    """Subjective-only major conflict should not become likely_wrong."""
    report = cross_validate(_path_a(), _path_b(arm_coordination=50))

    assert report.skeleton_reliability_signal != "likely_wrong"


def test_blend_weights_sum_invariant() -> None:
    """4 signal states x 3 agreement rates keep weight_a + weight_b == 1."""
    for signal in ["reliable", "uncertain", "likely_wrong", "unknown"]:
        for agreement_rate in [0.0, 0.5, 1.0]:
            report = cross_validate(_path_a(), _path_b())
            report.skeleton_reliability_signal = signal
            report.overall_agreement_rate = agreement_rate
            report.recommended_path = "blend"
            weight_a, weight_b = compute_blend_weights(report)

            assert weight_a + weight_b == pytest.approx(1.0, abs=0.001)


def test_bio_context_skips_missing() -> None:
    """A frame with both knees missing and no other metrics is omitted."""
    bio_data = {"knee_angles": [{"frame_idx": 1, "left": None, "right": None}]}

    assert build_frame_bio_context(bio_data, ["frame_0001"]) == {}


def test_key_frame_stems_jump_vs_spiral() -> None:
    """Jump key frames produce stems; spiral/non-jump empty key_frames produce set()."""
    jump = {"key_frames": {"takeoff": "frame_0017", "peak": "frame_0021", "landing": "frame_0025"}}

    assert extract_key_frame_stems(jump) == {"frame_0017", "frame_0021", "frame_0025"}
    assert extract_key_frame_stems({"key_frames": {}}) == set()


def test_summarize_jump_metrics_non_jump_returns_empty() -> None:
    """Non-jump or invalid jump metrics status returns an empty string."""
    assert summarize_jump_metrics({}) == ""
    assert summarize_jump_metrics({"jump_metrics_status": "invalid", "jump_metrics": {"air_time_seconds": 0.4}}) == ""


def test_annotator_handles_lost_keypoints(tmp_path: Path) -> None:
    """Lost keypoints are copied unchanged instead of raising."""
    src = _write_frame(tmp_path / "frames" / "frame_0001.jpg")
    pose_by_stem = build_pose_by_stem({"frames": [{"frame": "frame_0001.jpg", "keypoints": []}]})

    out = annotate_frames_batch([src], pose_by_stem, tmp_path / "annotated")

    assert out[0].read_bytes() == src.read_bytes()


def test_encode_frames_backward_compat(tmp_path: Path) -> None:
    """Omitting timestamps keeps data_url bytes identical and timestamp_sec at 0."""
    frame = _write_frame(tmp_path / "frames" / "frame_0001.jpg")

    legacy = asyncio.run(encode_frames([frame]))
    current = asyncio.run(encode_frames([frame], timestamps=None))

    assert [item.data_url for item in current] == [item.data_url for item in legacy]
    assert [item.timestamp_sec for item in current] == [0.0]


def test_dual_path_summary_serializable(tmp_path: Path) -> None:
    """dual_path_summary(result) contains no set/dataclass values."""
    frame_paths = _write_frames(tmp_path)

    with (
        patch("app.services.vision_dual.analyze_path_a", new=AsyncMock(return_value=_path_a())),
        patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(return_value=_path_b())),
    ):
        result = asyncio.run(
            analyze_frames_dual(
                "jump",
                frame_paths,
                _payloads(1),
                None,
                None,
                _provider(),
                _provider(),
                annotated_dir=tmp_path / "annotated",
            )
        )

    json.dumps(dual_path_summary(result), ensure_ascii=False)


def test_total_timeout_does_not_lose_path_a(tmp_path: Path) -> None:
    """Total timeout marks Path B total_timeout, then retries Path A alone."""
    frame_paths = _write_frames(tmp_path)
    mock_a = AsyncMock(return_value=_path_a())

    async def slow_b(*args: object, **kwargs: object) -> dict:
        await asyncio.sleep(0.05)
        return _path_b()

    with (
        patch("app.services.vision_dual.analyze_path_a", new=mock_a),
        patch("app.services.vision_dual.analyze_path_b", new=AsyncMock(side_effect=slow_b)),
    ):
        result = asyncio.run(
            analyze_frames_dual(
                "jump",
                frame_paths,
                _payloads(1),
                None,
                None,
                _provider(),
                _provider(),
                annotated_dir=tmp_path / "annotated",
                total_timeout=0.001,
            )
        )

    assert result.path_a["frame_analysis"]
    assert result.path_b["error"] == "total_timeout"
    assert result.validation.recommended_path == "A"
    assert mock_a.await_count == 2
