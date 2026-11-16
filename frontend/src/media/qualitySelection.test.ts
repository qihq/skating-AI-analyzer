import { describe, expect, it } from "vitest";
import { availableQualities, qualitySource, selectAutoQuality } from "./qualitySelection";
import type { MediaManifest, MediaSource } from "./types";

const manifest: MediaManifest = { schema_version: "analysis_media.v1", status: "ready", sources: [
  { quality: "original", status: "ready", width: 1920, height: 1080, url: "original", filename: "source.mp4", error: null },
  { quality: "720p", status: "ready", width: 1280, height: 720, url: "720", filename: "720.mp4", error: null },
] };

function source(quality: MediaSource["quality"], status: string, url: string | null, height: number | null): MediaSource {
  return { quality, status, width: height == null ? null : Math.round(height * 16 / 9), height, url, filename: null, error: status === "failed" ? "transcode failed" : null };
}
function manifestOf(sources: MediaSource[]): MediaManifest {
  return { schema_version: "analysis_media.v1", status: "ready", sources };
}

const transcoded = manifestOf([
  source("original", "ready", "original", 1080),
  source("1080p", "ready", "/1080", 1080),
  source("720p", "ready", "/720", 720),
  source("480p", "ready", "/480", 480),
]);

describe("qualitySource", () => {
  it("keeps manual choices pinned and returns null for unavailable choices", () => {
    expect(qualitySource(manifest, "720p")?.url).toBe("720");
    expect(qualitySource(manifest, "480p")).toBeNull();
  });

  it("keeps a ready original manually selectable while a transcode is playing", () => {
    expect(qualitySource(transcoded, "original")?.url).toBe("original");
    expect(qualitySource(transcoded, "auto")?.quality).not.toBe("original");
  });
});

describe("selectAutoQuality", () => {
  it("picks the smallest ready transcode that covers the display height instead of the original", () => {
    expect(selectAutoQuality(transcoded, 1280, 1)?.url).toBe("/720");
  });

  it("prefers a ready transcode over a larger original when none covers the display height", () => {
    const small = manifestOf([source("original", "ready", "original", 1080), source("720p", "ready", "/720", 720), source("480p", "ready", "/480", 480)]);
    expect(selectAutoQuality(small, 1920, 2)?.url).toBe("/720");
    const tiny = manifestOf([source("original", "ready", "original", 1080), source("480p", "ready", "/480", 480)]);
    expect(selectAutoQuality(tiny, 1280, 1)?.url).toBe("/480");
  });

  it("falls back to the original only when no transcode is ready", () => {
    const pendingTranscodes = manifestOf([source("original", "ready", "original", 1080), source("720p", "pending", null, 720), source("480p", "failed", "/480", 480)]);
    expect(selectAutoQuality(pendingTranscodes, 1280, 1)?.url).toBe("original");
    expect(selectAutoQuality(manifestOf([source("720p", "processing", null, 720)]), 1280, 1)).toBeNull();
  });
});

describe("availableQualities", () => {
  it("offers Auto plus every ready quality and excludes pending or failed ones", () => {
    expect(availableQualities(transcoded)).toEqual(["auto", "original", "1080p", "720p", "480p"]);
    const pendingTranscodes = manifestOf([source("original", "ready", "original", 1080), source("720p", "pending", null, 720), source("480p", "failed", "/480", 480)]);
    expect(availableQualities(pendingTranscodes)).toEqual(["auto", "original"]);
    expect(availableQualities(null)).toEqual(["auto"]);
  });
});
