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
  return { gate: "G1", gate_policy_version: "golden-gate-policy.v2", evidence_scope: "limited_sample", status: "waiting_for_owner_labels", diagnostic_only: true, release_claim: false, profiles: [{ key: "jump", count: 10, target: 10, missing: 0 }, { key: "spin", count: 4, target: 4, missing: 0 }, { key: "step", count: 2, target: 2, missing: 0 }, { key: "spiral", count: 2, target: 2, missing: 0 }], scenes: [{ key: "crossing/occlusion", count: 7, target: 1, missing: 0 }], requirements: { source_video_count: { count: 18, target: 18, passed: true }, event_count: { count: 18, target: 18, passed: true }, recording_sessions: { count: 17, target: 5, passed: true }, schema_valid: { count: 18, target: 18, passed: true }, split_grouping: { issues: ["session:split-inconsistent"], passed: false }, delayed_review: { count: 0, target: 2, passed: false }, ambiguous_rotation_double_review: { count: 0, target: 5, passed: false } }, next_actions: ["assign_consistent_splits", "complete_delayed_reviews", "complete_ambiguous_rotation_reviews"], next_best_videos: [] };
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
    expect(screen.getAllByText(/18\/18/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/0\/2/)).toBeInTheDocument();
    expect(screen.getByText(/limited_sample/)).toBeInTheDocument();
    expect(screen.getByText(/assign_consistent_splits/)).toBeInTheDocument();
    expect(screen.queryByText(/jump \+/i)).not.toBeInTheDocument();
    expect(screen.getByText(/diagnostic only/i)).toBeInTheDocument();
  });

  it("renders raw denominator, CI, confusion, and a non-mutating drill-down link", async () => {
    result.mockResolvedValue({ schema_version: "golden-pilot-sanitized-report.v1", evaluator_version: "v1", dataset_id: "pilot", dataset_fingerprint: "a", pipeline_fingerprint: "b", evaluation_masks: ["tracking", "action"], diagnostic_only: true, release_claim: false, deterministic_fingerprint: "c", repeatability: { deterministic: true, fingerprint: "c" }, aggregate: { tracking: { confirmed_coverage: { numerator: 8, denominator: 10, rate: .8, confidence_interval_95: [.49, .94] } }, action: { confusion_matrix: { jump: { spin: 1 } } }, strata: { crossing: { event_count: 2 } } }, failed_events: [{ alias: "event-001", profile: "jump", strata: ["crossing"], failure_codes: ["tracking_wrong_person"] }] });
    render(<GoldenPilotDashboard/>);
    await waitFor(() => expect(screen.getByText(/8\/10/)).toBeInTheDocument());
    expect(screen.getByText(/golden-gate-policy\.v1 \(legacy evidence\)/)).toBeInTheDocument();
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

  it("renders a legacy progress payload without next_actions or policy metadata", async () => {
    progress.mockResolvedValue({
      gate: "G1", status: "waiting_for_owner_labels", diagnostic_only: true, release_claim: false,
      profiles: [], scenes: [], requirements: { event_count: { count: 0, target: 36, passed: false } }, next_best_videos: [],
    } as never);
    render(<GoldenPilotDashboard />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Waiting for owner labels" })).toBeInTheDocument());
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
