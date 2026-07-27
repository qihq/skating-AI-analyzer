import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppModeProvider } from "../components/AppModeContext";
import { uploadAnalysis as uploadAnalysisMock } from "../api/client";
import type { Skater, SkillNode, TrainingSessionRecord } from "../api/client";
import ReviewPage from "./ReviewPage";

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

const skaters = [{ id: "skater-1", name: "tantan", display_name: "坦坦", is_default: true }] as Skater[];
const skills: SkillNode[] = [];
const sessions: TrainingSessionRecord[] = [];

describe("ReviewPage highlight quote", () => {
  beforeEach(async () => {
    const client = await import("../api/client");
    vi.mocked(client.fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(client.fetchSkaterSkills).mockResolvedValue(skills);
    vi.mocked(client.fetchTrainingSessions).mockResolvedValue(sessions);
    vi.mocked(client.uploadAnalysis).mockResolvedValue({ id: "analysis-1", status: "pending" } as never);
    vi.mocked(client.uploadAnalysis).mockClear();
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
});
