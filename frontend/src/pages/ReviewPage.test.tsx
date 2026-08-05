import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppModeProvider, useAppMode } from "../components/AppModeContext";
import { uploadAnalysis as uploadAnalysisMock } from "../api/client";
import type { Skater, SkillNode, TrainingSessionRecord } from "../api/client";
import { fetchAnalysisExperienceV2Diagnostic, fetchEventProposals } from "../analysis-v2/api";
import ReviewPage from "./ReviewPage";

vi.mock("../components/AppModeContext", () => ({
  AppModeProvider: ({ children }: { children: ReactNode }) => children,
  useAppMode: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchSkaters: vi.fn(),
  fetchSkaterSkills: vi.fn(),
  fetchTrainingSessions: vi.fn(),
  fetchAnalysis: vi.fn(),
  createTrainingSession: vi.fn(),
  uploadAnalysis: vi.fn(),
  fetchHasPin: vi.fn().mockResolvedValue({ has_pin: false, pin_length: 4 }),
  verifyPin: vi.fn(),
  createMonthlyChapterFacts: vi.fn(),
  fetchMonthlyChapters: vi.fn(),
  generateMonthlyChapter: vi.fn(),
  patchMonthlyChapter: vi.fn(),
  publishMonthlyChapter: vi.fn(),
}));

vi.mock("../analysis-v2/api", () => ({
  fetchAnalysisExperienceV2Diagnostic: vi.fn(),
  fetchEventProposals: vi.fn(),
  mutateEventProposals: vi.fn(),
}));

const skaters = [{ id: "skater-1", name: "tantan", display_name: "坦坦", is_default: true }] as Skater[];
const skills: SkillNode[] = [];
const sessions: TrainingSessionRecord[] = [];

describe("ReviewPage highlight quote", () => {
  beforeEach(async () => {
    vi.mocked(useAppMode).mockReturnValue({ isParentMode: false, parentPin: null, childView: "tantan", setChildView: vi.fn() } as never);
    const client = await import("../api/client");
    vi.mocked(client.fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(client.fetchSkaterSkills).mockResolvedValue(skills);
    vi.mocked(client.fetchTrainingSessions).mockResolvedValue(sessions);
    vi.mocked(client.uploadAnalysis).mockResolvedValue({ id: "analysis-1", status: "pending" } as never);
    vi.mocked(client.uploadAnalysis).mockClear();
    vi.mocked(fetchEventProposals).mockReset();
    vi.mocked(fetchAnalysisExperienceV2Diagnostic).mockReset();
  });

  it("appends highlight_quote and quote_speaker=skater to FormData on submit", async () => {
    render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    await screen.findByText("开始诊断");

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["x"], "source.mp4", { type: "video/mp4" })] },
    });

    const quoteTextarea = screen.getByPlaceholderText("比如：我今天敢往后滑了。") as HTMLTextAreaElement;
    fireEvent.change(quoteTextarea, { target: { value: "我今天敢往后滑了" } });

    const speakerSelect = screen.getByRole("combobox", { name: "金句说话人" }) as HTMLSelectElement;
    fireEvent.change(speakerSelect, { target: { value: "skater" } });

    fireEvent.click(screen.getByRole("button", { name: "开始诊断" }));

    await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalled());

    const captured = vi.mocked(uploadAnalysisMock).mock.calls[0][0] as FormData;
    expect(captured.get("highlight_quote")).toBe("我今天敢往后滑了");
    expect(captured.get("quote_speaker")).toBe("skater");
  });

  it("omits quote fields when the quote is empty", async () => {
    render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    await screen.findByText("开始诊断");

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["x"], "source.mp4", { type: "video/mp4" })] },
    });

    fireEvent.click(screen.getByRole("button", { name: "开始诊断" }));

    await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalled());

    const captured = vi.mocked(uploadAnalysisMock).mock.calls[0][0] as FormData;
    expect(captured.get("highlight_quote")).toBeNull();
    expect(captured.get("quote_speaker")).toBeNull();
  });

  it("选择视频后即显示可选时间区间，即使无法读取时长", async () => {
    render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    await screen.findByText("开始诊断");
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["x"], "source.mp4", { type: "video/mp4" })] },
    });

    expect(await screen.findByText("AI 输入片段（可选）")).toBeInTheDocument();
  });

  it("shows ambiguous rotation definition and exact PTS in parent review", async () => {
    vi.mocked(useAppMode).mockReturnValue({ isParentMode: true, parentPin: "1234", childView: "tantan", setChildView: vi.fn() } as never);
    vi.mocked(fetchEventProposals).mockResolvedValue({
      schema_version: "event-proposal-collection.v1",
      source_video_hash: "source",
      source_duration_sec: 3,
      pipeline_fingerprint: "pipeline",
      proposals: [{ event_id: "event-1", source_video_hash: "source", start_pts: 1, end_pts: 2, anchor_start_frame: 30, anchor_end_frame: 60, candidate_profile_scores: { jump: .8 }, proposed_profile: "unknown", status: "pending_confirmation", tracking_coverage: .9, pose_coverage: .8, observability: "partially_observable", evidence_sources: ["source_pts"], provenance_fingerprint: "proposal", revision: 1, parent_event_ids: [], superseded_event_ids: [] }],
      diagnostic_only: true,
      classifier_labels_consumed: false,
      revision: 1,
    });
    vi.mocked(fetchAnalysisExperienceV2Diagnostic).mockResolvedValue({
      schemaVersion: "analysis-experience.v2",
      analysisId: "analysis-1",
      authority: "v2",
      pipelineMode: "v2",
      sourcePipelineFingerprint: "pipeline",
      diagnosticOnly: true,
      familyUsable: false,
      claims: [],
      events: [{ eventId: "event-1", profile: "jump", subtype: "axel", state: "ambiguous", startPts: 1, endPts: 2, status: "uncertain", observability: "partially_observable" }],
      reviewTasks: [{ taskId: "rotation:event-1", authority: "v2", kind: "confirm_rotation_estimate", eventId: "event-1", startPts: 1.234, endPts: 1.567, definitionVersion: "airborne-body-rotation.source-pts.v1", convention: "airborne_body_rotation" }],
    });

    render(
      <MemoryRouter initialEntries={["/review?proposal_analysis_id=analysis-1"]}>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/标签定义：空中身体转体/)).toHaveTextContent("PTS 1.234–1.567");
    expect(screen.getByRole("link", { name: "打开精确时间复核" })).toHaveAttribute("href", "/analysis/analysis-1?view=moments&event=event-1&t=1.234");
  });
});
