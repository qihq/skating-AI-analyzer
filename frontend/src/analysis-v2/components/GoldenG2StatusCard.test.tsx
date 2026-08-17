import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fetchGoldenG2Status } from "../api";
import GoldenG2StatusCard from "./GoldenG2StatusCard";

vi.mock("../api", () => ({ fetchGoldenG2Status: vi.fn() }));

const fetchStatus = vi.mocked(fetchGoldenG2Status);

describe("GoldenG2StatusCard", () => {
  it("shows policy ranges and targeted profile gaps", async () => {
    fetchStatus.mockResolvedValue({
      schema_version: "golden-g2-status.v1",
      gate: "G2",
      status: "collecting",
      gate_policy_version: "golden-gate-policy.v2", evidence_scope: "limited_sample", event_count: 24,
      required_event_range: [24, 30], profile_ranges: { jump: [10, 14], spin: [6, 8], step: [4, 5], spiral: [4, 5] },
      distribution: { profiles: { jump: 10, spin: 4, step: 2, spiral: 2 }, splits: { unassigned: 24 }, strata: {}, recording_session_count: 4 },
      release_claim: false,
    });

    render(<GoldenG2StatusCard parentPin="1234" />);

    await waitFor(() => expect(screen.getByText("24/24-30")).toBeInTheDocument());
    expect(screen.getByText(/spin \+2/)).toBeInTheDocument();
    expect(screen.getByText(/step \+2/)).toBeInTheDocument();
    expect(screen.getByText(/spiral \+2/)).toBeInTheDocument();
    expect(screen.queryByText(/jump \+/)).not.toBeInTheDocument();
    expect(screen.getByText(/jump 10-14/)).toBeInTheDocument();
    expect(screen.getByText(/spin 6-8/)).toBeInTheDocument();
    expect(screen.getByText(/step 4-5/)).toBeInTheDocument();
    expect(screen.getByText(/spiral 4-5/)).toBeInTheDocument();
    expect(screen.getByText(/总量要求为 24-30/)).toBeInTheDocument();
  });

  it("shows a recorded baseline without claiming release approval", async () => {
    fetchStatus.mockResolvedValue({
      schema_version: "golden-g2-status.v1",
      gate: "G2",
      status: "baseline_recorded",
      gate_policy_version: "golden-gate-policy.v2", evidence_scope: "limited_sample", event_count: 24,
      required_event_range: [24, 30], profile_ranges: { jump: [10, 14], spin: [6, 8], step: [4, 5], spiral: [4, 5] },
      distribution: { profiles: { jump: 10, spin: 6, step: 4, spiral: 4 }, splits: { development: 18, validation: 3, frozen_test: 3 }, strata: {}, recording_session_count: 5 },
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

  it("keeps legacy v1 status readable with policy labels and range fallbacks", async () => {
    fetchStatus.mockResolvedValue({
      schema_version: "golden-g2-status.v1", gate: "G2", status: "collecting", event_count: 12,
      required_event_range: [60, 80],
      distribution: { profiles: { jump: 6, spin: 3, step: 2, spiral: 1 }, splits: { unassigned: 12 }, strata: {}, recording_session_count: 4 },
      release_claim: false,
    } as never);
    render(<GoldenG2StatusCard parentPin="1234" />);
    await waitFor(() => expect(screen.getByText(/golden-gate-policy\.v1 \(legacy evidence\)/)).toBeInTheDocument());
    expect(screen.getByText(/jump 24-32/)).toBeInTheDocument();
    expect(screen.getByText(/spin 16-20/)).toBeInTheDocument();
    expect(screen.getByText(/step 12-16/)).toBeInTheDocument();
    expect(screen.getByText(/spiral 8-12/)).toBeInTheDocument();
  });
});
