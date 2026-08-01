import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fetchGoldenG2Status } from "../api";
import GoldenG2StatusCard from "./GoldenG2StatusCard";

vi.mock("../api", () => ({ fetchGoldenG2Status: vi.fn() }));

const fetchStatus = vi.mocked(fetchGoldenG2Status);

describe("GoldenG2StatusCard", () => {
  it("shows that the current dataset cannot be frozen before 60 events", async () => {
    fetchStatus.mockResolvedValue({
      schema_version: "golden-g2-status.v1",
      gate: "G2",
      status: "collecting",
      event_count: 12,
      required_event_range: [60, 80],
      distribution: { profiles: { jump: 6, spin: 3, step: 2, spiral: 1 }, splits: { unassigned: 12 }, strata: {}, recording_session_count: 4 },
      release_claim: false,
    });

    render(<GoldenG2StatusCard parentPin="1234" />);

    await waitFor(() => expect(screen.getByText("12/60-80")).toBeInTheDocument());
    expect(screen.getByText(/不能冻结/)).toBeInTheDocument();
  });

  it("shows a recorded baseline without claiming release approval", async () => {
    fetchStatus.mockResolvedValue({
      schema_version: "golden-g2-status.v1",
      gate: "G2",
      status: "baseline_recorded",
      event_count: 60,
      required_event_range: [60, 80],
      distribution: { profiles: { jump: 24, spin: 16, step: 12, spiral: 8 }, splits: { development: 36, validation: 12, frozen_test: 12 }, strata: {}, recording_session_count: 5 },
      dataset_revision: 80,
      dataset_fingerprint: "dataset:123",
      legacy_pipeline_fingerprint: "legacy:v5.2.307",
      baseline_result_fingerprint: "result:123",
      release_claim: false,
    });

    render(<GoldenG2StatusCard parentPin="1234" />);

    await waitFor(() => expect(screen.getByText(/legacy:v5.2.307/)).toBeInTheDocument());
    expect(screen.getByText(/不代表发布通过/)).toBeInTheDocument();
  });
});
