import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as analysisApi from "../analysis-v2/api";
import * as api from "../api/client";
import ModernTodayIsland from "./ModernTodayIsland";

vi.mock("../analysis-v2/api", () => ({ fetchAnalysisExperienceV2: vi.fn() }));
vi.mock("../api/client", async () => ({ ...(await vi.importActual("../api/client")), fetchSkaters: vi.fn(), fetchGrowthSummary: vi.fn(), fetchAnalysis: vi.fn() }));
vi.mock("../components/AppModeContext", () => ({ useAppMode: () => ({ isParentMode: false }) }));

describe("ModernTodayIsland presenter contract", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses the experience presenter for the latest-analysis card", async () => {
    vi.mocked(api.fetchSkaters).mockResolvedValue([{ id: "s1", name: "N", display_name: "N", is_default: true } as api.Skater]);
    vi.mocked(api.fetchGrowthSummary).mockResolvedValue({ latest_analysis_id: "a1", current_month_analysis_count: 1, milestone_count: 0, current_focus: null } as api.GrowthSummary);
    vi.mocked(analysisApi.fetchAnalysisExperienceV2).mockResolvedValue({
      schemaVersion: "analysis-experience.v2", analysisId: "a1", authority: "legacy", pipelineMode: "legacy", sourcePipelineFingerprint: "legacy:v1", diagnosticOnly: false, familyUsable: true,
      events: [{ eventId: "e1", profile: "跳跃", startPts: null, endPts: null, status: "confirmed", observability: "observable" }],
      claims: [{ analysisId: "a1", eventId: null, claimType: "report_summary", value: "来自 presenter", authority: "legacy", sourcePipelineFingerprint: "legacy:v1", definitionVersion: "v1", unit: null, convention: null, status: "confirmed", observability: "observable", confidence: null }], reviewTasks: [],
    });
    render(<MemoryRouter><ModernTodayIsland /></MemoryRouter>);
    expect((await screen.findAllByText("来自 presenter")).length).toBeGreaterThan(0);
    expect(api.fetchAnalysis).not.toHaveBeenCalled();
  });
});
