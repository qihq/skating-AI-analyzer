import { describe, expect, it } from "vitest";
import type { EventMomentSetV2, ExperienceEvent, KeyMomentV2, ProfileMomentKey } from "./contracts";
import { momentMarkers, orderedMoments, selectedMomentThumbnail } from "./momentSelectors";

function moment(semanticKey: ProfileMomentKey, status: KeyMomentV2["status"] = "confirmed", ptsSec: number | null = 1): KeyMomentV2 {
  return { semanticKey, kind: semanticKey.includes("interval") || semanticKey.startsWith("spin_") || semanticKey.startsWith("spiral_") ? "interval" : semanticKey.startsWith("step_") ? "representative" : "point", status, sourceFrameIndex: ptsSec == null ? null : Math.round(ptsSec * 60), ptsSec, endSourceFrameIndex: null, endPtsSec: null, definitionVersion: "v1", candidateEvidence: [], confidence: status === "unavailable" ? 0 : .8, warnings: status === "unavailable" ? ["absent"] : [], observability: status === "unavailable" ? "unobservable" : "observed", provenance: ["source_pts"], competingCandidates: [], reviewResolvable: false };
}

function set(profile: EventMomentSetV2["profile"], moments: KeyMomentV2[]): EventMomentSetV2 {
  const keys = moments.map((item) => item.semanticKey);
  return { schemaVersion: "event-moment-set.v1", eventId: "e", profile, definitionVersion: "v1", moments, expectedKeys: keys, requiredKeys: keys.slice(0, profile === "step" ? 2 : keys.length), presentKeys: keys.filter((key) => moments.find((item) => item.semanticKey === key)?.status !== "unavailable"), missingKeys: keys.filter((key) => moments.find((item) => item.semanticKey === key)?.status === "unavailable"), completeness: "complete", warnings: [], sourceTimelineFingerprint: "timeline", stateMachineFingerprint: "state", semanticLabelsConsumed: false, revision: 1 };
}

describe("profile moment selectors", () => {
  it.each([
    ["jump", ["takeoff", "apex", "landing"]],
    ["spin", ["spin_entry", "spin_main", "spin_exit"]],
    ["spiral", ["spiral_entry", "spiral_hold", "spiral_exit"]],
    ["step", ["step_sequence_interval", "step_representative_1", "step_representative_2", "step_representative_3"]],
  ] as const)("is exhaustive for %s", (profile, keys) => {
    const event = { eventId: "e", profile, state: "confirmed", startPts: 0, endPts: 2, status: "confirmed", observability: "observable", moments: set(profile, keys.map((key, index) => moment(key, "confirmed", index + 1))) } as ExperienceEvent;
    expect(orderedMoments(event).map((item) => item.semanticKey)).toEqual(keys);
  });

  it("does not create timeline markers or thumbnails for unavailable moments", () => {
    const moments = set("jump", [moment("takeoff", "confirmed", 1), moment("apex", "confirmed", 2), moment("landing", "unavailable", null)]);
    expect(momentMarkers(moments).map((item) => item.phase)).toEqual(["takeoff", "apex"]);
    expect(selectedMomentThumbnail(moments, "landing")).toBeNull();
    expect(selectedMomentThumbnail(moments)?.semanticKey).toBe("apex");
  });
});
