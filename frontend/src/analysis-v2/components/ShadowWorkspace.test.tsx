import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAppMode } from "../../components/AppModeContext";
import { cleanupShadowRun, createShadowRun, fetchShadowArtifact, fetchShadowDiff, fetchShadowReviewDecisions, fetchShadowRuns, recoverShadowRun } from "../api";
import type { ShadowRunRecord } from "../shadow-contracts";
import ShadowWorkspace from "./ShadowWorkspace";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({
  createShadowRun: vi.fn(), fetchShadowRuns: vi.fn(), fetchShadowDiff: vi.fn(), fetchShadowArtifact: vi.fn(), fetchShadowReviewDecisions: vi.fn(), retryShadowRun: vi.fn(), recoverShadowRun: vi.fn(), cleanupShadowRun: vi.fn(), submitShadowReviewDecision: vi.fn(), addShadowNote: vi.fn(),
}));

const mode = vi.mocked(useAppMode);
const runsApi = vi.mocked(fetchShadowRuns);
const diffApi = vi.mocked(fetchShadowDiff);
const runApi = vi.mocked(createShadowRun);
const recoverApi = vi.mocked(recoverShadowRun);
const cleanupApi = vi.mocked(cleanupShadowRun);
const artifactApi = vi.mocked(fetchShadowArtifact);
const decisionsApi = vi.mocked(fetchShadowReviewDecisions);

function run(): ShadowRunRecord {
  const stages = ["timebase", "observations", "candidates", "identity", "pose", "events", "moments", "rotation", "path_reviews", "claims"] as const;
  return {
    schema_version: "shadow-run.v1", run_id: "shadow-1", analysis_id: "a1", status: "partial", authority: "legacy", diagnostic_only: true,
    pipeline_fingerprint: "pipeline-fp", source_fingerprint: "source-fp", source_video_hash: null, model_fingerprint: "model-fp", config_fingerprint: "config-fp", prompt_fingerprint: null, contract_fingerprint: null,
    created_at: "2026-08-08T00:00:00Z", updated_at: "2026-08-08T00:00:00Z", requested_by: "parent", coalesced: false, retry_from_stage: "pose", first_divergent_stage: null,
    stages: stages.map((stage) => ({ schema_version: "shadow-stage.v1", stage, status: stage === "pose" ? "failed" : "complete", fingerprint: `${stage}-fp`, input_hash: null, output_hash: `${stage}-out`, dependency_hashes: {}, error: stage === "pose" ? "failed" : null, retry_count: 0, updated_at: "2026-08-08T00:00:00Z" })),
    diffs: [], artifacts: [{ schema_version: "shadow-artifact-reference.v1", artifact_id: "pose-artifact", stage: "pose", kind: "stage-output", relative_path: "artifacts/pose.json", fingerprint: "pose-fp", status: "rebuildable", created_at: "2026-08-08T00:00:00Z" }], review_decisions: [], downstream: [{ consumer: "skills/XP", status: "excluded", reason: "shadow", executed: false }], notes: [], error: null,
  };
}

describe("ShadowWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    artifactApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", run_id: "shadow-1", analysis_id: "a1", artifact: run().artifacts[0], content: { schema_version: "shadow-pose-stage.v1", observations: [{ source_frame_index: 3, pts_sec: 0.1, source_method: "legacy_snapshot_adapter" }] } });
    decisionsApi.mockResolvedValue([]);
  });

  it("is locked in child mode and performs no Shadow request", () => {
    mode.mockReturnValue({ isParentMode: false, parentPin: null, enterParentMode: vi.fn() } as never);
    render(<ShadowWorkspace analysisId="a1"/>);
    expect(screen.getByRole("heading", { name: "Shadow 工作台仅家长可见" })).toBeInTheDocument();
    expect(runsApi).not.toHaveBeenCalled();
  });

  it("shows canonical checkpoints, first divergence and dry-run impacts", async () => {
    mode.mockReturnValue({ isParentMode: true, parentPin: "1234", enterParentMode: vi.fn() } as never);
    const record = run();
    runsApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", analysis_id: "a1", runs: [record] });
    diffApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", run_id: "shadow-1", analysis_id: "a1", first_divergent_stage: "identity", stages: [{ schema_version: "shadow-stage-diff.v1", stage: "identity", status: "different", legacy_fingerprint: "l", v2_fingerprint: "v", summary: "identity conflict", details: {}, first_divergent: true }], downstream: record.downstream });
    render(<ShadowWorkspace analysisId="a1"/>);
    await waitFor(() => expect(screen.getAllByText("Identity").length).toBeGreaterThan(0));
    expect(screen.getByText("Candidate coverage")).toBeInTheDocument();
    expect(screen.getByText("Path A/B reviews")).toBeInTheDocument();
    expect(screen.getByText("skills/XP")).toBeInTheDocument();
    expect(screen.getByText("pose-artifact")).toBeInTheDocument();
    expect(screen.getByText("G11 fixed-fingerprint repeatability")).toBeInTheDocument();
    expect(screen.getAllByText("unavailable").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "恢复 / 从首个无效 stage 继续" })).toBeEnabled();
    expect(screen.getAllByText("legacy").length).toBeGreaterThan(0);
    await waitFor(() => expect(decisionsApi).toHaveBeenCalledWith("1234", "shadow-1"));
  });

  it("requires an explicit parent action for recovery and cleanup", async () => {
    mode.mockReturnValue({ isParentMode: true, parentPin: "1234", enterParentMode: vi.fn() } as never);
    const record = run();
    runsApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", analysis_id: "a1", runs: [record] });
    diffApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", run_id: "shadow-1", analysis_id: "a1", first_divergent_stage: null, stages: [], downstream: [] });
    recoverApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", run: record });
    cleanupApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", run_id: "shadow-1", removed: ["artifacts/pose.json"], retained: ["run.json", "audit.jsonl", "source", "golden", "reviews", "corrections"] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ShadowWorkspace analysisId="a1"/>);
    await screen.findByText("pose-artifact");
    fireEvent.click(screen.getByRole("button", { name: "恢复 / 从首个无效 stage 继续" }));
    await waitFor(() => expect(recoverApi).toHaveBeenCalledWith("1234", "shadow-1"));
    fireEvent.click(screen.getByRole("button", { name: "清理可重建 artifacts" }));
    await waitFor(() => expect(cleanupApi).toHaveBeenCalledWith("1234", "shadow-1"));
  });

  it("starts Shadow only after an explicit parent action", async () => {
    mode.mockReturnValue({ isParentMode: true, parentPin: "1234", enterParentMode: vi.fn() } as never);
    runsApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", analysis_id: "a1", runs: [] });
    const record = run();
    runApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", run: record });
    diffApi.mockResolvedValue({ schema_version: "shadow-orchestration.v1", run_id: "shadow-1", analysis_id: "a1", first_divergent_stage: null, stages: [], downstream: [] });
    render(<ShadowWorkspace/>);
    fireEvent.change(screen.getByPlaceholderText("输入已 Golden 的 analysis id"), { target: { value: "a1" } });
    fireEvent.click(screen.getByRole("button", { name: "运行 / 合并 Shadow" }));
    await waitFor(() => expect(runApi).toHaveBeenCalledWith("1234", expect.objectContaining({ analysis_id: "a1" })));
  });
});
