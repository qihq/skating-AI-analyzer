import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AnalysisDetail } from "../api/client";
import KeyframeEvidencePanel from "./KeyframeEvidencePanel";

const analysis = {
  id: "analysis-1",
  media_manifest: null,
  bio_data: { key_frames: { T: "frame_0010", A: "", L: "" } },
  video_temporal_diagnostics: { selected_semantic_frames: [{ frame_id: "frame_0010", phase_code: "T", timestamp: 2.4 }] },
} as unknown as AnalysisDetail;

describe("KeyframeEvidencePanel", () => {
  it("uses the shared player with normalized evidence markers", () => {
    render(<KeyframeEvidencePanel analysis={analysis} draftKeyframes={{}} onSyncFrames={() => undefined} />);

    expect(screen.getByLabelText("分析视频")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳到T" })).toBeInTheDocument();
  });
});
