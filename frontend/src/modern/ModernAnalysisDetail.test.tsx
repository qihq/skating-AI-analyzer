import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import * as experienceApi from "../analysis-v2/api";
import ModernAnalysisDetail from "./ModernAnalysisDetail";

vi.mock("../analysis-v2/api", () => ({ fetchAnalysisExperienceV2: vi.fn(), fetchAnalysisExperienceV2Diagnostic: vi.fn() }));
vi.mock("../components/AppModeContext", () => ({ useAppMode: () => ({ isParentMode: false, parentPin: null }) }));
vi.mock("../pages/ReportPage", () => ({ default: () => <div>legacy report</div> }));
vi.mock("../pages/ReportWorkspacePage", () => ({ default: () => <div>legacy workspace</div> }));

describe("ModernAnalysisDetail presenter contract", () => {
  it("loads the single experience contract for an analysis route", async () => {
    vi.mocked(experienceApi.fetchAnalysisExperienceV2).mockResolvedValue({
      schemaVersion: "analysis-experience.v2", analysisId: "a1", authority: "legacy", pipelineMode: "legacy",
      sourcePipelineFingerprint: "legacy:v1", diagnosticOnly: false, familyUsable: true, events: [],
      claims: [{ analysisId: "a1", eventId: null, claimType: "report_summary", value: "presenter summary", authority: "legacy", sourcePipelineFingerprint: "legacy:v1", definitionVersion: "v1", unit: null, convention: null, status: "confirmed", observability: "observable", confidence: null }],
      reviewTasks: [],
    });
    render(<MemoryRouter initialEntries={["/analysis/a1"]}><Routes><Route path="/analysis/:id" element={<ModernAnalysisDetail />} /></Routes></MemoryRouter>);
    await waitFor(() => expect(experienceApi.fetchAnalysisExperienceV2).toHaveBeenCalledWith("a1"));
    expect(await screen.findByTestId("analysis-experience-contract")).toHaveTextContent("Legacy");
    expect(screen.getByText("presenter summary")).toBeInTheDocument();
  });

  it("keeps a diagnostic multi-event selection in the deep link", async () => {
    vi.mocked(experienceApi.fetchAnalysisExperienceV2).mockResolvedValue({
      schemaVersion: "analysis-experience.v2", analysisId: "a1", authority: "v2", pipelineMode: "v2", sourcePipelineFingerprint: "v2:fp", diagnosticOnly: true, familyUsable: false, claims: [], reviewTasks: [],
      events: [
        { eventId: "e1", profile: "unknown", startPts: 1, endPts: 2, status: "uncertain", observability: "observable", proposalStatus: "pending_confirmation" },
        { eventId: "e2", profile: "unknown", startPts: 3, endPts: 4, status: "uncertain", observability: "partially_observable", proposalStatus: "unknown" },
      ],
    });
    render(<MemoryRouter initialEntries={["/analysis/a1?event=e2"]}><Routes><Route path="/analysis/:id" element={<ModernAnalysisDetail />} /></Routes></MemoryRouter>);
    expect(await screen.findByTestId("selected-proposal")).toHaveTextContent("e2");
    expect(screen.getByRole("option", { name: /Event 2/ })).toHaveAttribute("aria-selected", "true");
  });
});
