import { describe, expect, it } from "vitest";
import type { AnalysisDetail } from "../api/client";
import { analysisMediaMarkers } from "./analysisMarkers";

const analysis = {
  bio_data: { key_frames: { T: "frame_0010", A: "frame_0020", L: "frame_0030" } },
  video_temporal_diagnostics: {
    selected_semantic_frames: [
      { frame_id: "frame_0010", phase_code: "T", timestamp: 2.4 },
      { frame_id: "frame_0040", phase_code: "landing", timestamp: 6.2 },
    ],
    partial_semantic_frames: [{ frame_id: "frame_0050", phase_code: "landing", timestamp: 6.9 }],
  },
  pose_data: { frame_timestamps: { frame_0010: 2.4, frame_0020: 4.8, frame_0030: 6.1 }, frames: [] },
} as unknown as AnalysisDetail;

describe("analysisMediaMarkers", () => {
  it("preserves T/A/L and conflicting semantic candidates", () => {
    const markers = analysisMediaMarkers(analysis);

    expect(markers.map((marker) => marker.label)).toEqual(expect.arrayContaining(["T", "A", "L", "landing", "候选 landing"]));
    expect(markers.map((marker) => marker.timestamp)).toEqual([...markers.map((marker) => marker.timestamp)].sort((left, right) => left - right));
  });
});
