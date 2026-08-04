import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AnalysisDetail, PoseResponse } from "../api/client";
import ActionPhaseStrip from "./ActionPhaseStrip";
import type { ExperienceEvent } from "../analysis-v2/contracts";

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

  it("renders profile-specific V2 phases and never synthesizes unavailable markers", () => {
    const spin = {
      eventId: "event-spin", profile: "spin", state: "confirmed", startPts: 1, endPts: 4, status: "confirmed", observability: "observable",
      moments: {
        schemaVersion: "event-moment-set.v1", eventId: "event-spin", profile: "spin", definitionVersion: "spin.v1", expectedKeys: ["spin_entry", "spin_main", "spin_exit"], requiredKeys: ["spin_entry", "spin_main", "spin_exit"], presentKeys: ["spin_entry", "spin_main"], missingKeys: ["spin_exit"], completeness: "incomplete", warnings: [], sourceTimelineFingerprint: "timeline", stateMachineFingerprint: "state", semanticLabelsConsumed: false, revision: 1,
        moments: [
          { semanticKey: "spin_entry", kind: "interval", status: "confirmed", sourceFrameIndex: 60, ptsSec: 1, endSourceFrameIndex: 80, endPtsSec: 1.33, definitionVersion: "spin.v1", candidateEvidence: [], confidence: .8, warnings: [], observability: "observed", provenance: ["source_pts"], competingCandidates: [], reviewResolvable: false },
          { semanticKey: "spin_main", kind: "interval", status: "confirmed", sourceFrameIndex: 81, ptsSec: 1.35, endSourceFrameIndex: 150, endPtsSec: 2.5, definitionVersion: "spin.v1", candidateEvidence: [], confidence: .9, warnings: [], observability: "observed", provenance: ["source_pts"], competingCandidates: [], reviewResolvable: false },
          { semanticKey: "spin_exit", kind: "interval", status: "unavailable", sourceFrameIndex: null, ptsSec: null, endSourceFrameIndex: null, endPtsSec: null, definitionVersion: "spin.v1", candidateEvidence: [], confidence: 0, warnings: ["absent"], observability: "unobservable", provenance: ["refusal"], competingCandidates: [], reviewResolvable: false },
        ],
      },
    } as ExperienceEvent;
    render(<ActionPhaseStrip analysisId="analysis-1" event={spin} pose={null} showVideo={false} />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((item) => item.textContent)).toEqual(["入转", "主转", "出转"]);
    expect(screen.getByText(/不可用：absent/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /查看出转 不可用/ })).toBeDisabled();
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
