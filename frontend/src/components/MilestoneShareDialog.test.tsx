import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GrowthMilestone } from "../api/client";
import MilestoneShareDialog from "./MilestoneShareDialog";

vi.mock("../utils/shareExport", () => ({
  exportShareDocument: vi.fn().mockResolvedValue({
    pages: [{
      blob: new Blob(["fake"], { type: "image/jpeg" }),
      filename: "milestone-test.jpg",
      mimeType: "image/jpeg",
      sizeBytes: 1000,
      canNativeShare: false,
    }],
  }),
}));

const milestone: GrowthMilestone = {
  id: "ms-1",
  occurred_at: "2026-07-15T00:00:00Z",
  type: "skill_unlock",
  title: "Waltz jump已点亮",
  note: "第一次完整起跳",
  verification: "parent_confirmed",
  source_skill_id: "skill-waltz",
  source_analysis_ids: ["a-1"],
  evidence_quality: "persisted",
};

describe("MilestoneShareDialog", () => {
  it("renders loading state then preview image", async () => {
    render(
      <MilestoneShareDialog
        open
        onClose={vi.fn()}
        skaterName="坦坦"
        milestone={milestone}
      />,
    );

    expect(screen.getAllByText("正在生成…")).not.toHaveLength(0);
    const img = await screen.findByAltText("分享里程碑预览");
    expect(img).toBeInTheDocument();
  });

  it("shows download and copy buttons after generation", async () => {
    render(
      <MilestoneShareDialog
        open
        onClose={vi.fn()}
        skaterName="坦坦"
        milestone={milestone}
      />,
    );

    await screen.findByAltText("分享里程碑预览");
    expect(screen.getByRole("button", { name: "复制到剪贴板" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载当前页" })).toBeInTheDocument();
  });

  it("calls onClose when clicking outside the dialog", async () => {
    const onClose = vi.fn();
    render(
      <MilestoneShareDialog
        open
        onClose={onClose}
        skaterName="坦坦"
        milestone={milestone}
      />,
    );

    await screen.findByAltText("分享里程碑预览");
    const backdrop = screen.getByRole("presentation");
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalled();
  });

  it("closes via the dismiss button", async () => {
    const onClose = vi.fn();
    render(
      <MilestoneShareDialog
        open
        onClose={onClose}
        skaterName="坦坦"
        milestone={milestone}
      />,
    );

    await screen.findByAltText("分享里程碑预览");
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("returns null when not open", () => {
    const { container } = render(
      <MilestoneShareDialog
        open={false}
        onClose={vi.fn()}
        skaterName="坦坦"
        milestone={milestone}
      />,
    );
    expect(container.innerHTML).toBe("");
  });
});
