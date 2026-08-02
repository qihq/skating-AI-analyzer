import { describe, expect, it } from "vitest";
import { DetectionProposalDiagnostics, selectDetectionOverlays } from "./contracts";

describe("detection diagnostics selectors", () => {
  it("keeps crossing candidates and anchor suggestions separate", () => {
    const payload = { schema_version: "detection-proposal-diagnostics.v1", status: "complete", provider: "v2", detector: "yolo", tracker: "bytetrack", model_source: "default", model_hash: null, dependency_ready: true, candidates: [{ candidate_id: "a", source_frame_index: 4 }, { candidate_id: "b", source_frame_index: 4 }], short_tracks: [{ short_track_id: "ta", source_frame_indices: [3, 4] }, { short_track_id: "tb", source_frame_indices: [4, 5] }], camera: [], anchor_suggestions: ["a"], candidate_recall: null, diagnostics_fingerprint: "sha256:x", invalidation_scope: "shadow_diagnostics_only", ds918_compatible: true, candidate_recall_counts: {} } as DetectionProposalDiagnostics;
    expect(selectDetectionOverlays(payload, 4)).toEqual({ candidates: payload.candidates, shortTracks: payload.short_tracks, anchorSuggestions: ["a"] });
  });
});
