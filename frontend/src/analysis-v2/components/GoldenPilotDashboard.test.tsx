import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAppMode } from "../../components/AppModeContext";
import { fetchPilotEvaluatorResult, fetchPilotEvaluatorStatus, fetchPilotEventDiagnostic, fetchPilotProgress } from "../api";
import type { PilotProgress } from "../golden-contracts";
import GoldenPilotDashboard from "./GoldenPilotDashboard";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({ fetchPilotProgress: vi.fn(), fetchPilotEvaluatorStatus: vi.fn(), fetchPilotEvaluatorResult: vi.fn(), fetchPilotEventDiagnostic: vi.fn() }));

const progress = vi.mocked(fetchPilotProgress);
const status = vi.mocked(fetchPilotEvaluatorStatus);
const result = vi.mocked(fetchPilotEvaluatorResult);
const diagnostic = vi.mocked(fetchPilotEventDiagnostic);

function waitingProgress(): PilotProgress {
  return { gate: "G1", status: "waiting_for_owner_labels", diagnostic_only: true, release_claim: false, profiles: [{ key: "jump", count: 0, target: 14, missing: 14 }, { key: "spin", count: 0, target: 10, missing: 10 }, { key: "step", count: 0, target: 6, missing: 6 }, { key: "spiral", count: 0, target: 6, missing: 6 }], scenes: [{ key: "crossing/occlusion", count: 0, target: 1, missing: 1 }], requirements: { event_count: { count: 0, target: 36, passed: false }, recording_sessions: { count: 0, target: 5, passed: false }, schema_valid: { count: 0, target: 36, passed: false }, delayed_review: { count: 0, target: 4, passed: false } }, next_best_videos: ["crossing/occlusion", "jump"] };
}

describe("GoldenPilotDashboard", () => {
  beforeEach(() => {
    vi.mocked(useAppMode).mockReturnValue({ parentPin: "1234" } as never);
    progress.mockResolvedValue(waitingProgress());
    status.mockResolvedValue({ status: "not_run", evaluator_version: "v1", diagnostic_only: true, message: null });
    result.mockResolvedValue(null);
    diagnostic.mockResolvedValue({ event_id: "private-event", source_pts: 1.234 });
  });

  it("shows profile/scene gaps and diagnostic-only waiting state", async () => {
    render(<GoldenPilotDashboard/>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Waiting for owner labels" })).toBeInTheDocument());
    expect(screen.getAllByText(/0\/36/)).toHaveLength(2);
    expect(screen.getByText(/missing 14/)).toBeInTheDocument();
    expect(screen.getByText(/crossing\/occlusion, jump/)).toBeInTheDocument();
    expect(screen.getByText(/diagnostic only/i)).toBeInTheDocument();
  });

  it("renders raw denominator, CI, confusion, and a non-mutating drill-down link", async () => {
    result.mockResolvedValue({ schema_version: "golden-pilot-sanitized-report.v1", evaluator_version: "v1", dataset_id: "pilot", dataset_fingerprint: "a", pipeline_fingerprint: "b", evaluation_masks: ["tracking", "action"], diagnostic_only: true, release_claim: false, deterministic_fingerprint: "c", repeatability: { deterministic: true, fingerprint: "c" }, aggregate: { tracking: { confirmed_coverage: { numerator: 8, denominator: 10, rate: .8, confidence_interval_95: [.49, .94] } }, action: { confusion_matrix: { jump: { spin: 1 } } }, strata: { crossing: { event_count: 2 } } }, failed_events: [{ alias: "event-001", profile: "jump", strata: ["crossing"], failure_codes: ["tracking_wrong_person"] }] });
    render(<GoldenPilotDashboard/>);
    await waitFor(() => expect(screen.getByText(/8\/10/)).toBeInTheDocument());
    expect(screen.getByText(/95% CI 49.0-94.0%/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Sanitized strata and confusion/)).toHaveTextContent("spin");
    fireEvent.click(screen.getByRole("button", { name: /event-001/ }));
    await waitFor(() => expect(screen.getByRole("link", { name: /exact source PTS 1.234000/ })).toHaveAttribute("href", "/golden?event=private-event&pts=1.234"));
    expect(screen.getByRole("status")).toHaveTextContent(/never mutates Ground Truth/);
  });

  it("announces loading and failed transport states", async () => {
    progress.mockRejectedValue(new Error("offline"));
    render(<GoldenPilotDashboard/>);
    expect(screen.getByText(/Loading Golden pilot/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("shows a recoverable error when private failed-event drill-down is unavailable", async () => {
    result.mockResolvedValue({ schema_version: "golden-pilot-sanitized-report.v1", evaluator_version: "v1", dataset_id: "pilot", dataset_fingerprint: "a", pipeline_fingerprint: "b", evaluation_masks: ["tracking"], diagnostic_only: true, release_claim: false, deterministic_fingerprint: "c", repeatability: { deterministic: true, fingerprint: "c" }, aggregate: {}, failed_events: [{ alias: "event-001", profile: "jump", strata: ["crossing"], failure_codes: ["tracking_wrong_person"] }] });
    diagnostic.mockRejectedValue(new Error("offline"));
    render(<GoldenPilotDashboard/>);
    await waitFor(() => expect(screen.getByRole("button", { name: /event-001/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /event-001/ }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/is unavailable. Retry the event link/));
    expect(screen.getByRole("status")).toHaveTextContent(/never mutates Ground Truth/);
  });
});
