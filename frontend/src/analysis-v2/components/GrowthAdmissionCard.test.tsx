import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as api from "../api";
import GrowthAdmissionCard from "./GrowthAdmissionCard";

vi.mock("../api", () => ({ fetchGrowthAdmission: vi.fn() }));

describe("GrowthAdmissionCard", () => {
  it("shows included and excluded counts with family-language reasons", async () => {
    vi.mocked(api.fetchGrowthAdmission).mockResolvedValue({
      schema_version: "growth-profile-admission.v1",
      included_count: 2,
      excluded_count: 3,
      excluded_reasons: { ambiguous_profile: 1, shadow_diagnostic: 2 },
      diagnostic_only: true,
    });
    render(<GrowthAdmissionCard analysisIds={["a1", "a2"]} parentPin="1234" />);
    expect(await screen.findByText("纳入 2")).toBeInTheDocument();
    expect(screen.getByText("排除 3")).toBeInTheDocument();
    expect(screen.getByText("动作家庭有歧义：1")).toBeInTheDocument();
    expect(screen.getByText("Shadow 诊断结果不进入成长记录：2")).toBeInTheDocument();
  });

  it("renders an accessible error state", async () => {
    vi.mocked(api.fetchGrowthAdmission).mockRejectedValue(new Error("offline"));
    render(<GrowthAdmissionCard analysisIds={["a1"]} parentPin="1234" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法读取");
  });
});
