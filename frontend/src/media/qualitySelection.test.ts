import { describe, expect, it } from "vitest";
import { qualitySource } from "./qualitySelection";
import type { MediaManifest } from "./types";

const manifest: MediaManifest = { schema_version: "analysis_media.v1", status: "ready", sources: [
  { quality: "original", status: "ready", width: 1920, height: 1080, url: "original", filename: "source.mp4", error: null },
  { quality: "720p", status: "ready", width: 1280, height: 720, url: "720", filename: "720.mp4", error: null },
] };

describe("qualitySource", () => {
  it("keeps manual choices pinned and returns null for unavailable choices", () => {
    expect(qualitySource(manifest, "720p")?.url).toBe("720");
    expect(qualitySource(manifest, "480p")).toBeNull();
  });
});
