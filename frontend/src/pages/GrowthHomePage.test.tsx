import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAnalysis, fetchGrowthSummary, fetchSkaters } from "../api/client";
import type { AnalysisDetail, GrowthSummary, Skater } from "../api/client";
import GrowthHomePage from "./GrowthHomePage";

vi.mock("../api/client", () => ({
  fetchAnalysis: vi.fn(),
  fetchGrowthSummary: vi.fn(),
  fetchSkaters: vi.fn(),
}));
vi.mock("../components/ActionPhaseStrip", () => ({ default: () => <div>阶段联图</div> }));

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
const analysis = {
  id: "analysis-1",
  report: { summary: "这次落冰更稳定", training_focus: "落冰保持", improvements: [{ target: "膝盖缓冲", action: "做三组落冰定格" }] },
  pose_data: null,
} as AnalysisDetail;

describe("GrowthHomePage", () => {
  beforeEach(() => {
    vi.mocked(fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(fetchGrowthSummary).mockImplementation(async (id) => ({ ...summary, skater_id: id, latest_analysis_id: id === "skater-1" ? "analysis-1" : null }));
    vi.mocked(fetchAnalysis).mockResolvedValue(analysis);
  });

  it("loads the default skater and composes the growth story", async () => {
    render(<MemoryRouter><GrowthHomePage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "看见每次训练，积累每一步进步" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "当前练习档案" })).toHaveValue("skater-1");
    expect(await screen.findByText("落冰保持")).toBeInTheDocument();
    expect(screen.getByText("这次落冰更稳定")).toBeInTheDocument();
    expect(screen.getByText("做三组落冰定格")).toBeInTheDocument();
    expect(await screen.findByText("阶段联图")).toBeInTheDocument();
  });

  it("reloads the selected skater and handles an empty analysis history", async () => {
    render(<MemoryRouter><GrowthHomePage /></MemoryRouter>);
    fireEvent.change(await screen.findByRole("combobox", { name: "当前练习档案" }), { target: { value: "skater-2" } });
    await waitFor(() => expect(fetchGrowthSummary).toHaveBeenCalledWith("skater-2"));
    expect(await screen.findByText("完成第一次复盘后，这里会出现关键动作阶段。")).toBeInTheDocument();
  });
});
