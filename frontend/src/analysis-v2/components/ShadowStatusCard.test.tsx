import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAppMode } from "../../components/AppModeContext";
import { fetchAdvancedRuntimeCapabilities } from "../api";
import ShadowStatusCard from "./ShadowStatusCard";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({ fetchAdvancedRuntimeCapabilities: vi.fn() }));

const mockedMode = vi.mocked(useAppMode);
const mockedFetch = vi.mocked(fetchAdvancedRuntimeCapabilities);

function mode(overrides: Record<string, unknown> = {}) {
  return {
    mode: "child",
    isParentMode: false,
    childView: "tantan",
    hasPin: true,
    pinLength: 4,
    parentPin: null,
    openParentDialog: vi.fn(),
    setChildView: vi.fn(),
    switchToChildView: vi.fn(),
    switchToChildMode: vi.fn(),
    enterParentMode: vi.fn().mockResolvedValue(undefined),
    activateParentMode: vi.fn(),
    refreshPinState: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as ReturnType<typeof useAppMode>;
}

describe("ShadowStatusCard", () => {
  it("keeps child mode locked without requesting private status", () => {
    mockedMode.mockReturnValue(mode());
    render(<ShadowStatusCard />);
    expect(screen.getByRole("heading", { name: "Shadow 状态仅家长可见" })).toBeInTheDocument();
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("requires an in-memory verified PIN even when parent mode was persisted", () => {
    mockedMode.mockReturnValue(mode({ isParentMode: true }));
    render(<ShadowStatusCard />);
    expect(screen.getByRole("heading", { name: "请重新验证家长 PIN" })).toBeInTheDocument();
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("renders the honest ready no-op state", async () => {
    mockedMode.mockReturnValue(mode({ isParentMode: true, parentPin: "1234" }));
    mockedFetch.mockResolvedValue({
      schema_version: "advanced-runtime-capabilities.v1",
      runtime_mode: "shadow",
      public_authority: "legacy",
      shadow_status: "ready",
      shadow_execution: "noop",
      writes_user_data: false,
      isolated_runtime: true,
      baseline_source_commit: "c291324c62bcc930f96f3429dcdc9521e060b516",
    });
    render(<ShadowStatusCard />);
    expect(screen.getByText("正在读取 Shadow 状态…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "准备就绪" })).toBeInTheDocument());
    expect(screen.getByText("Iteration 0 no-op")).toBeInTheDocument();
    expect(screen.getByText("无")).toBeInTheDocument();
    expect(screen.getByText("Legacy")).toBeInTheDocument();
  });

  it("announces API failures without showing a false status", async () => {
    mockedMode.mockReturnValue(mode({ isParentMode: true, parentPin: "1234" }));
    mockedFetch.mockRejectedValue(new Error("offline"));
    render(<ShadowStatusCard />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "状态暂不可用" })).toBeInTheDocument();
  });
});
