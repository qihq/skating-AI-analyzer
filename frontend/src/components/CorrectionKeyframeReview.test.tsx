import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { KeyframeEvidenceItem } from "../utils/keyframeEvidence";
import CorrectionKeyframeReview from "./CorrectionKeyframeReview";

const items = [
  { key: "T", label: "起跳", value: "frame_0010", frameId: "frame_0010", imageUrl: null, timestamp: 2.4, confidence: null, source: "Video AI" },
  { key: "A", label: "腾空", value: "frame_0020", frameId: "frame_0020", imageUrl: null, timestamp: 4.8, confidence: null, source: "Video AI" },
  { key: "L", label: "落冰", value: "", frameId: null, imageUrl: null, timestamp: null, confidence: null, source: "Video AI" },
] as KeyframeEvidenceItem[];

describe("CorrectionKeyframeReview", () => {
  it("opens the review player at the selected TAL timestamp", () => {
    render(<CorrectionKeyframeReview analysisId="analysis-1" items={items} />);

    fireEvent.click(screen.getByRole("button", { name: "定位 T 起跳 2.400s" }));
    const video = screen.getByTestId("correction-review-video") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", { value: 0, writable: true });
    fireEvent.loadedMetadata(video);

    expect(video.currentTime).toBe(2.4);
    expect(screen.getByText("正在 Review：T · 起跳")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "TAL 视频 Review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "定位 L 落冰 --" })).toBeDisabled();
  });
});
