import { describe, expect, it } from "vitest";
import type { AnalysisExperienceV2, EventMomentSetV2, ExperienceEvent, KeyMomentV2, ProfileMomentKey } from "./contracts";
import { comparisonMomentChips, presentComparison } from "./presenter";

function moment(key: ProfileMomentKey, ptsSec: number, definitionVersion = "moments.v1"): KeyMomentV2 {
  return { semanticKey: key, kind: "point", status: "confirmed", sourceFrameIndex: Math.round(ptsSec * 60), ptsSec, endSourceFrameIndex: null, endPtsSec: null, definitionVersion, candidateEvidence: [], confidence: 0.9, warnings: [], observability: "observed", provenance: ["source_pts"], competingCandidates: [], reviewResolvable: false };
}

function moments(eventId: string, points: Array<[ProfileMomentKey, number]>, definitionVersion = "moments.v1"): EventMomentSetV2 {
  const values = points.map(([key, pts]) => moment(key, pts, definitionVersion));
  return { schemaVersion: "event-moment-set.v1", eventId, profile: "jump", definitionVersion, moments: values, expectedKeys: values.map((item) => item.semanticKey), requiredKeys: values.map((item) => item.semanticKey), presentKeys: values.map((item) => item.semanticKey), missingKeys: [], completeness: "complete", warnings: [], sourceTimelineFingerprint: "timeline", stateMachineFingerprint: "state", semanticLabelsConsumed: false, revision: 1 };
}

function experience(id: string, authority: "v2" | "legacy", event: ExperienceEvent): AnalysisExperienceV2 {
  return { schemaVersion: "analysis-experience.v2", analysisId: id, authority, pipelineMode: authority, sourcePipelineFingerprint: `${authority}:pipeline`, diagnosticOnly: false, familyUsable: true, events: [event], claims: [], reviewTasks: [], sourceTimeline: null };
}

function event(eventId: string, eventMoments: EventMomentSetV2): ExperienceEvent {
  return { eventId, profile: "jump", state: "confirmed", startPts: 0, endPts: 5, status: "confirmed", observability: "observable", moments: eventMoments };
}

describe("comparison authority moments", () => {
  it("projects chips from matched experience moments", () => {
    const left = experience("left", "v2", event("e-left", moments("e-left", [["takeoff", 1.1], ["apex", 1.7], ["landing", 2.2]])));
    const right = experience("right", "v2", event("e-right", moments("e-right", [["takeoff", 3.1], ["apex", 3.8], ["landing", 4.2]])));
    expect(comparisonMomentChips(left, right)).toEqual([
      expect.objectContaining({ key: "takeoff", beforePtsSec: 1.1, afterPtsSec: 3.1 }),
      expect.objectContaining({ key: "apex", beforePtsSec: 1.7, afterPtsSec: 3.8 }),
      expect.objectContaining({ key: "landing", beforePtsSec: 2.2, afterPtsSec: 4.2 }),
    ]);
    expect(presentComparison(left, right).momentChips).toHaveLength(3);
  });

  it("suppresses chips for authority or definition conflicts", () => {
    const left = experience("left", "v2", event("e-left", moments("e-left", [["takeoff", 1]])));
    const rightLegacy = experience("right", "legacy", event("e-right", moments("e-right", [["takeoff", 3]])));
    expect(comparisonMomentChips(left, rightLegacy)).toEqual([]);
    const rightDefinition = experience("right-v2", "v2", event("e-right", moments("e-right", [["takeoff", 3]], "moments.v2")));
    expect(comparisonMomentChips(left, rightDefinition)).toEqual([]);
  });
});
