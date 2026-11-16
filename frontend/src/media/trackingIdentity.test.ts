import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PoseResponse } from "../api/client";
import { drawPoseOverlay, isDisplayFrame } from "../utils/poseCanvas";
import { poseFrameIndexAtTime } from "./poseTimeline";

const directory = process.env.IDENTITY_GET_FIXTURES;
const suite = directory ? describe : describe.skip;
afterEach(() => vi.restoreAllMocks());
suite("spatial identity through actual saved GET (synthetic detector/landmarks)", () => {
  const load = (kind: string): PoseResponse => JSON.parse(readFileSync(`${directory}/identity-${kind}.json`, "utf8")).readback.pose;
  const positives = ["same", "translation", "scale", "brightness", "crop", "combined"];
  it.each([...positives,"vertical_swap","diagonal_swap","alternating","occluded","late_swap","support_drift","reference_layout_conflict","scrambled"])("draws only supported frames: %s", kind => {
    const pose=load(kind);
    const canvas=document.createElement("canvas");
    const ctx={setTransform:vi.fn(),clearRect:vi.fn(),beginPath:vi.fn(),arc:vi.fn(),fill:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn(),setLineDash:vi.fn(),fillText:vi.fn()};
    vi.spyOn(canvas,"getContext").mockReturnValue(ctx as never);
    const end=positives.includes(kind)?12:kind==="late_swap"?10:6;
    pose.frames.forEach((frame,i)=>{
      const expected=i<6 || (i>=8 && i<end);
      expect(isDisplayFrame(frame)).toBe(expected);
      ctx.arc.mockClear();
      drawPoseOverlay(canvas,frame,pose.connections,{mediaWidth:640,mediaHeight:240});
      expect(ctx.arc.mock.calls.length>0).toBe(expected);
      if(i>=6){
        const identity=frame.temporal?.segment_identity as {evidence_version:string;reason:string};
        expect(["torso_spatial_v2","torso_spatial_aligned_v3","torso_reliable_colour_v4"]).toContain(identity.evidence_version);
        expect(identity.reason).toBeTruthy();
      }
    });
    expect(poseFrameIndexAtTime(pose,.9)).toBe(-1);
    expect(pose.geometry).toBeNull(); // No invented video geometry from identity.
  });
});
