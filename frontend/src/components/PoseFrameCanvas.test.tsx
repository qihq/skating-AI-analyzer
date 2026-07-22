import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PoseFrameCanvas from "./PoseFrameCanvas";

const frame = { frame: "frame_0010.jpg", keypoints: [] };

describe("PoseFrameCanvas", () => {
  it("shows an explicit unavailable state when the frame URL is missing", () => {
    render(<PoseFrameCanvas frame={frame} frameUrl={null} connections={[]} alt="起跳" />);

    expect(screen.getByText("当前阶段没有可展示的画面")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders an available source frame even when pose landmarks are unavailable", () => {
    render(<PoseFrameCanvas frame={null} frameUrl="/frame.jpg" connections={[]} alt="腾空" />);

    expect(screen.getByRole("img", { name: "腾空" })).toHaveClass("object-contain");
    expect(screen.queryByText("当前阶段没有可展示的画面")).not.toBeInTheDocument();
  });

  it("adds a canvas overlay when pose landmarks are available", () => {
    const { container } = render(<PoseFrameCanvas frame={frame} frameUrl="/frame.jpg" connections={[]} alt="落冰" />);

    expect(container.querySelector("canvas")).toBeInTheDocument();
  });
});
