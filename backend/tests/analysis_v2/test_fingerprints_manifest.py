import json
import pytest

from app.analysis_v2.fingerprints import pipeline_fingerprint
from app.analysis_v2.manifest import RunManifest


def test_pipeline_fingerprint_is_stable_changes_on_relevant_inputs_and_redacts_secrets():
    base = dict(source_commit="abc", model_files={"pose": "hash1"}, configuration={"fps": 30}, provider="mimo", model="mimo-v2.5", prompt_version="p1", contract_version="contracts.v1", api_key="secret")
    first = pipeline_fingerprint(**base)
    assert first == pipeline_fingerprint(**base)
    assert first != pipeline_fingerprint(**{**base, "prompt_version": "p2"})
    assert "secret" not in first


def test_run_manifest_is_immutable_and_persists_atomically(tmp_path):
    manifest = RunManifest.create(source_identity={"video_hash": "sha256:v"}, pipeline_fingerprint="fp")
    manifest = manifest.with_stage_hashes("tracking", input_hash="in", output_hash="out")
    with pytest.raises((TypeError, AttributeError)):
        manifest.pipeline_fingerprint = "other"
    path = tmp_path / "manifest.json"
    manifest.persist(path)
    loaded = RunManifest.load(path)
    assert loaded == manifest
    assert json.loads(path.read_text())["pipeline_fingerprint"] == "fp"


def test_pipeline_fingerprint_redacts_nested_secret_fields():
    fingerprint = pipeline_fingerprint(
        source_commit="abc",
        model_files={"pose": "hash1"},
        configuration={"threshold": 0.5, "api_key": "nested-secret", "nested": {"token": "token-secret"}},
        provider="mimo",
        model="mimo-v2.5",
        prompt_version="p1",
        contract_version="contracts.v1",
    )

    assert fingerprint == pipeline_fingerprint(
        source_commit="abc",
        model_files={"pose": "hash1"},
        configuration={"threshold": 0.5, "api_key": "other-secret", "nested": {"token": "other-token"}},
        provider="mimo",
        model="mimo-v2.5",
        prompt_version="p1",
        contract_version="contracts.v1",
    )


def test_pipeline_fingerprint_changes_when_pose_provider_configuration_changes():
    base = dict(
        source_commit="abc",
        model_files={},
        configuration={"pose_provider_fingerprint": "sha256:pose-a", "POSE_NUM_POSES": 1},
        provider="mediapipe",
        model="pose",
        prompt_version="none",
        contract_version="v2",
    )
    first = pipeline_fingerprint(**base)
    changed = {**base, "configuration": {**base["configuration"], "pose_provider_fingerprint": "sha256:pose-b"}}
    assert first != pipeline_fingerprint(**changed)
