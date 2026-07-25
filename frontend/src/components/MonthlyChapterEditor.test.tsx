import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MonthlyChapter } from "../api/client";
import MonthlyChapterEditor from "./MonthlyChapterEditor";

function chapter(overrides: Partial<MonthlyChapter>): MonthlyChapter {
  return {
    id: "chapter-1",
    skater_id: "skater-1",
    year_month: "2026-07",
    revision: 1,
    status: "generated",
    fact_snapshot: {
      schema_version: "monthly_facts.v1",
      skater_id: "skater-1",
      year_month: "2026-07",
      generated_at: "2026-07-31T00:00:00Z",
      coverage: { sessions: 0, completed_analyses: 0, comparable_metrics: 0 },
      facts: [],
      source_analysis_ids: [],
      source_session_ids: [],
      source_skill_ids: [],
      quality_flags: [],
      representative_frames: [],
    },
    source_hash: "abc",
    generated_payload: {},
    draft_text: "AI 初稿内容。",
    final_text: null,
    quality_flags: [],
    representative_frames: [],
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
    published_at: null,
    ...overrides,
  };
}

describe("MonthlyChapterEditor", () => {
  it("shows the AI draft and a character counter", () => {
    render(
      <MonthlyChapterEditor
        chapter={chapter({ final_text: null, draft_text: "AI 初稿内容。" })}
        onSaveDraft={vi.fn()}
        onPublish={vi.fn()}
        saving={false}
        error={null}
      />,
    );
    expect(screen.getByText("AI 初稿", { selector: "summary" })).toBeInTheDocument();
    expect(document.querySelector("pre")?.textContent ?? "").toContain("AI 初稿内容。");
    expect(screen.getByLabelText("最终文字")).toHaveValue("AI 初稿内容。");
  });

  it("offers a new revision when the chapter is published", () => {
    render(
      <MonthlyChapterEditor
        chapter={chapter({ status: "published", final_text: "已发布最终文字。", published_at: "2026-07-31T00:00:00Z" })}
        onSaveDraft={vi.fn()}
        onPublish={vi.fn()}
        saving={false}
        error={null}
      />,
    );
    expect(screen.getByRole("button", { name: "创建新版本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
    expect(screen.getByText("已发布")).toBeInTheDocument();
  });

  it("calls onPublish only after the confirm dialog is accepted", async () => {
    const onPublish = vi.fn().mockResolvedValue(undefined);

    render(
      <MonthlyChapterEditor
        chapter={chapter({})}
        onSaveDraft={vi.fn()}
        onPublish={onPublish}
        saving={false}
        error={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "确认发布" }));
    expect(onPublish).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(dialog.querySelectorAll("button")[1]);
    await waitFor(() => expect(onPublish).toHaveBeenCalledTimes(1));
  });

  it("renders error message and calls onSaveDraft when saving", () => {
    const onSaveDraft = vi.fn().mockResolvedValue(undefined);
    render(
      <MonthlyChapterEditor
        chapter={chapter({})}
        onSaveDraft={onSaveDraft}
        onPublish={vi.fn()}
        saving={false}
        error="保存失败"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("保存失败");
    screen.getByRole("button", { name: "保存修改" }).click();
    expect(onSaveDraft).toHaveBeenCalledTimes(1);
  });
});
