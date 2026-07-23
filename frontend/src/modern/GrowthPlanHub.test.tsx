import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../api/client";
import GrowthPlanHub from "./GrowthPlanHub";

vi.mock("../api/client", async () => ({ ...(await vi.importActual("../api/client")), fetchSkaters: vi.fn(), fetchAnalyses: vi.fn(), fetchLatestPlanForSkater: vi.fn() }));

describe("GrowthPlanHub", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders an actionable empty state instead of an invalid plan id", async () => {
    vi.mocked(api.fetchSkaters).mockResolvedValue([{ id: "s1", name: "坦坦", display_name: "坦坦", is_default: true } as api.Skater]);
    vi.mocked(api.fetchAnalyses).mockResolvedValue([]);
    vi.mocked(api.fetchLatestPlanForSkater).mockRejectedValue({ response: { status: 404 } });
    render(<MemoryRouter><GrowthPlanHub /></MemoryRouter>);
    expect(await screen.findByText("还没有训练计划")).toBeInTheDocument();
    expect(screen.queryByText("无效的训练计划 ID。")).not.toBeInTheDocument();
  });
});
