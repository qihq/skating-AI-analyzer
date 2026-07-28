import type { MediaManifest, MediaQuality, MediaSource } from "./types";

export function readySources(manifest: MediaManifest | null | undefined): MediaSource[] {
  return (manifest?.sources ?? []).filter((source) => source.status === "ready" && Boolean(source.url));
}

export function selectAutoQuality(manifest: MediaManifest | null | undefined, viewportWidth = window.innerWidth, dpr = window.devicePixelRatio || 1): MediaSource | null {
  const sources = readySources(manifest).sort((left, right) => (right.height ?? 0) - (left.height ?? 0));
  const targetHeight = Math.max(360, Math.min(1080, Math.round((viewportWidth * dpr) * 9 / 16)));
  return sources.find((source) => (source.height ?? 0) >= targetHeight) ?? sources[0] ?? null;
}

export function qualitySource(manifest: MediaManifest | null | undefined, quality: MediaQuality): MediaSource | null {
  if (quality === "auto") return selectAutoQuality(manifest);
  return readySources(manifest).find((source) => source.quality === quality) ?? null;
}
