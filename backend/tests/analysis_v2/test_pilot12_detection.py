from pathlib import Path

from app.analysis_v2.evaluation.pilot12_detection import evaluate_pilot12_detection


def test_imported_pilot12_fixture_is_deterministic_and_identity_safe() -> None:
    fixture = Path(__file__).parents[3] / ".." / ".." / "skating-analyzer-v2-runtime" / "test-data" / "pilot-12-run-20260801" / "api-analysis-index-live.json"
    if not fixture.exists():
        return
    first = evaluate_pilot12_detection(fixture)
    second = evaluate_pilot12_detection(fixture)
    assert first["analysis_count"] == 12
    assert first["candidate_count"] > 0
    assert first["diagnostic_only"] is True
    assert first["identity_decisions"] is False
    assert first["result_fingerprint"] == second["result_fingerprint"]
