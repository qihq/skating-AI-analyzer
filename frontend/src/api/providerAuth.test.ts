import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  activateProvider,
  apiClient,
  createProvider,
  deleteProvider,
  fetchProviderMetrics,
  fetchProviders,
  fetchVisionVoteConfig,
  testProvider,
  updateProvider,
  updateVisionVoteConfig,
} from "./client";

describe("provider API parent-PIN boundary", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("sends X-Parent-Pin for every sensitive provider read/write", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [] } as never);
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { success: true, detail: "ok" } } as never);
    const put = vi.spyOn(apiClient, "put").mockResolvedValue({ data: { primary_provider_id: null, secondary_provider_id: null } } as never);
    const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({ data: { id: "provider-1" } } as never);
    const remove = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: undefined } as never);
    const pin = "1234";

    await fetchProviders(pin);
    await fetchVisionVoteConfig(pin);
    await fetchProviderMetrics(pin);
    await updateVisionVoteConfig({ primary_provider_id: null, secondary_provider_id: null, scope: "legacy_vision_only", applies_to_v2_fusion: false }, pin);
    await createProvider({ slot: "report", name: "Report", provider: "qwen", base_url: "https://example.test", model_id: "m", api_key: "secret" }, pin);
    await activateProvider("provider-1", pin);
    await updateProvider("provider-1", { model_id: "m2" }, pin);
    await testProvider("provider-1", pin);
    await deleteProvider("provider-1", pin);

    for (const call of [...get.mock.calls, ...post.mock.calls, ...put.mock.calls, ...patch.mock.calls, ...remove.mock.calls]) {
      const config = (call[2] ?? call[1]) as { headers?: Record<string, string> } | undefined;
      expect(config?.headers?.["X-Parent-Pin"]).toBe(pin);
    }
  });

  it("sends X-Parent-Pin for auto-eval snapshots", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: [] } as never);
    await import("./client").then(({ fetchAutoEvalSnapshots }) => fetchAutoEvalSnapshots("1234", { limit: 3 }));
    const lastCall = get.mock.calls[get.mock.calls.length - 1];
    expect(lastCall?.[1]).toMatchObject({ headers: { "X-Parent-Pin": "1234" } });
  });
});
