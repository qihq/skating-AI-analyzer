import { describe, expect, it } from "vitest";

import type { AnalysisExperienceV2 } from "./contracts";
import { orderedProposalEvents, proposalDeepLink, proposalTimelineMarkers, rotationReviewDeepLink, selectProposalEvent } from "./eventProposals";

const experience: AnalysisExperienceV2 = {
  schemaVersion: "analysis-experience.v2", analysisId: "a/1", authority: "v2", pipelineMode: "v2", sourcePipelineFingerprint: "fp", diagnosticOnly: true, familyUsable: false,
  claims: [], reviewTasks: [], events: [
    { eventId: "later", profile: "unknown", startPts: 4, endPts: 5, status: "uncertain", observability: "partially_observable" },
    { eventId: "first", profile: "unknown", startPts: 1, endPts: 2, status: "uncertain", observability: "observable" },
  ],
};

describe("multi-event selectors", () => {
  it("orders by exact source PTS and selects deep-linked stable event IDs", () => {
    expect(orderedProposalEvents(experience).map((item) => item.eventId)).toEqual(["first", "later"]);
    expect(selectProposalEvent(experience, "later").event?.startPts).toBe(4);
    expect(selectProposalEvent(experience, "missing").eventId).toBe("first");
  });

  it("builds shared timeline markers and encoded links", () => {
    expect(proposalTimelineMarkers(experience)).toHaveLength(4);
    expect(proposalDeepLink(experience.analysisId, "event one")).toBe("/analysis/a%2F1?event=event%20one");
  });

  it("builds rotation review links only from an exact source PTS task", () => {
    expect(rotationReviewDeepLink("analysis 1", { eventId: "event/1", startPts: 1.234 })).toBe("/analysis/analysis%201?view=moments&event=event%2F1&t=1.234");
    expect(() => rotationReviewDeepLink("a1", { eventId: "e1", startPts: null })).toThrow(/exact/);
  });
});
