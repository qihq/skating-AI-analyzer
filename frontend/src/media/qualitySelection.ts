import type { MediaManifest, MediaQuality, MediaSource } from "./types";

const QUALITY_ORDER: Exclude<MediaQuality, "auto">[] = ["original", "1080p", "720p", "480p"];

export function readySources(manifest: MediaManifest | null | undefined): MediaSource[] {
  return (manifest?.sources ?? []).filter((source) => source.status === "ready" && Boolean(source.url));
}

/** "Auto" plus every quality the manifest reports as ready with a URL; pending/failed entries are never selectable. */
export function availableQualities(manifest: MediaManifest | null | undefined): MediaQuality[] {
  const ready = readySources(manifest);
  const selectable = new Set(ready.map((source) => source.quality));
  const known = QUALITY_ORDER.filter((quality) => selectable.has(quality));
  return ["auto", ...known];
}

/**
 * Auto keeps the smallest ready transcode that still covers the display height, falls back to the largest
 * available transcode when none covers it, and only uses the original when no ready transcode exists.
 * The original may report metadata yet fail to play/seek in Chromium, so it is never preferred over a transcode.
 */
export function selectAutoQuality(manifest: MediaManifest | null | undefined, viewportWidth = window.innerWidth, dpr = window.devicePixelRatio || 1): MediaSource | null {
  const sources = readySources(manifest);
  const transcodes = sources.filter((source) => source.quality !== "original");
  const candidates = transcodes.length > 0 ? transcodes : sources;
  if (candidates.length === 0) return null;
  const targetHeight = Math.max(360, Math.min(1080, Math.round((viewportWidth * dpr) * 9 / 16)));
  const covering = candidates.filter((source) => (source.height ?? 0) >= targetHeight).sort((left, right) => (left.height ?? 0) - (right.height ?? 0));
  if (covering.length > 0) return covering[0];
  return candidates.reduce((largest, source) => (source.height ?? 0) > (largest.height ?? 0) ? source : largest);
}

export function qualitySource(manifest: MediaManifest | null | undefined, quality: MediaQuality): MediaSource | null {
  if (quality === "auto") return selectAutoQuality(manifest);
  return readySources(manifest).find((source) => source.quality === quality) ?? null;
}
