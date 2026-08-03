import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PoseViewer from "./PoseViewer";
import type { PoseResponse } from "../api/client";

function pose(overrides: Partial<PoseResponse> = {}): PoseResponse {
  return {
    connections: [],
    frames: [{
      frame: "frame_0001.jpg",
      keypoints: [],
      source_pts_sec: 1.234,
      identity_state: "confirmed",
      pose_provenance: "measured",
    }],
    frame_urls: {},
    ...overrides,
  };
}

describe("PoseViewer provenance surface", () => {
  it("renders a text legend, selected event, source PTS, and provenance", () => {
    render(<PoseViewer pose={pose()} selectedEventId="event-1" selectedEventLabel="跳跃" />);

    expect(screen.getByLabelText("姿态证据图例")).toBeInTheDocument();
    expect(screen.getByText(/事件/)).toHaveTextContent("跳跃");
    expect(screen.getByText("PTS 1.234s")).toBeInTheDocument();
    expect(screen.getByText("pose: measured")).toBeInTheDocument();
  });

  it("exposes an identity warning and keeps the viewer usable without a skeleton", () => {
    render(<PoseViewer pose={pose({ frames: [{ frame: "frame_0001.jpg", keypoints: [], identity_state: "lost", pose_provenance: "identity-blocked", source_pts_sec: 2 }] })} />);

    expect(screen.getByText(/骨架已隐藏/)).toBeInTheDocument();
    expect(screen.getByText("pose: identity-blocked")).toBeInTheDocument();
  });

  it("shows an explicit empty-state message when no frames are available", () => {
    render(<PoseViewer pose={pose({ frames: [] })} />);
    expect(screen.getByText(/还没有可展示的骨骼姿态数据/)).toBeInTheDocument();
  });
});
