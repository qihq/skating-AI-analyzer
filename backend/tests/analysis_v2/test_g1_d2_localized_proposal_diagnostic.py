from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.g1_d2_localized_proposal_diagnostic import analyze_diagnostic


def _diagnostic() -> dict:
    samples = [
        {
            "source_frame_index": index,
            "pts_sec": index * .2,
            "camera_compensated_track_motion": .36 if 10 <= index <= 12 else .04,
            "pose_dynamics": .24 if 10 <= index <= 12 else .02,
            "edge_complexity": .22 if 10 <= index <= 12 else .04,
            "tracking_observable": True,
            "pose_observable": 10 <= index <= 12,
            "provenance": ["source_pts", "source_only_adapter"],
        }
        for index in range(30)
    ]
    return {
        "videos": [{
            "status": "ok",
            "raw_diagnostics": {
                "source_evidence": {
                    "source_video_hash": "sha256:source-a",
                    "source_duration_sec": 6.0,
                    "proposal_samples": samples,
                    "proposal_collection": {"proposals": []},
                },
            },
        }],
    }


def test_diagnostic_reports_the_localized_upgrade_without_downstream_invocation() -> None:
    result = analyze_diagnostic(_diagnostic())

    assert result["aggregate"]["localized_proposal_count_before"] == 0
    assert result["aggregate"]["localized_proposal_count_after"] == 1
    assert result["aggregate"]["net_new_localized_proposal_count"] == 1
    assert result["aggregate"]["recorded_collection_source_count"] == 1
    assert result["aggregate"]["baseline_matches_recorded_source_count"] == 0
    assert result["aggregate"]["sources_gaining_localized"] == 1
    assert result["aggregate"]["sources_with_changed_localized_output"] == 1
    assert result["golden_labels_consumed"] is False
    assert result["classification_invoked"] is False
    assert result["moments_invoked"] is False
    assert result["rotation_invoked"] is False
    assert result["formal_pilot_invoked"] is False


def test_diagnostic_is_invariant_to_unread_golden_shaped_fields() -> None:
    baseline = analyze_diagnostic(_diagnostic())
    with_private_labels = _diagnostic()
    with_private_labels["golden"] = {
        "profile": "must-not-be-read",
        "events": [{"start_pts": 1.0, "end_pts": 2.0}],
    }
    with_private_labels["videos"][0]["raw_diagnostics"]["golden_labels"] = {
        "moments": ["must-not-be-read"],
        "rotation": 9.0,
    }

    assert analyze_diagnostic(with_private_labels) == baseline


def test_diagnostic_fingerprint_is_independent_of_video_order() -> None:
    first = _diagnostic()
    second_video = deepcopy(first["videos"][0])
    second_video["raw_diagnostics"]["source_evidence"]["source_video_hash"] = "sha256:source-b"
    first["videos"].append(second_video)
    reversed_order = {"videos": list(reversed(first["videos"]))}

    assert analyze_diagnostic(first) == analyze_diagnostic(reversed_order)
