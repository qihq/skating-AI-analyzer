import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useMediaController } from "./useMediaController";

describe("useMediaController", () => {
  it("keeps preview seeking separate until committed", () => {
    const { result } = renderHook(() => useMediaController(null));
    act(() => result.current.previewSeek(4.2));
    expect(result.current.state.previewTime).toBe(4.2);
    act(() => result.current.commitSeek(4.2));
    expect(result.current.state.currentTime).toBe(4.2);
    expect(result.current.state.previewTime).toBeNull();
  });
});

const manifest = { schema_version: "media.v1", status: "ready", sources: [
  { quality: "480p", height: 480, status: "ready", url: "/small.mp4" },
  { quality: "720p", height: 720, status: "ready", url: "/large.mp4" },
  { quality: "original", height: 1280, status: "ready", url: "/original.mp4" },
] } as import("./types").MediaManifest;

// Model the browser resetting playback on each React-owned source assignment.
function harness(initialManifest: typeof manifest | null = manifest) {
  const hook = renderHook(({ media }) => useMediaController(media), { initialProps: { media: initialManifest } });
  const video = document.createElement("video");
  Object.defineProperties(video, {
    duration: { value: 29, configurable: true },
    paused: { value: true, writable: true, configurable: true },
  });
  video.play = vi.fn(async () => { Object.defineProperty(video, "paused", { value: false, writable: true }); });
  act(() => hook.result.current.bindVideo(video));
  const load = () => {
    video.setAttribute("src", hook.result.current.source!.url!);
    video.currentTime = 0; video.volume = 1; video.playbackRate = 1;
    act(() => hook.result.current.mediaProps.onLoadedMetadata());
  };
  if (initialManifest) load();
  return { ...hook, video, load };
}

describe("quality recovery snapshots", () => {
  it("recovers using a manifest loaded after the controller mounts", async () => {
    vi.stubGlobal("innerWidth", 1440);
    const h = harness(null);
    h.rerender({ media: manifest }); h.load();
    h.video.currentTime = 7.37;
    await act(() => h.result.current.setQuality("original"));
    h.video.setAttribute("src", h.result.current.source!.url!);
    vi.stubGlobal("innerWidth", 600);
    act(() => h.result.current.mediaProps.onError());
    expect(h.result.current.source?.url).toBe("/small.mp4");
    h.load();
    expect(h.video.currentTime).toBe(7.37);
    expect(h.result.current.state.error).toContain("已恢复视频");
    h.unmount(); vi.unstubAllGlobals();
  });
  it.each([
    ["auto", 1440, 600, true], ["auto", 1440, 600, false], ["auto", 1440, 1440, false],
    ["480p", 1440, 600, true], ["720p", 1440, 600, false],
  ] as const)("restores %s across viewport %s -> %s (paused=%s)", async (quality, before, after, paused) => {
    vi.stubGlobal("innerWidth", before);
    const h = harness();
    if (quality !== "auto") { await act(() => h.result.current.setQuality(quality)); h.load(); }
    h.video.currentTime = 7.37; h.video.volume = .31; h.video.muted = true; h.video.playbackRate = 1.25;
    Object.defineProperty(h.video, "paused", { value: paused, writable: true });
    await act(() => h.result.current.setQuality("original"));
    h.video.setAttribute("src", h.result.current.source!.url!);
    vi.stubGlobal("innerWidth", after);
    act(() => h.result.current.mediaProps.onError());
    const fallback = h.result.current.source!.url;
    h.load();
    expect(fallback).toBe(quality === "480p" || quality === "auto" && after === 600 ? "/small.mp4" : "/large.mp4");
    expect(h.video.currentTime).toBe(7.37);
    expect(h.video.volume).toBe(.31); expect(h.video.muted).toBe(true); expect(h.video.playbackRate).toBe(1.25);
    expect(h.video.play).toHaveBeenCalledTimes(paused ? 0 : 1);
    act(() => h.result.current.mediaProps.onTimeUpdate());
    expect(h.result.current.state.currentTime).toBe(7.37);
    expect(h.result.current.state.buffering).toBe(false);
    h.unmount(); vi.unstubAllGlobals();
  });
  it("does not consume a newer switch snapshot on stale metadata", async () => {
    vi.stubGlobal("innerWidth", 1440);
    const h = harness(); h.video.currentTime = 11.4;
    await act(() => h.result.current.setQuality("original"));
    await act(() => h.result.current.setQuality("480p"));
    h.video.setAttribute("src", "/original.mp4");
    act(() => h.result.current.mediaProps.onLoadedMetadata());
    act(() => h.result.current.mediaProps.onError());
    expect(h.result.current.state.quality).toBe("480p");
    h.load(); expect(h.video.currentTime).toBe(11.4);
    expect(h.result.current.source?.url).toBe("/small.mp4");
    h.unmount(); vi.unstubAllGlobals();
  });
});
