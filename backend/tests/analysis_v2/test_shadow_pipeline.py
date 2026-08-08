from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.analysis_v2.config import load_runtime_config
from app.analysis_v2.orchestration import ShadowArtifactStore, ShadowOrchestrator


def _config(tmp_path: Path):
    return load_runtime_config(
        {"SKATING_ANALYSIS_PIPELINE": "shadow", "V2_RUNTIME_ROOT": str(tmp_path / "runtime")},
        project_root=tmp_path,
    )


def _legacy() -> dict[str, object]:
    return {
        "analysis_id": "shadow-fixture",
        "analysis_profile": "jump",
        "pipeline_version": "legacy-v5",
        "source_fps": 30.0,
        "action_window_start": 0.0,
        "action_window_end": 2.0,
        "frame_motion_scores": {
            "video_identity": {"sha256": "a" * 64},
            "selected": [
                {"timestamp": index / 15, "source_thumb_index": index, "motion_score": 0.4 + (index % 3) * 0.1}
                for index in range(30)
            ],
        },
        "target_lock": {
            "status": "auto_locked",
            "selected_candidate_id": "target-1",
            "selected_bbox": {"x": 0.30, "y": 0.10, "width": 0.30, "height": 0.80},
        },
        "pose_data": {"frames": []},
        "bio_data": {},
        "vision_path_a": {},
        "vision_path_b": {},
        "cross_validation": {},
        "report": {"summary": "legacy authority"},
    }


def _run(tmp_path: Path, *, source_path: str | None = None):
    async def scenario():
        config = _config(tmp_path)
        orchestrator = ShadowOrchestrator(config)
        legacy = _legacy()
        before = json.loads(json.dumps(legacy))
        source_identity = {"video_hash": "a" * 64}
        if source_path:
            source_identity["source_path"] = source_path
        result = await orchestrator.run(
            legacy,
            analysis_id="shadow-fixture",
            source_identity=source_identity,
            pipeline_fingerprint="fixed-pipeline",
        )
        assert legacy == before
        assert result.status == "completed"
        assert result.first_invalid_stage is None
        saved = orchestrator.store.load_run(result.run_id or "")
        return orchestrator, saved

    return asyncio.run(scenario())


def test_default_factory_executes_all_stages_without_legacy_mutation(tmp_path: Path) -> None:
    orchestrator, run = _run(tmp_path)
    assert run.completed
    assert all(stage.artifact_reference for stage in run.stages)
    assert all(stage.output_hash for stage in run.stages)
    claims = orchestrator.store.read_artifact(run.run_id, "claims")
    assert claims["schema_version"] == "shadow-claims-stage.v1"
    assert "legacy authority" not in json.dumps(claims, ensure_ascii=False)


def test_ephemeral_source_path_is_not_persisted(tmp_path: Path) -> None:
    private_path = str(tmp_path / "private-source.mp4")
    Path(private_path).write_bytes(b"not-a-video")
    _orchestrator, run = _run(tmp_path, source_path=private_path)
    assert "source_path" not in run.source_identity
    manifest = Path(tmp_path / "runtime" / "shadow" / "v2" / "runs" / run.run_id / "run.json")
    assert private_path not in manifest.read_text(encoding="utf-8")


def test_fixed_fingerprint_repeatability(tmp_path: Path) -> None:
    first_orchestrator, first = _run(tmp_path / "first")
    second_orchestrator, second = _run(tmp_path / "second")
    assert first.pipeline_fingerprint == second.pipeline_fingerprint
    assert [stage.output_hash for stage in first.stages] == [stage.output_hash for stage in second.stages]
    assert [stage.fingerprint for stage in first.stages] == [stage.fingerprint for stage in second.stages]
    # The two stores remain independent; no artifact is written to a shared
    # legacy/data directory.
    assert first_orchestrator.store.root != second_orchestrator.store.root
    assert ShadowArtifactStore(first_orchestrator.store.runtime_root).has_run(first.run_id)
    assert ShadowArtifactStore(second_orchestrator.store.runtime_root).has_run(second.run_id)


def test_path_a_unobservable_payload_fails_soft_without_text_claims() -> None:
    from app.analysis_v2.path_review import normalize_path_a_review

    claims = normalize_path_a_review(
        {
            "action_phase_summary": {"detected_phases": ["jump"]},
            "visible_observations": ["stale text"],
            "contradictions": ["stale contradiction"],
        },
        target_policy={"identity_state": "unknown", "target_marking": "none"},
    )

    assert claims
    assert all(item.observability == "unobservable" for item in claims)
    assert all(item.status == "unobservable" for item in claims)
    assert all(item.value is None for item in claims)
