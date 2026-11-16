import { createRef } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PoseSurface } from "./PoseSurface";
import { drawPoseOverlay } from "../utils/poseCanvas";
vi.mock("../utils/poseCanvas", async original => ({...await original<typeof import("../utils/poseCanvas")>(), drawPoseOverlay: vi.fn()}));
afterEach(() => {cleanup(); vi.clearAllMocks();});
it("uses a transparent overlay, decoded video dimensions and clears gaps/seeks without any sampled image", () => {
  const video = document.createElement("video");
  Object.defineProperties(video, {readyState: {get: () => 4}, videoWidth: {get: () => 406}, videoHeight: {get: () => 720}, seeking: {get: () => false}});
  video.currentTime = .125;
  const ref = {current: video};
  const point = {id: 11, name: "joint", x: .2, y: .3, z: 0, visibility: .9};
  const geometry = {schema_version: "pose-geometry.v1", coordinate_space: "sample_normalized", sample_width: 800, sample_height: 400, content_rect: {x:288,y:0,width:226,height:400}, source_width: 406, source_height:720, rotation_degrees:0,crop:"none",provenance:"saved_metadata_verified_frames"} as const;
  const pose = {geometry, frames: [0,.062,.125,1].map((_,i) => ({frame: `f${i}`, keypoints: [point]})), connections: [], frame_urls: {f2: "/static-sample.jpg"}, frame_timestamps: {f0: 0, f1: .062, f2: .125, f3: 1}};
  const {container} = render(<PoseSurface pose={pose} timestamp={.125} videoRef={ref} className="ice-media-player__overlay" />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("canvas")).toBeInTheDocument();
  expect(drawPoseOverlay).toHaveBeenCalledWith(expect.any(HTMLCanvasElement), pose.frames[2], [], {mediaWidth: 406, mediaHeight: 720, coordinateTarget: "video", geometry});
  expect(screen.getByText(/采样参考/)).toBeInTheDocument();
  video.currentTime = .6; fireEvent.timeUpdate(video);
  expect(container.querySelector("canvas")).toBeNull();
  expect(screen.getByText(/无匹配/)).toBeInTheDocument();
  video.currentTime = .125; fireEvent.seeked(video);
  expect(container.querySelector("canvas")).toBeInTheDocument();
  fireEvent.seeking(video);
  expect(container.querySelector("canvas")).toBeNull();
});

it("stops video overlay without geometry and retains the saved image reference", () => {
  const video=document.createElement("video");Object.defineProperties(video,{readyState:{get:()=>4},videoWidth:{get:()=>400},videoHeight:{get:()=>800},seeking:{get:()=>false}});video.currentTime=0;
  const pose={connections:[],frames:[{frame:"sample.jpg",keypoints:[]}],frame_urls:{"sample.jpg":"/saved.jpg"},frame_timestamps:{"sample.jpg":0}};
  const {container}=render(<PoseSurface pose={pose} timestamp={0} videoRef={{current:video}} />);
  expect(container.querySelector('canvas[aria-label="保存骨架叠加"]')).toBeNull();
  expect(screen.getByText(/保存几何不可用/)).toBeInTheDocument();
  expect(container.querySelector("img")).toHaveAttribute("src","/saved.jpg");
  expect(drawPoseOverlay).not.toHaveBeenCalled();
});
