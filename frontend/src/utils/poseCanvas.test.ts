import { describe, expect, it } from "vitest";
import { computeContainRect } from "./poseCanvas";

describe("computeContainRect", () => {
  it("letterboxes portrait media without stretching it", () => {
    expect(computeContainRect(320, 180, 90, 160)).toEqual({
      x: 109.375,
      y: 0,
      width: 101.25,
      height: 180,
    });
  });

  it("pillarboxes wide media inside a square", () => {
    expect(computeContainRect(200, 200, 400, 100)).toEqual({
      x: 0,
      y: 75,
      width: 200,
      height: 50,
    });
  });
});
