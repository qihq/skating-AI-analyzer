import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PoseResponse } from "../api/client";
import { isDisplayFrame, drawPoseOverlay } from "../utils/poseCanvas";
import { poseFrameIndexAtTime, poseFrameTimestamp } from "./poseTimeline";
import { PoseSurface } from "./PoseSurface";

const directory = process.env.SEGMENT_GET_FIXTURES;
const suite = directory ? describe : describe.skip;
afterEach(() => {cleanup();vi.restoreAllMocks();});
const context = () => ({setTransform:vi.fn(),clearRect:vi.fn(),beginPath:vi.fn(),arc:vi.fn(),fill:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn(),setLineDash:vi.fn(),fillText:vi.fn()});
it("explicitly unconfirmed identity blocks optimistic legacy state", () => {
  expect(isDisplayFrame({frame:"f",keypoints:[],tracking_state:"tracked",tracker_state:"tracked",input_binding_valid:true,image_binding_valid:true,identity_status:"identity_unconfirmed"})).toBe(false);
});
suite("actual saved segment GET consumption, synthetic detector and landmarks", () => {
  const load = (kind="same"):PoseResponse => JSON.parse(readFileSync(`${directory}/chain-readback-${kind}.json`,"utf8")).pose;
  it("displays only the confirmed part of the new segment", () => {
    const pose=load();expect(pose.frames.map(isDisplayFrame)).toEqual([true,true,true,true,true,true,false,false,true,true,true,true]);
    const canvas=document.createElement("canvas");const ctx=context();
    vi.spyOn(canvas,"getContext").mockReturnValue(ctx as never);
    drawPoseOverlay(canvas,pose.frames[6],pose.connections,{mediaWidth:640,mediaHeight:240});expect(ctx.arc).not.toHaveBeenCalled();
    drawPoseOverlay(canvas,pose.frames[8],pose.connections,{mediaWidth:640,mediaHeight:240});expect(ctx.arc).toHaveBeenCalled();
    expect(pose.frames[8].temporal?.tracking_continuity_segment).toBe(1);
    expect((pose.frames[8].temporal?.segment_identity as any).support.map((s:any)=>s.observation_index)).toEqual([6,7,8]);
  });
  it.each(["ambiguous","replacement"])("does not draw rejected %s candidates", kind => {
    expect(load(kind).frames.slice(6).every(f=>!isDisplayFrame(f)&&f.keypoints.length===0)).toBe(true);
  });
  it("uses playback seconds without bridging gap or selecting a neighbour", () => {
    const pose=load();expect(poseFrameIndexAtTime(pose,.9)).toBe(-1);
    expect(poseFrameIndexAtTime(pose,1.4)).toBe(6);expect(isDisplayFrame(pose.frames[6])).toBe(false);
    expect(poseFrameIndexAtTime(pose,1.6)).toBe(8);
    expect(poseFrameTimestamp(pose,pose.frames[8],8)).toBeCloseTo(1.6);
    expect(pose.frames[8].temporal?.analysis_timestamp).toBeCloseTo(.4);
    expect(poseFrameIndexAtTime(pose,8.6)).toBe(-1);
  });
  it("keeps static image selection independent from unavailable video geometry and never seeks", () => {
    const pose=load();expect(pose.geometry).toBeNull();
    vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue(context() as never);
    const video=document.createElement("video");let time=1.6;const seek=vi.fn();
    Object.defineProperties(video,{currentTime:{get:()=>time,set:seek},readyState:{get:()=>4},videoWidth:{get:()=>640},videoHeight:{get:()=>240},seeking:{get:()=>false}});
    const view=render(<PoseSurface pose={pose} timestamp={time} videoRef={{current:video}}/>);
    expect(view.container.querySelector('canvas[aria-label="保存骨架叠加"]')).toBeNull();
    expect(view.container.querySelector("img")?.getAttribute("src")).toContain("frame_0009.jpg");
    time=1.4;fireEvent.timeUpdate(video);expect(view.container.querySelector("img")?.getAttribute("src")).toContain("frame_0007.jpg");
    time=.9;fireEvent.timeUpdate(video);expect(view.container.querySelector("img")).toBeNull();
    expect(seek).not.toHaveBeenCalled();
  });
});
