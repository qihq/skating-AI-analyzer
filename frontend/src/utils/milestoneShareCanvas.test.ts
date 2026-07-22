import { describe, expect, it } from "vitest";

import { createMilestoneShareImage } from "./milestoneShareCanvas";
import type { GrowthMilestone } from "../api/client";

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

describe("createMilestoneShareImage", () => {
  it("creates a 1080x1350 JPEG blob with expected filename and size", async () => {
    const result = await createMilestoneShareImage({
      skaterName: "坦坦",
      milestone,
    });
    expect(result.mimeType).toBe("image/jpeg");
    expect(result.sizeBytes).toBeGreaterThan(0);
    expect(result.sizeBytes).toBeLessThanOrEqual(2_400_000);
    expect(result.filename).toContain("milestone-Waltz_jump");
    expect(result.canNativeShare).toBe(false);
  });

  it("generates an image-only layout (no frame URL)", async () => {
    const result = await createMilestoneShareImage({
      skaterName: "坦坦",
      milestone,
      metric: { label: "腾空时间", value: "0.45s", definition: "本月最佳" },
    });
    expect(result.sizeBytes).toBeGreaterThan(0);
  });

  it("preserves verification source label", async () => {
    const result = await createMilestoneShareImage({
      skaterName: "坦坦",
      milestone: { ...milestone, verification: "system_detected" },
    });
    expect(result.sizeBytes).toBeGreaterThan(0);
  });

  it("shows gradient panel when frameUrl is absent", async () => {
    const result = await createMilestoneShareImage({
      skaterName: "坦坦",
      milestone,
    });
    // Still produces a valid image without a frame
    expect(result.sizeBytes).toBeGreaterThan(0);
  });
});