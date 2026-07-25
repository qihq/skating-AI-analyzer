import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createMonthlyChapterFacts,
  fetchSkaters,
  fetchMonthlyChapters,
  generateMonthlyChapter,
  patchMonthlyChapter,
  reviseMonthlyChapter,
  publishMonthlyChapter,
} from "../api/client";
import type { MonthlyChapter, Skater } from "../api/client";
import MonthlyChaptersPage from "./MonthlyChaptersPage";

vi.mock("../api/client", () => ({
  fetchSkaters: vi.fn(),
  fetchMonthlyChapters: vi.fn(),
  createMonthlyChapterFacts: vi.fn(),
  generateMonthlyChapter: vi.fn(),
  patchMonthlyChapter: vi.fn(),
  reviseMonthlyChapter: vi.fn(),
  recycleMonthlyChapter: vi.fn(),
  restoreMonthlyChapter: vi.fn(),
  permanentlyDeleteMonthlyChapter: vi.fn(),
  publishMonthlyChapter: vi.fn(),
}));

vi.mock("../components/AppModeContext", () => ({
  useAppMode: () => ({ parentPin: "1234", enterParentMode: vi.fn() }),
}));

const skaters = [{ id: "skater-1", name: "tantan", display_name: "坦坦", is_default: true }] as Skater[];

function makeChapter(overrides: Partial<MonthlyChapter> = {}): MonthlyChapter {
  return {
    id: "chapter-1",
    skater_id: "skater-1",
    year_month: "2026-07",
    revision: 1,
    status: "facts_ready",
    fact_snapshot: {
      schema_version: "monthly_facts.v1",
      skater_id: "skater-1",
      year_month: "2026-07",
      generated_at: "2026-07-31T00:00:00Z",
      coverage: { sessions: 2, completed_analyses: 3, comparable_metrics: 0 },
      facts: [
        { id: "session_count", kind: "count", text: "本月记录 2 次训练课次", value: 2 },
        { id: "quote:a-1", kind: "quote", text: "我今天敢往后滑了", speaker: "skater", source_analysis_id: "a-1" },
      ],
      source_analysis_ids: ["a-1"],
      source_session_ids: [],
      source_skill_ids: [],
      quality_flags: ["insufficient_comparable_evidence"],
      representative_frames: [],
    },
    source_hash: "abc",
    generated_payload: null,
    draft_text: null,
    final_text: null,
    quality_flags: ["insufficient_comparable_evidence"],
    representative_frames: [],
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
    published_at: null,
    ...overrides,
  };
}

describe("MonthlyChaptersPage", () => {
  beforeEach(() => {
    vi.mocked(fetchSkaters).mockReset();
    vi.mocked(fetchMonthlyChapters).mockReset();
    vi.mocked(createMonthlyChapterFacts).mockReset();
    vi.mocked(generateMonthlyChapter).mockReset();
    vi.mocked(patchMonthlyChapter).mockReset();
    vi.mocked(reviseMonthlyChapter).mockReset();
    vi.mocked(publishMonthlyChapter).mockReset();
    vi.mocked(fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(fetchMonthlyChapters).mockResolvedValue([]);
    vi.mocked(createMonthlyChapterFacts).mockResolvedValue(makeChapter({ id: "chapter-new" }));
    vi.mocked(generateMonthlyChapter).mockResolvedValue(makeChapter({ id: "chapter-new", status: "generated", draft_text: "AI 初稿。" }));
    vi.mocked(patchMonthlyChapter).mockResolvedValue(makeChapter({ id: "chapter-new", status: "generated", final_text: "编辑后的文字。" }));
    vi.mocked(reviseMonthlyChapter).mockResolvedValue(makeChapter({ id: "chapter-2", revision: 2, status: "generated", final_text: "已发布文字。" }));
    vi.mocked(publishMonthlyChapter).mockResolvedValue(makeChapter({ id: "chapter-new", status: "published", final_text: "编辑后的文字。", published_at: "2026-07-31T12:00:00Z" }));
  });

  it("shows revision history when multiple revisions exist", async () => {
    vi.mocked(fetchMonthlyChapters).mockResolvedValue([
      makeChapter({ id: "chapter-2", revision: 2, status: "published" }),
      makeChapter({ id: "chapter-1", revision: 1, status: "facts_ready" }),
    ]);

    render(
      <MemoryRouter>
        <MonthlyChaptersPage />
      </MemoryRouter>,
    );

    await screen.findAllByText("第 2 次修订（已发布）");
    fireEvent.click(screen.getByLabelText("选择修订"));
    expect(await screen.findByRole("option", { name: /第 1 次修订（事实就绪）/ })).toBeInTheDocument();
  });

  it("creates a new version from a published chapter", async () => {
    vi.mocked(fetchMonthlyChapters).mockResolvedValue([makeChapter({ id: "chapter-1", status: "published", final_text: "已发布文字。" })]);

    render(
      <MemoryRouter>
        <MonthlyChaptersPage />
      </MemoryRouter>,
    );

    const saveButton = await screen.findByRole("button", { name: "创建新版本" });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);
    await waitFor(() => expect(reviseMonthlyChapter).toHaveBeenCalled());
    fireEvent.click(screen.getByLabelText("选择修订"));
    expect(await screen.findByRole("option", { name: /第 1 次修订（已发布）/ })).toBeInTheDocument();
  });

  it("keeps facts on generation error and surfaces the message", async () => {
    vi.mocked(generateMonthlyChapter).mockRejectedValueOnce({ response: { data: { detail: "生成失败，请稍后重试。" } } });

    render(
      <MemoryRouter>
        <MonthlyChaptersPage />
      </MemoryRouter>,
    );

    const gatherButton = screen.getByRole("button", { name: "整理本月事实" });
    await waitFor(() => expect(gatherButton).toBeEnabled());
    fireEvent.click(gatherButton);
    await screen.findByText("本月记录 2 次训练课次");

    fireEvent.click(screen.getByRole("button", { name: "生成叙事初稿" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("生成失败，请稍后重试。"));
    // facts preview remains
    expect(screen.getByText("本月记录 2 次训练课次")).toBeInTheDocument();
  });
});
