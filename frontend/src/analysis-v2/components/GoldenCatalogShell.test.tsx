import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAppMode } from "../../components/AppModeContext";
import { fetchGoldenCatalog, fetchGoldenSanitizedExport, fetchGoldenSchema } from "../api";
import GoldenCatalogShell from "./GoldenCatalogShell";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({ fetchGoldenCatalog: vi.fn(), fetchGoldenSchema: vi.fn(), fetchGoldenSanitizedExport: vi.fn() }));
vi.mock("./GoldenPilotDashboard", () => ({ default: () => <div>Golden pilot dashboard</div> }));

const mode = vi.mocked(useAppMode);
const catalog = vi.mocked(fetchGoldenCatalog);
const schema = vi.mocked(fetchGoldenSchema);
const exportData = vi.mocked(fetchGoldenSanitizedExport);

function appMode(parent = false) {
  return { isParentMode: parent, parentPin: parent ? "1234" : null, enterParentMode: vi.fn().mockResolvedValue(undefined) } as unknown as ReturnType<typeof useAppMode>;
}

function mockCatalog(status: "empty" | "ready" | "invalid-source" | "schema-incompatible" = "empty", duplicates: string[] = []) {
  mode.mockReturnValue(appMode(true));
  catalog.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", schema_version: "golden-dataset.v2", revision: 1, status, source_count: 0, event_count: 0, profile_counts: [], observability_counts: [], strata_counts: [], duplicate_sources: duplicates });
  schema.mockResolvedValue({ schema_version: "golden-dataset.v2", supported_schema_versions: ["golden-dataset.v2"], migration_policy: "future-v2-only", historical_debug_pool: "not-imported" });
  exportData.mockResolvedValue({ schema_version: "golden-sanitized-summary.v1", dataset_id: "golden-v2-private-catalog", golden_schema_version: "golden-dataset.v2", revision: 1, aggregate: { source_count: 0, event_count: 0, profile_counts: [], observability_counts: [], strata_counts: [] }, redacted_aliases: [], gate_template: { gate: "G1", status: "not-run", required_new_events: 36 } });
}

describe("GoldenCatalogShell", () => {
  it("keeps the private catalog locked for child mode", () => {
    mode.mockReturnValue(appMode(false));
    render(<GoldenCatalogShell />);
    expect(screen.getByRole("heading", { name: "Golden 目录仅家长可见" })).toBeInTheDocument();
    expect(catalog).not.toHaveBeenCalled();
  });

  it("renders the private empty manifest without historic fallback", async () => {
    mockCatalog();
    render(<GoldenCatalogShell />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "等待新的评测事件" })).toBeInTheDocument());
    expect(screen.getByText(/尚未导入视频、人工标注或运行 G1/)).toBeInTheDocument();
  });

  it("renders a parent diagnostic for duplicate sources", async () => {
    mockCatalog("ready", ["near-duplicate:source-001"]);
    render(<GoldenCatalogShell />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "发现需要复核的相近素材" })).toBeInTheDocument());
    screen.getByRole("button", { name: "查看家长诊断" }).click();
    await waitFor(() => expect(screen.getByText(/near-duplicate:source-001/)).toBeInTheDocument());
  });

  it("renders schema incompatibility without a legacy fallback", async () => {
    mockCatalog("schema-incompatible");
    render(<GoldenCatalogShell />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "目录版本需要处理" })).toBeInTheDocument());
    expect(screen.getByText(/不会静默丢弃字段或读取旧 debug Golden/)).toBeInTheDocument();
  });

  it("announces an authorization or transport error", async () => {
    mode.mockReturnValue(appMode(true));
    catalog.mockRejectedValue(new Error("offline")); schema.mockResolvedValue({} as never); exportData.mockResolvedValue({} as never);
    render(<GoldenCatalogShell />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
