import { readFileSync } from "node:fs";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PoseResponse } from "../api/client";
import { drawPoseOverlay, isDisplayFrame, validVideoGeometry } from "../utils/poseCanvas";
import { poseFrameIndexAtTime, poseFrameTimestamp } from "./poseTimeline";
import { PoseSurface } from "./PoseSurface";

// Optional integration fixture is the actual isolated SQLite/TestClient output.
// The offline delivery runner supplies it; ordinary unit runs explicitly skip it.
const fixture = process.env.SAVED_GEOMETRY_GET_FIXTURE;
const original = process.env.SAVED_GEOMETRY_ORIGINAL_FIXTURE;
const suite = fixture && original ? describe : describe.skip;
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it.each(["full_frame_yolo_relock_pending", "local_zoom_yolo_relock_pending", "relock_pending", "detector_relocked", "relocked", "continuity_rejected", "relock_rejected", "lost_reused", "input_unreliable"])("geometry cannot promote tracker state %s", state => {
  expect(isDisplayFrame({frame:"f",keypoints:[],tracking_state:"tracked",tracker_state:state})).toBe(false);
});
it("rejects explicitly invalid image binding even with high visibility", () => {
  expect(isDisplayFrame({frame:"f",keypoints:[],input_binding_valid:false})).toBe(false);
  expect(isDisplayFrame({frame:"f",keypoints:[],temporal:{binding:{},time_source:"index_derived"}})).toBe(false);
});

suite("actual saved GET geometry consumers (offline, no video decode)", () => {
  const load = (): PoseResponse => JSON.parse(readFileSync(fixture!, "utf8")).pose;
  function canvasContext() {
    return {setTransform:vi.fn(),clearRect:vi.fn(),beginPath:vi.fn(),arc:vi.fn(),fill:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn(),setLineDash:vi.fn(),fillText:vi.fn()};
  }
  function fakeVideo() {
    const video=document.createElement("video");
    Object.defineProperties(video,{readyState:{get:()=>4},videoWidth:{get:()=>400},videoHeight:{get:()=>800},seeking:{get:()=>false}});
    video.currentTime=.1;return video;
  }
  it("maps the saved marker to quarter width / three-quarter height and uses playback time", () => {
    const pose=load();const canvas=document.createElement("canvas");const ctx=canvasContext();
    Object.defineProperties(canvas,{clientWidth:{value:400},clientHeight:{value:800}});
    vi.spyOn(canvas,"getContext").mockReturnValue(ctx as never);
    expect(validVideoGeometry(pose.geometry,400,800)).toBe(true);
    drawPoseOverlay(canvas,pose.frames[1],pose.connections,{mediaWidth:400,mediaHeight:800,coordinateTarget:"video",geometry:pose.geometry});
    expect(ctx.arc.mock.calls[0][0]).toBeCloseTo(100,8);expect(ctx.arc.mock.calls[0][1]).toBeCloseTo(600,8);
    expect(poseFrameTimestamp(pose,pose.frames[1],1)).toBe(.1);
    expect(pose.frames[1].temporal?.analysis_timestamp).toBe(.025);
    expect(poseFrameIndexAtTime(pose,.5)).toBe(-1);
    expect(poseFrameIndexAtTime(pose,7.1)).toBe(-1);
    expect(poseFrameIndexAtTime(pose,-.01)).toBe(-1);
  });
  it("overlay readiness follows saved clocks and hides gaps, pending identity, and seeking", () => {
    const pose=load();const video=fakeVideo();
    vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue(canvasContext() as never);
    const {container}=render(<PoseSurface pose={pose} timestamp={.1} videoRef={{current:video}} />);
    const overlay=()=>container.querySelector('canvas[aria-label="保存骨架叠加"]');
    expect(overlay()).not.toBeNull();
    video.currentTime=.5;fireEvent.timeUpdate(video);expect(overlay()).toBeNull();
    video.currentTime=.9;fireEvent.timeUpdate(video);expect(overlay()).toBeNull();
    video.currentTime=.1;fireEvent.seeked(video);expect(overlay()).not.toBeNull();
    fireEvent.seeking(video);expect(overlay()).toBeNull();
    fireEvent.seeked(video);expect(overlay()).not.toBeNull();
  });
  it("original unknown SAR remains unavailable and retains a saved-image fallback", () => {
    const pose:PoseResponse=JSON.parse(readFileSync(original!,"utf8"));const video=fakeVideo();video.currentTime=2.8;
    vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue(canvasContext() as never);
    const {container}=render(<PoseSurface pose={pose} timestamp={2.8} videoRef={{current:video}} />);
    expect(pose.geometry).toBeNull();expect(pose.geometry_unavailable_reason).toBe("unsupported_or_unknown_saved_sar");
    expect(container.querySelector('canvas[aria-label="保存骨架叠加"]')).toBeNull();
    expect(screen.getByText(/保存采样图参考/)).toBeInTheDocument();
    expect(container.querySelector("img")?.getAttribute("src")).toContain("frame_0015.jpg");
    expect(pose.frames.filter(f=>f.keypoints.length)).toHaveLength(6);
  });
});
