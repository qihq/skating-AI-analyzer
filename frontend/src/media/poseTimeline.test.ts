import { describe, expect, it } from "vitest";
import { poseFrameIndexAtTime } from "./poseTimeline";

describe("poseFrameIndexAtTime", () => {
  it("uses timestamps and returns the nearest pose frame", () => {
    const pose = { frames: [{ frame: "frame_1.jpg", keypoints: [] }, { frame: "frame_2.jpg", keypoints: [] }, { frame: "frame_3.jpg", keypoints: [] }], frame_urls: {}, frame_timestamps: { "frame_1.jpg": 0, "frame_2.jpg": 1, "frame_3.jpg": 2 }, connections: [] };
    expect(poseFrameIndexAtTime(pose, 1.4)).toBe(1);
    expect(poseFrameIndexAtTime(pose, 1.8)).toBe(2);
  });
});
