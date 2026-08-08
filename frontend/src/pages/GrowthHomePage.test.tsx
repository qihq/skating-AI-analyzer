import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchGrowthSummary, fetchMonthlyChapters, fetchSkaters } from "../api/client";
import * as experienceApi from "../analysis-v2/api";
import type { GrowthSummary, MonthlyChapter, Skater } from "../api/client";
import GrowthHomePage from "./GrowthHomePage";

vi.mock("../api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  fetchGrowthSummary: vi.fn(),
  fetchSkaters: vi.fn(),
  createMonthlyChapterFacts: vi.fn(),
  fetchMonthlyChapters: vi.fn(),
  generateMonthlyChapter: vi.fn(),
  patchMonthlyChapter: vi.fn(),
  publishMonthlyChapter: vi.fn(),
}));
vi.mock("../analysis-v2/api", () => ({ fetchAnalysisExperienceV2: vi.fn() }));

const summary: GrowthSummary = {
  schema_version: 1,
  skater_id: "skater-1",
  as_of: "2026-07-22T00:00:00Z",
  lesson_count: 8,
  completed_analysis_count: 12,
  current_month_analysis_count: 3,
  milestone_count: 4,
  latest_analysis_id: "analysis-1",
  current_focus: { label: "落冰保持", source_analysis_id: "analysis-1", quality: "good" },
  metric_definitions: {},
  recent_milestones: [],
};
const skaters = [
  { id: "skater-1", name: "tantan", display_name: "坦坦", is_default: true },
  { id: "skater-2", name: "zhaozhao", display_name: "昭昭", is_default: false },
] as Skater[];
const publishedChapter = { id: "chapter-1", status: "published" } as MonthlyChapter;

describe("GrowthHomePage", () => {
  beforeEach(() => {
    vi.mocked(fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(fetchGrowthSummary).mockImplementation(async (id) => ({ ...summary, skater_id: id, latest_analysis_id: id === "skater-1" ? "analysis-1" : null }));
    vi.mocked(experienceApi.fetchAnalysisExperienceV2).mockResolvedValue({
      schemaVersion: "analysis-experience.v2", analysisId: "analysis-1", authority: "v2", pipelineMode: "v2", sourcePipelineFingerprint: "v2:test", diagnosticOnly: false, familyUsable: true,
      events: [{ eventId: "e1", profile: "jump", state: "confirmed", startPts: 1, endPts: 2, status: "confirmed", observability: "observable" }],
      claims: [
        { analysisId: "analysis-1", eventId: null, claimType: "report_summary", value: "这次落冰更稳定", authority: "v2", sourcePipelineFingerprint: "v2:test", definitionVersion: "v1", unit: null, convention: null, status: "confirmed", observability: "observable", confidence: 0.9 },
        { analysisId: "analysis-1", eventId: null, claimType: "next_action", value: "做三组落冰定格", authority: "v2", sourcePipelineFingerprint: "v2:test", definitionVersion: "v1", unit: null, convention: null, status: "confirmed", observability: "observable", confidence: 0.9 },
      ], reviewTasks: [],
    });
    vi.mocked(fetchMonthlyChapters).mockImplementation(async (id) => id === "skater-1" ? [publishedChapter] : []);
  });

  it("loads the default skater and composes the growth story", async () => {
    render(<MemoryRouter><GrowthHomePage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "看见每次训练，积累每一步进步" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "当前练习档案" })).toHaveValue("skater-1");
    expect((await screen.findAllByText("落冰保持")).length).toBeGreaterThan(0);
    expect(screen.getByText("这次落冰更稳定")).toBeInTheDocument();
    expect(screen.getByText("做三组落冰定格")).toBeInTheDocument();
    expect(await screen.findByText("最近复盘")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /年度/ })).toHaveAttribute("href", "/annual");
  });

  it("reloads the selected skater and handles an empty analysis history", async () => {
    render(<MemoryRouter><GrowthHomePage /></MemoryRouter>);
    fireEvent.change(await screen.findByRole("combobox", { name: "当前练习档案" }), { target: { value: "skater-2" } });
    await waitFor(() => expect(fetchGrowthSummary).toHaveBeenCalledWith("skater-2"));
    expect(await screen.findByText("完成第一次复盘后，这里会出现关键动作阶段。")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /年度/ })).not.toBeInTheDocument();
  });

  it("keeps the growth summary available when the annual entry check fails", async () => {
    vi.mocked(fetchMonthlyChapters).mockRejectedValueOnce(new Error("chapters unavailable"));
    render(<MemoryRouter><GrowthHomePage /></MemoryRouter>);
    expect(await screen.findByText("这次落冰更稳定")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("link", { name: /年度/ })).not.toBeInTheDocument());
  });
});
