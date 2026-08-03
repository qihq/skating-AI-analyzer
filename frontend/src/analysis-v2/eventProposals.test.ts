import { describe, expect, it } from "vitest";

import type { AnalysisExperienceV2 } from "./contracts";
import { orderedProposalEvents, proposalDeepLink, proposalTimelineMarkers, selectProposalEvent } from "./eventProposals";

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
});
