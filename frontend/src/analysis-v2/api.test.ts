import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import {
  cleanupShadowRun,
  fetchShadowArtifact,
  fetchShadowArtifacts,
  fetchShadowCapabilities,
  fetchShadowReviewDecisions,
  recoverShadowRun,
  updateShadowFingerprints,
} from "./api";

describe("Shadow API parent authorization", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("uses the isolated Shadow endpoints and parent PIN for lifecycle reads/writes", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: {} } as never);
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} } as never);

    await fetchShadowCapabilities("1234");
    await fetchShadowArtifacts("1234", "run/unsafe");
    await fetchShadowArtifact("1234", "run/unsafe", "artifact/unsafe");
    await fetchShadowReviewDecisions("1234", "run/unsafe");
    await recoverShadowRun("1234", "run/unsafe");
    await cleanupShadowRun("1234", "run/unsafe");
    await updateShadowFingerprints("1234", "run/unsafe", {
      config_fingerprint: "config-v2",
      confirmation: "confirm_shadow_fingerprint_update",
    });

    expect(get.mock.calls.map(([path]) => path)).toEqual([
      "/shadow/capabilities",
      "/shadow/runs/run%2Funsafe/artifacts",
      "/shadow/runs/run%2Funsafe/artifacts/artifact%2Funsafe",
      "/shadow/runs/run%2Funsafe/review-decisions",
    ]);
    expect(post.mock.calls.map(([path]) => path)).toEqual([
      "/shadow/runs/run%2Funsafe/recover",
      "/shadow/runs/run%2Funsafe/cleanup",
      "/shadow/runs/run%2Funsafe/fingerprints",
    ]);
    for (const call of [...get.mock.calls, ...post.mock.calls]) {
      const config = (call[2] ?? call[1]) as { headers?: Record<string, string> } | undefined;
      expect(config?.headers?.["X-Parent-Pin"]).toBe("1234");
    }
  });
});
