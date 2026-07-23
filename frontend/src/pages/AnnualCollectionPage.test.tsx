import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createAnnualCollection,
  createAnnualExport,
  fetchAnnualExport,
  fetchAnnualMilestones,
  fetchMonthlyChapters,
  fetchSkaters,
  previewAnnualCollection,
} from "../api/client";
import type { MonthlyChapter, Skater } from "../api/client";
import AnnualCollectionPage from "./AnnualCollectionPage";

vi.mock("../api/client", () => ({
  fetchSkaters: vi.fn(),
  fetchMonthlyChapters: vi.fn(),
  previewAnnualCollection: vi.fn(),
  createAnnualCollection: vi.fn(),
  createAnnualExport: vi.fn(),
  fetchAnnualExport: vi.fn(),
  fetchAnnualMilestones: vi.fn(),
}));

const chapter: MonthlyChapter = {
  id: "chapter-1", skater_id: "skater-1", year_month: "2026-01", revision: 1, status: "published",
  fact_snapshot: { schema_version: "monthly_facts.v1", skater_id: "skater-1", year_month: "2026-01", generated_at: "2026-01-31T00:00:00Z", coverage: { sessions: 2, completed_analyses: 3, comparable_metrics: 0 }, facts: [], source_analysis_ids: [], source_session_ids: [], source_skill_ids: [], quality_flags: [], representative_frames: [] },
  source_hash: "a".repeat(64), generated_payload: null, draft_text: null, final_text: "一月的成长记录", quality_flags: [], representative_frames: [], created_at: "2026-01-31T00:00:00Z", updated_at: "2026-01-31T00:00:00Z", published_at: "2026-01-31T00:00:00Z",
};

const skater: Skater = {
  id: "skater-1", name: "tantan", display_name: "坦坦", is_default: true,
  avatar_emoji: "⛸", avatar_type: "emoji", birth_year: 2018, current_level: "基础",
  avatar_level: 1, total_xp: 0, current_streak: 0, longest_streak: 0, last_active_date: null,
  level: null, notes: null, created_at: "2026-01-01T00:00:00Z",
};

describe("AnnualCollectionPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchSkaters).mockResolvedValue([skater]);
    vi.mocked(fetchMonthlyChapters).mockResolvedValue([chapter]);
    vi.mocked(fetchAnnualMilestones).mockResolvedValue([]);
    vi.mocked(previewAnnualCollection).mockResolvedValue({ snapshot: {}, source_hash: "b".repeat(64), coverage: { published_chapter_count: 1, text_only_chapter_count: 1, selected_milestone_count: 0 } });
    vi.mocked(createAnnualCollection).mockResolvedValue({ id: "collection-1", skater_id: "skater-1", year: 2026, revision: 1, status: "ready", title: "2026 年度成长合集", selected_chapter_ids: ["chapter-1"], selected_milestone_ids: [], snapshot: {}, source_hash: "b".repeat(64), created_at: "2026-07-23T00:00:00Z", updated_at: "2026-07-23T00:00:00Z" });
    vi.mocked(createAnnualExport).mockResolvedValue({ id: "export-1", collection_id: "collection-1", status: "pending", renderer_version: "annual_pdf.v1", asset_relative_path: null, file_sha256: null, page_count: null, error_message: null, created_at: "2026-07-23T00:00:00Z", completed_at: null });
    vi.mocked(fetchAnnualExport).mockResolvedValue({ id: "export-1", collection_id: "collection-1", status: "completed", renderer_version: "annual_pdf.v1", asset_relative_path: "annual/collection-1/export-1.pdf", file_sha256: "c".repeat(64), page_count: 5, error_message: null, created_at: "2026-07-23T00:00:00Z", completed_at: "2026-07-23T00:01:00Z" });
  });

  it("defaults to all published chapters and exports a rebuildable annual PDF", async () => {
    render(<MemoryRouter><AnnualCollectionPage /></MemoryRouter>);
    expect(await screen.findByText("一月的成长记录")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /2026-01/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "预览合集" }));
    await waitFor(() => expect(previewAnnualCollection).toHaveBeenCalledWith("skater-1", 2026, ["chapter-1"], []));
    fireEvent.click(screen.getByRole("button", { name: "生成年度 PDF" }));
    await waitFor(() => expect(createAnnualCollection).toHaveBeenCalled());
    await waitFor(() => expect(createAnnualExport).toHaveBeenCalledWith("collection-1"));
    expect(await screen.findByRole("link", { name: "下载年度 PDF" })).toHaveAttribute("href", "/api/annual/exports/export-1/download");
  });

  it("retries a failed annual PDF export from the status panel", async () => {
    vi.mocked(fetchAnnualExport).mockResolvedValue({ id: "export-1", collection_id: "collection-1", status: "failed", renderer_version: "annual_pdf.v1", asset_relative_path: null, file_sha256: null, page_count: null, error_message: "font unavailable", created_at: "2026-07-23T00:00:00Z", completed_at: "2026-07-23T00:01:00Z" });
    render(<MemoryRouter><AnnualCollectionPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /PDF/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("font unavailable");
    fireEvent.click(screen.getByRole("button", { name: "重新生成年度 PDF" }));
    await waitFor(() => expect(createAnnualExport).toHaveBeenCalledTimes(2));
    expect(createAnnualExport).toHaveBeenLastCalledWith("collection-1");
  });
});
