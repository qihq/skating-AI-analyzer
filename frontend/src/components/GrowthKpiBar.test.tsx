import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { GrowthSummary } from "../api/client";
import GrowthKpiBar from "./GrowthKpiBar";

const summary = {
  lesson_count: 8,
  completed_analysis_count: 12,
  current_month_analysis_count: 3,
  milestone_count: 4,
  metric_definitions: {
    lesson_count: "课次定义",
    completed_analysis_count: "累计定义",
    current_month_analysis_count: "本月定义",
    milestone_count: "里程碑定义",
  },
} as unknown as GrowthSummary;

describe("GrowthKpiBar", () => {
  it("renders only the four defined P0 metrics with definitions", () => {
    render(<GrowthKpiBar summary={summary} />);

    for (const label of ["训练课次", "累计复盘", "本月复盘", "成长里程碑"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByTitle("课次定义")).toBeInTheDocument();
    expect(screen.queryByText(/落冰率/)).not.toBeInTheDocument();
  });
});
