import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PoseFrameCanvas from "./PoseFrameCanvas";
import { drawPoseOverlay } from "../utils/poseCanvas";

vi.mock("../utils/poseCanvas", () => ({
  drawPoseOverlay: vi.fn(),
}));

const drawPoseOverlayMock = vi.mocked(drawPoseOverlay);

const frame = { frame: "frame_0010.jpg", keypoints: [] };
const trackedFrame = {
  frame: "frame_0030.jpg",
  keypoints: [{ id: 11, name: "left_shoulder", x: 0.5, y: 0.4, z: 0, visibility: 0.92 }],
};
const connections = [[11, 12]];
const extendedConnections = [
  [11, 12],
  [23, 24],
];

function getImage() {
  return screen.getByRole("img", { name: "骨架姿态" }) as HTMLImageElement;
}

function markImageReady(image: HTMLImageElement, width = 854, height = 480) {
  Object.defineProperty(image, "complete", { configurable: true, writable: true, value: true });
  Object.defineProperty(image, "naturalWidth", { configurable: true, writable: true, value: width });
  Object.defineProperty(image, "naturalHeight", { configurable: true, writable: true, value: height });
}

function markImageLoading(image: HTMLImageElement) {
  Object.defineProperty(image, "complete", { configurable: true, writable: true, value: false });
}

describe("PoseFrameCanvas", () => {
  beforeEach(() => {
    drawPoseOverlayMock.mockClear();
  });

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

  it("draws the overlay with the decoded image size after the image loads", () => {
    const { container } = render(
      <PoseFrameCanvas frame={trackedFrame} frameUrl="/frame_0030.jpg" connections={connections} alt="骨架姿态" />,
    );
    markImageReady(getImage());

    fireEvent.load(getImage());

    expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);
    expect(drawPoseOverlayMock).toHaveBeenCalledWith(container.querySelector("canvas"), trackedFrame, connections, {
      mediaWidth: 854,
      mediaHeight: 480,
    });
  });

  it("repaints when the pose frame changes while the cached image URL stays the same", () => {
    const { container, rerender } = render(
      <PoseFrameCanvas frame={frame} frameUrl="/frame_0030.jpg" connections={connections} alt="骨架姿态" />,
    );
    markImageReady(getImage());
    fireEvent.load(getImage());
    expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);

    drawPoseOverlayMock.mockClear();
    rerender(
      <PoseFrameCanvas frame={trackedFrame} frameUrl="/frame_0030.jpg" connections={connections} alt="骨架姿态" />,
    );

    // No new load event fires for an already cached image: the prop change alone must repaint.
    expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);
    expect(drawPoseOverlayMock).toHaveBeenCalledWith(container.querySelector("canvas"), trackedFrame, connections, {
      mediaWidth: 854,
      mediaHeight: 480,
    });
  });

  it("repaints when only the connections change", () => {
    const { rerender } = render(
      <PoseFrameCanvas frame={trackedFrame} frameUrl="/frame_0030.jpg" connections={connections} alt="骨架姿态" />,
    );
    markImageReady(getImage());
    fireEvent.load(getImage());
    drawPoseOverlayMock.mockClear();

    rerender(
      <PoseFrameCanvas
        frame={trackedFrame}
        frameUrl="/frame_0030.jpg"
        connections={extendedConnections}
        alt="骨架姿态"
      />,
    );

    expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);
    expect(drawPoseOverlayMock.mock.calls[0][2]).toBe(extendedConnections);
  });

  it("draws an already cached image on mount without waiting for a load event", () => {
    const complete = vi.spyOn(HTMLImageElement.prototype, "complete", "get").mockReturnValue(true);
    const naturalWidth = vi.spyOn(HTMLImageElement.prototype, "naturalWidth", "get").mockReturnValue(854);
    const naturalHeight = vi.spyOn(HTMLImageElement.prototype, "naturalHeight", "get").mockReturnValue(480);
    try {
      render(
        <PoseFrameCanvas frame={trackedFrame} frameUrl="/frame_0030.jpg" connections={connections} alt="骨架姿态" />,
      );

      expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);
      expect(drawPoseOverlayMock).toHaveBeenCalledWith(expect.any(HTMLCanvasElement), trackedFrame, connections, {
        mediaWidth: 854,
        mediaHeight: 480,
      });
    } finally {
      complete.mockRestore();
      naturalWidth.mockRestore();
      naturalHeight.mockRestore();
    }
  });

  it("does not paint a newly requested image with the previous image dimensions", () => {
    const { rerender } = render(
      <PoseFrameCanvas frame={frame} frameUrl="/frame_0030.jpg" connections={connections} alt="骨架姿态" />,
    );
    markImageReady(getImage(), 854, 480);
    fireEvent.load(getImage());
    expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);

    drawPoseOverlayMock.mockClear();
    markImageLoading(getImage());
    rerender(
      <PoseFrameCanvas frame={trackedFrame} frameUrl="/frame_0031.jpg" connections={connections} alt="骨架姿态" />,
    );

    // The new URL has not decoded yet: painting now would use the stale 854x480 size.
    expect(drawPoseOverlayMock).not.toHaveBeenCalled();

    markImageReady(getImage(), 640, 360);
    fireEvent.load(getImage());

    expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);
    expect(drawPoseOverlayMock).toHaveBeenCalledWith(expect.any(HTMLCanvasElement), trackedFrame, connections, {
      mediaWidth: 640,
      mediaHeight: 360,
    });
  });

  it("keeps repainting on window resize with the current frame", () => {
    render(<PoseFrameCanvas frame={frame} frameUrl="/frame_0030.jpg" connections={connections} alt="骨架姿态" />);
    markImageReady(getImage());
    fireEvent.load(getImage());
    drawPoseOverlayMock.mockClear();

    fireEvent(window, new Event("resize"));

    expect(drawPoseOverlayMock).toHaveBeenCalledTimes(1);
    expect(drawPoseOverlayMock).toHaveBeenCalledWith(expect.any(HTMLCanvasElement), frame, connections, {
      mediaWidth: 854,
      mediaHeight: 480,
    });
  });

  it("keeps the unavailable state when the image fails to load", () => {
    render(<PoseFrameCanvas frame={trackedFrame} frameUrl="/missing.jpg" connections={connections} alt="骨架姿态" />);

    fireEvent.error(getImage());

    expect(screen.getByText("当前阶段没有可展示的画面")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(drawPoseOverlayMock).not.toHaveBeenCalled();
  });
});


it("discards old canvas pixels while a replacement image is loading or fails", () => {
  const {container, rerender} = render(<PoseFrameCanvas frame={trackedFrame} frameUrl="/first.jpg" connections={connections} alt="骨架姿态" />);
  markImageReady(getImage()); fireEvent.load(getImage());
  const oldCanvas = container.querySelector("canvas");
  markImageLoading(getImage());
  rerender(<PoseFrameCanvas frame={trackedFrame} frameUrl="/next.jpg" connections={connections} alt="骨架姿态" />);
  expect(oldCanvas?.isConnected).toBe(false);
  fireEvent.error(getImage());
  expect(container.querySelector("canvas")).toBeNull();
});
