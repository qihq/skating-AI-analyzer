import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateProvider,
  createProvider,
  deleteProvider,
  fetchProviders,
  fetchVisionVoteConfig,
  testProvider,
  updateProvider,
  updateVisionVoteConfig,
} from "../api/client";
import { useAppMode } from "../components/AppModeContext";
import type { ProviderPublic, VisionVoteConfig } from "../api/client";
import ApiSettingsPage from "./ApiSettingsPage";

vi.mock("../components/AppModeContext", () => ({
  useAppMode: vi.fn(),
}));

vi.mock("../api/client", () => ({
  activateProvider: vi.fn(),
  createProvider: vi.fn(),
  deleteProvider: vi.fn(),
  fetchProviders: vi.fn(),
  fetchVisionVoteConfig: vi.fn(),
  testProvider: vi.fn(),
  updateProvider: vi.fn(),
  updateVisionVoteConfig: vi.fn(),
}));

const voteConfig: VisionVoteConfig = {
  primary_provider_id: "vision-active",
  secondary_provider_id: "vision-inactive",
  scope: "legacy_vision_only",
  applies_to_v2_fusion: false,
};

function makeProvider(overrides: Partial<ProviderPublic> = {}): ProviderPublic {
  return {
    id: "report-active",
    slot: "report",
    name: "Qwen report",
    provider: "qwen",
    base_url: "https://example.test/v1",
    model_id: "qwen3.6-plus",
    vision_model: null,
    api_key: "***",
    is_active: true,
    notes: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    v2_role: "report",
    fingerprint: "provider-fingerprint",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ApiSettingsPage />
    </MemoryRouter>,
  );
}

describe("ApiSettingsPage provider deletion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAppMode).mockReturnValue({
      isParentMode: true,
      parentPin: "1234",
      enterParentMode: vi.fn(),
    } as never);
    vi.mocked(fetchProviders).mockResolvedValue([makeProvider(), makeProvider({
      id: "report-secondary",
      name: "DeepSeek report",
      provider: "deepseek",
      model_id: "deepseek-chat",
      is_active: false,
      created_at: "2026-08-02T00:00:00Z",
    })]);
    vi.mocked(fetchVisionVoteConfig).mockResolvedValue(voteConfig);
    vi.mocked(deleteProvider).mockResolvedValue(undefined);
    vi.mocked(activateProvider).mockResolvedValue(makeProvider());
    vi.mocked(createProvider).mockResolvedValue(makeProvider());
    vi.mocked(testProvider).mockResolvedValue({ success: true, detail: "ok" });
    vi.mocked(updateProvider).mockResolvedValue(makeProvider());
    vi.mocked(updateVisionVoteConfig).mockResolvedValue(voteConfig);
  });

  it("does not expose provider deletion while in child mode", () => {
    vi.mocked(useAppMode).mockReturnValue({
      isParentMode: false,
      parentPin: null,
      enterParentMode: vi.fn(),
    } as never);

    renderPage();

    expect(screen.getByRole("button", { name: "进入家长模式" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /删除/ })).not.toBeInTheDocument();
  });

  it("confirms deletion, sends the parent PIN, and refreshes providers", async () => {
    const remaining = makeProvider({ id: "report-secondary", name: "DeepSeek report", provider: "deepseek", model_id: "deepseek-chat", is_active: false });
    vi.mocked(fetchProviders).mockResolvedValue([makeProvider(), remaining]);

    renderPage();
    await screen.findByRole("heading", { name: /Qwen \/ qwen3\.6-plus/ });
    vi.mocked(fetchProviders).mockResolvedValue([remaining]);
    fireEvent.click(screen.getByRole("button", { name: /删除 Qwen qwen3.6-plus/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("删除模型实例？");

    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(deleteProvider).toHaveBeenCalledWith("report-active", "1234"));
    await waitFor(() => expect(fetchProviders).toHaveBeenLastCalledWith("1234"));
    expect(await screen.findByRole("heading", { name: "DeepSeek" })).toBeInTheDocument();
    expect(screen.getByText("模型 ID：deepseek-chat")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Qwen" })).not.toBeInTheDocument();
    expect(screen.getByText("Qwen / qwen3.6-plus 已删除。")).toBeInTheDocument();
  });

  it("surfaces the backend rejection when deleting the only active provider", async () => {
    const detail = "不可删除该 slot 唯一的激活供应商。";
    vi.mocked(deleteProvider).mockRejectedValue({
      isAxiosError: true,
      response: { data: { detail } },
    });

    renderPage();
    await screen.findByRole("heading", { name: /Qwen \/ qwen3\.6-plus/ });
    fireEvent.click(screen.getByRole("button", { name: /删除 Qwen qwen3.6-plus/ }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByText(detail)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Qwen \/ qwen3\.6-plus/ })).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("disables confirmation while deletion is pending", async () => {
    let resolveDelete!: () => void;
    vi.mocked(deleteProvider).mockImplementation(() => new Promise<void>((resolve) => {
      resolveDelete = resolve;
    }));

    renderPage();
    await screen.findByRole("heading", { name: /Qwen \/ qwen3\.6-plus/ });
    fireEvent.click(screen.getByRole("button", { name: /删除 Qwen qwen3.6-plus/ }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    const confirmButton = await screen.findByRole("button", { name: "删除中..." });
    expect(confirmButton).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();

    resolveDelete();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
