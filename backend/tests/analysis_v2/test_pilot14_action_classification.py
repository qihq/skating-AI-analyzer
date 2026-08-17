from pathlib import Path

from app.analysis_v2.evaluation.pilot12_event_proposals import evaluate_pilot14_action_classification


def test_g7_pilot_payload_is_policy_scoped(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    labels = tmp_path / "labels.json"
    snapshot.write_text("{}", encoding="utf-8")
    labels.write_text('{"events": []}', encoding="utf-8")
    result = evaluate_pilot14_action_classification(snapshot, labels)
    assert result["gate"] == "G7"
    assert result["gate_policy_version"] == "golden-gate-policy.v2"
    assert result["evidence_scope"] == "limited_sample"
    assert result["release_claim"] is False
