import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AnalysisDetail, PoseResponse } from "../api/client";
import ActionPhaseStrip from "./ActionPhaseStrip";

const pose: PoseResponse = {
  connections: [],
  frames: [{ frame: "frame_0010.jpg", keypoints: [] }],
  frame_urls: { "frame_0010.jpg": "/frame.jpg" },
  frame_timestamps: { frame_0010: 2.4 },
};

const jump = {
  id: "analysis-1",
  analysis_profile: "jump",
  bio_data: { key_frames: { T: "frame_0010", A: "", L: "" } },
  video_temporal_diagnostics: { selected_semantic_frames: [{ frame_id: "frame_0010", phase_code: "T", timestamp: 2.4 }] },
} as unknown as AnalysisDetail;

describe("ActionPhaseStrip", () => {
  it("renders T/A/L in order and preserves missing phases", () => {
    render(<ActionPhaseStrip analysis={jump} pose={pose} showVideo={false} />);

    expect(screen.getAllByRole("heading", { level: 3 }).map((item) => item.textContent)).toEqual(["起跳", "腾空", "落冰"]);
    expect(screen.getAllByText("当前阶段没有可展示的画面")).toHaveLength(2);
    expect(screen.queryByText("准备")).not.toBeInTheDocument();
  });

  it("seeks the bundled video to the stored timestamp", () => {
    render(<ActionPhaseStrip analysis={jump} pose={pose} showVideo />);
    const video = screen.getByLabelText("分析视频") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", { value: 0, writable: true });
    fireEvent.click(screen.getByRole("button", { name: "查看起跳 2.400s" }));

    expect(video.currentTime).toBe(2.4);
  });

  it("only seeks after the user finishes dragging the progress slider", () => {
    render(<ActionPhaseStrip analysis={jump} pose={pose} showVideo />);
    const video = screen.getByLabelText("分析视频") as HTMLVideoElement;
    const slider = screen.getByRole("slider", { name: /播放进度/ });
    Object.defineProperty(video, "duration", { value: 12, configurable: true });
    Object.defineProperty(video, "currentTime", { value: 0, writable: true });
    fireEvent.loadedMetadata(video);

    fireEvent.pointerDown(slider);
    fireEvent.change(slider, { target: { value: "7.5" } });
    expect(video.currentTime).toBe(0);

    fireEvent.pointerUp(slider, { currentTarget: { value: "7.5" } });
    expect(video.currentTime).toBe(7.5);
  });
});
