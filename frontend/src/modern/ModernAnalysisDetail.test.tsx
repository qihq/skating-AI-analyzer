import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import * as experienceApi from "../analysis-v2/api";
import ModernAnalysisDetail from "./ModernAnalysisDetail";

vi.mock("../analysis-v2/api", () => ({ fetchAnalysisExperienceV2: vi.fn() }));
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
});
