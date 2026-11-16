import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IceMediaPlayer } from "./IceMediaPlayer";

describe("IceMediaPlayer", () => {
  it("composes the shared surface and controls", () => {
    render(<IceMediaPlayer fallbackSrc="source.mp4" markers={[{ id: "T", label: "T", timestamp: 1 }]} />);
    expect(screen.getByLabelText("分析视频")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳到T" })).toBeInTheDocument();
  });
});

afterEach(() => {cleanup(); vi.restoreAllMocks();});
it("binds the actual video clock on initial overlay mount and keeps the video through toggles", () => {
  vi.spyOn(HTMLMediaElement.prototype, "readyState", "get").mockReturnValue(4);
  vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(406);
  vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(720);
  const pose = {geometry: {schema_version: "pose-geometry.v1", coordinate_space: "sample_normalized", sample_width:406,sample_height:720,content_rect:{x:0,y:0,width:406,height:720},source_width:406,source_height:720,rotation_degrees:0,crop:"none",provenance:"saved_metadata_verified_frames"} as const, frames: [{frame: "sample", keypoints: []}], frame_urls: {}, frame_timestamps: {sample: 0}, connections: []};
  const {container, rerender} = render(<IceMediaPlayer fallbackSrc="source.mp4" pose={pose} mode="overlay" />);
  const video = container.querySelector("video");
  expect(screen.getByText(/此采样无可用关键点/)).toBeInTheDocument();
  rerender(<IceMediaPlayer fallbackSrc="source.mp4" pose={pose} mode="video" />);
  expect(container.querySelector("video")).toBe(video);
  rerender(<IceMediaPlayer fallbackSrc="source.mp4" pose={pose} mode="overlay" />);
  expect(container.querySelector("video")).toBe(video);
  expect(container.querySelector("img")).toBeNull();
});
