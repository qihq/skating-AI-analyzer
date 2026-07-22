import { describe, expect, it } from "vitest";
import type { AnalysisDetail } from "../api/client";
import { buildCurrentKeyframeEvidenceItems } from "./keyframeEvidence";

function analysis(profile: string): AnalysisDetail {
  return { id: "analysis-1", analysis_profile: profile, bio_data: { key_frames: {} } } as AnalysisDetail;
}

describe("profile-specific keyframe evidence", () => {
  it("uses the resolved phase contracts for non-jump profiles", () => {
    expect(buildCurrentKeyframeEvidenceItems(analysis("spin")).map((item) => item.label)).toEqual(["入转", "主转", "出转"]);
    expect(buildCurrentKeyframeEvidenceItems(analysis("spiral")).map((item) => item.label)).toEqual(["姿态保持"]);
    expect(buildCurrentKeyframeEvidenceItems(analysis("step")).map((item) => item.label)).toEqual(["步法区间"]);
  });
});
