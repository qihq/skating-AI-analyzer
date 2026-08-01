import { describe, expect, it } from "vitest";
import { displayToSource, sourceBoxToDisplay, sourceToDisplay, sourceTimelineFrameAt, sourceTimelineNextFrame } from "./timebase";
import type { SourceTimeline } from "./contracts";

const timeline: SourceTimeline = {
  schemaVersion: "source-timeline.v1", sourceVideoHash: "sha256:source", durationSec: 1, width: 1920, height: 1080,
  rotationDegrees: 90, timestampStatus: "exact", decodeGaps: [], ptsDiscontinuities: [], fingerprint: "fp",
  frames: [
    { sourceFrameIndex: 0, ptsSec: 0, durationSec: .04, status: "available", gapBeforeSec: 0 },
    { sourceFrameIndex: 1, ptsSec: .04, durationSec: .06, status: "available", gapBeforeSec: 0 },
    { sourceFrameIndex: 2, ptsSec: .10, durationSec: .04, status: "gap_after_previous", gapBeforeSec: .02 },
  ],
};

describe("canonical V2 timebase selectors", () => {
  it("round-trips normalized coordinates for every rotation", () => {
    for (const rotation of [0, 90, 180, 270] as const) {
      const source = { x: .173, y: .827 };
      const restored = displayToSource(sourceToDisplay(source, rotation), rotation);
      expect(restored.x).toBeCloseTo(source.x, 12);
      expect(restored.y).toBeCloseTo(source.y, 12);
    }
  });

  it("rotates boxes and resolves seek/step to one source identity", () => {
    expect(sourceBoxToDisplay({ left: .1, top: .2, right: .4, bottom: .8 }, 90)).toMatchObject({ right: .8, top: .1, bottom: .4 });
    expect(sourceBoxToDisplay({ left: .1, top: .2, right: .4, bottom: .8 }, 90).left).toBeCloseTo(.2, 12);
    expect(sourceTimelineFrameAt(timeline, .091)?.sourceFrameIndex).toBe(2);
    expect(sourceTimelineNextFrame(timeline, 1, 1)?.ptsSec).toBe(.10);
  });
});
