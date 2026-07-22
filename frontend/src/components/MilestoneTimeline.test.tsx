import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { GrowthMilestone } from "../api/client";
import MilestoneTimeline from "./MilestoneTimeline";

const event = (id: string, verification: GrowthMilestone["verification"], note: string | null): GrowthMilestone => ({
  id,
  occurred_at: `2026-07-${id}T00:00:00Z`,
  type: "skill_unlock",
  title: `里程碑 ${id}`,
  note,
  verification,
  source_skill_id: `skill-${id}`,
  source_analysis_ids: [],
  evidence_quality: "persisted",
});

describe("MilestoneTimeline", () => {
  it("preserves API order and verification source", () => {
    render(
      <MilestoneTimeline
        items={[
          event("18", "parent_confirmed", "连续完成三次"),
          event("17", "coach_confirmed", null),
          event("16", "system_detected", null),
        ]}
      />,
    );

    expect(screen.getAllByRole("listitem").map((item) => item.textContent?.includes("里程碑 18"))).toEqual([true, false, false]);
    expect(screen.getByText("家长确认")).toBeInTheDocument();
    expect(screen.getByText("教练确认")).toBeInTheDocument();
    expect(screen.getByText("系统检测")).toBeInTheDocument();
    expect(screen.getAllByText("连续完成三次")).toHaveLength(1);
  });

  it("renders an explicit empty state", () => {
    render(<MilestoneTimeline items={[]} />);
    expect(screen.getByText("还没有已确认的成长里程碑")).toBeInTheDocument();
  });
});
