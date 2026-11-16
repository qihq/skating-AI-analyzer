import { describe, expect, it } from "vitest";
import { poseFrameIndexAtTime } from "./poseTimeline";
import type { PoseResponse } from "../api/client";
function pose(times: (number | undefined)[]): PoseResponse {
  return { frames: times.map((_, i) => ({frame: `f${i}.jpg`, keypoints: []})), frame_urls: {}, connections: [],
    frame_timestamps: Object.fromEntries(times.flatMap((t, i) => t === undefined ? [] : [[`f${i}.jpg`, t]])) };
}
describe("bounded saved pose matching", () => {
  it("matches exact times, zero and close samples without extrapolation", () => {
    const data = pose([0, .062, .125, .187, 1]);
    expect(poseFrameIndexAtTime(data, 0)).toBe(0);
    expect(poseFrameIndexAtTime(data, .125)).toBe(2);
    expect(poseFrameIndexAtTime(data, .14)).toBe(2);
    expect(poseFrameIndexAtTime(data, 1)).toBe(4);
    expect(poseFrameIndexAtTime(data, -.001)).toBe(-1);
    expect(poseFrameIndexAtTime(data, 1.001)).toBe(-1);
  });
  it("never fills sparse gaps with the nearest pose or uses effective_fps to manufacture times", () => {
    const data = {...pose([0, .062, .125, .9, 1.8]), effective_fps: 100};
    expect(poseFrameIndexAtTime(data, .5)).toBe(-1);
    expect(poseFrameIndexAtTime(data, 1.4)).toBe(-1);
    expect(poseFrameIndexAtTime(pose([0, 1, 2]), 1.4)).toBe(-1);
  });
  it.each([[undefined, undefined], [0, undefined, 1], [0, .2, .1], [0, 0], [-1, 0], [0, Infinity], [0, NaN]])("refuses missing/invalid/unordered times: %j", (...times) => {
    expect(poseFrameIndexAtTime(pose(times), 0)).toBe(-1);
  });
  it("refuses nonfinite playhead times and only matches a single sample exactly", () => {
    expect(poseFrameIndexAtTime(pose([1]), 1)).toBe(0);
    for (const t of [0, 1.01, NaN, Infinity]) expect(poseFrameIndexAtTime(pose([1]), t)).toBe(-1);
  });
});
