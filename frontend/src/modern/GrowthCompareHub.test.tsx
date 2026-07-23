import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import GrowthCompareHub from "./GrowthCompareHub";

vi.mock("../api/client", async () => ({ ...(await vi.importActual("../api/client")), fetchSkaters: vi.fn(), fetchAnalyses: vi.fn(), fetchAnalysisComparisons: vi.fn() }));

describe("GrowthCompareHub", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a comparison launcher instead of an invalid parameter error", async () => {
    vi.mocked(api.fetchSkaters).mockResolvedValue([{ id: "s1", name: "坦坦", display_name: "坦坦", is_default: true } as api.Skater]);
    vi.mocked(api.fetchAnalyses).mockResolvedValue([]);
    vi.mocked(api.fetchAnalysisComparisons).mockResolvedValue([]);
    render(<MemoryRouter><GrowthCompareHub /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "创建成长对比" })).toBeInTheDocument();
    expect(screen.queryByText("无效的对比参数。")).not.toBeInTheDocument();
  });
});
