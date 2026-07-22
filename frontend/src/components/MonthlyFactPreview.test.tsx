import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MonthlyFactSnapshot } from "../api/client";
import MonthlyFactPreview from "./MonthlyFactPreview";

function snapshot(facts: MonthlyFactSnapshot["facts"]): MonthlyFactSnapshot {
  return {
    schema_version: "monthly_facts.v1",
    skater_id: "skater-1",
    year_month: "2026-07",
    generated_at: "2026-07-31T00:00:00Z",
    coverage: { sessions: 2, completed_analyses: 3, comparable_metrics: 1 },
    facts,
    source_analysis_ids: [],
    source_session_ids: [],
    source_skill_ids: [],
    quality_flags: [],
    representative_frames: [],
  };
}

describe("MonthlyFactPreview", () => {
  it("groups facts and shows milestone verification badges", () => {
    render(
      <MonthlyFactPreview
        snapshot={snapshot([
          { id: "session_count", kind: "count", text: "本月记录 2 次训练课次", value: 2 },
          {
            id: "metric:Waltz:air_time_seconds",
            kind: "metric",
            metric: "air_time_seconds",
            label: "腾空时间",
            unit: "s",
            action_subtype: "Waltz",
            before: 0.4,
            after: 0.5,
            sample_count: 2,
          },
          {
            id: "milestone:skill-waltz",
            kind: "milestone",
            text: "Waltz jump已点亮",
            verification: "parent_confirmed",
            skill_id: "skill-waltz",
            source_analysis_ids: ["a-1"],
          },
          {
            id: "quote:a-1",
            kind: "quote",
            text: "我今天敢往后滑了",
            speaker: "skater",
            source_analysis_id: "a-1",
          },
        ])}
      />,
    );
    expect(screen.getByText("课次与复盘")).toBeInTheDocument();
    expect(screen.getByText("本月记录 2 次训练课次")).toBeInTheDocument();
    expect(screen.getByText("可比较指标")).toBeInTheDocument();
    expect(screen.getByText("里程碑")).toBeInTheDocument();
    expect(screen.getByText("家长确认")).toBeInTheDocument();
    expect(screen.getByText(/我今天敢往后滑了/)).toBeInTheDocument();
  });

  it("shows the low-data warning when quality_flags is set", () => {
    const snap = snapshot([]);
    snap.quality_flags = ["insufficient_comparable_evidence"];
    render(<MonthlyFactPreview snapshot={snap} />);
    expect(screen.getByText(/本月可比较指标较少/)).toBeInTheDocument();
  });

  it("renders system_detected badge for auto-unlocked milestones", () => {
    render(
      <MonthlyFactPreview
        snapshot={snapshot([
          {
            id: "milestone:skill-auto",
            kind: "milestone",
            text: "Back crossovers已点亮",
            verification: "system_detected",
            skill_id: "skill-auto",
            source_analysis_ids: [],
          },
        ])}
      />,
    );
    expect(screen.getByText("系统识别")).toBeInTheDocument();
  });
});