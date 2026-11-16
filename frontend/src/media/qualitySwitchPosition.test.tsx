import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useMediaController } from "./useMediaController";
import { VideoSurface } from "./VideoSurface";
import type { MediaManifest } from "./types";

type Controller = ReturnType<typeof useMediaController>;

const manifest: MediaManifest = { schema_version: "analysis_media.v1", status: "ready", sources: [
  { quality: "original", status: "ready", width: 720, height: 1280, url: "/api/analysis/synthetic/video?quality=original", filename: "source.mov", error: null },
  { quality: "1080p", status: "ready", width: 608, height: 1080, url: "/api/analysis/synthetic/video?quality=1080p", filename: "1080p.mp4", error: null },
  { quality: "720p", status: "ready", width: 406, height: 720, url: "/api/analysis/synthetic/video?quality=720p", filename: "720p.mp4", error: null },
  { quality: "480p", status: "ready", width: 270, height: 480, url: "/api/analysis/synthetic/video?quality=480p", filename: "480p.mp4", error: null },
] };

/**
 * JSDOM stand-in for the browser media pipeline: every src attribute update starts one load, resets currentTime to 0,
 * then reports metadata (or a media error). This is a test double, not a real browser run.
 */
function installMediaStandIn(video: HTMLVideoElement, failingUrls: string[] = []) {
  const events: string[] = [];
  let currentTime = 0;
  let readyState = 0;
  let playing = false;
  Object.defineProperty(video, "currentTime", { configurable: true, get: () => currentTime, set: (value: number) => { currentTime = value; } });
  Object.defineProperty(video, "duration", { configurable: true, get: () => 8 });
  Object.defineProperty(video, "readyState", { configurable: true, get: () => readyState });
  Object.defineProperty(video, "paused", { configurable: true, get: () => !playing });
  const descriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "src");
  if (!descriptor?.get || !descriptor.set) throw new Error("JSDOM does not expose the media src reflection this stand-in needs");
  const startLoad = () => {
    const url = video.getAttribute("src") ?? "";
    events.push(`load:${url}`);
    currentTime = 0;
    playing = false;
    readyState = 1;
    events.push(`reset:${currentTime}`);
    queueMicrotask(() => {
      if (failingUrls.includes(url)) { events.push(`error:${url}`); video.dispatchEvent(new Event("error")); }
      else video.dispatchEvent(new Event("loadedmetadata"));
      events.push(`after:${currentTime}`);
    });
  };
  Object.defineProperty(video, "src", { configurable: true, get: () => descriptor.get!.call(video), set: (value: string) => { descriptor.set!.call(video, value); startLoad(); } });
  video.setAttribute = (name: string, value: string) => {
    Element.prototype.setAttribute.call(video, name, value);
    if (name === "src") startLoad();
  };
  vi.spyOn(video, "play").mockImplementation(() => { playing = true; return Promise.resolve(); });
  vi.spyOn(video, "load").mockImplementation(startLoad);
  return { events, setPlaying: (value: boolean) => { playing = value; } };
}

function renderPlayer(failingUrls: string[] = []) {
  const holder: { controller?: Controller } = {};
  function Fixture() { const controller = useMediaController(manifest); holder.controller = controller; return <VideoSurface controller={controller} manifest={manifest} />; }
  render(<Fixture />);
  const video = screen.getByLabelText("分析视频") as HTMLVideoElement;
  return { video, get controller(): Controller { return holder.controller as Controller; }, ...installMediaStandIn(video, failingUrls) };
}

describe("quality switch keeps the playback position", () => {
  it("applies one DOM source update and restores the paused position after metadata", async () => {
    const player = renderPlayer();
    expect(player.video.getAttribute("src")).toBe("/api/analysis/synthetic/video?quality=720p");
    act(() => player.controller.commitSeek(2));
    player.video.currentTime = 3.5;

    await act(async () => { void player.controller.setQuality("480p"); });

    expect(player.video.getAttribute("src")).toBe("/api/analysis/synthetic/video?quality=480p");
    expect(player.events).toEqual([
      "load:/api/analysis/synthetic/video?quality=480p",
      "reset:0",
      "after:3.5",
    ]);
    expect(player.video.currentTime).toBe(3.5);
    expect(player.video.paused).toBe(true);
    expect(player.controller.state.quality).toBe("480p");
    expect(player.controller.state.buffering).toBe(false);
  });

  it("keeps the position and playing state across 720p → 480p → 1080p → 720p", async () => {
    const player = renderPlayer();
    player.setPlaying(true);
    player.video.currentTime = 3.5;
    const play = vi.spyOn(player.video, "play");

    for (const quality of ["480p", "1080p", "720p"] as const) {
      await act(async () => { void player.controller.setQuality(quality); });
      expect(player.video.getAttribute("src")).toBe(`/api/analysis/synthetic/video?quality=${quality}`);
      expect(player.video.currentTime).toBe(3.5);
      expect(player.video.paused).toBe(false);
    }

    expect(play).toHaveBeenCalledTimes(3);
    expect(player.events.filter((event) => event.startsWith("load:"))).toEqual([
      "load:/api/analysis/synthetic/video?quality=480p",
      "load:/api/analysis/synthetic/video?quality=1080p",
      "load:/api/analysis/synthetic/video?quality=720p",
    ]);
  });

  it("restores the previous quality, source and position when the new source fails", async () => {
    const player = renderPlayer(["/api/analysis/synthetic/video?quality=480p"]);
    player.video.currentTime = 3.5;
    player.setPlaying(true);

    await act(async () => { void player.controller.setQuality("480p"); });

    expect(player.video.paused).toBe(false);
    expect(player.video.getAttribute("src")).toBe("/api/analysis/synthetic/video?quality=720p");
    expect(player.video.currentTime).toBe(3.5);
    expect(player.controller.state.quality).toBe("auto");
    expect(player.controller.state.error).toBe("清晰度切换失败，已恢复视频");
    expect(player.controller.state.buffering).toBe(false);
    expect(player.events).toEqual([
      "load:/api/analysis/synthetic/video?quality=480p",
      "reset:0",
      "error:/api/analysis/synthetic/video?quality=480p",
      "after:0",
      "load:/api/analysis/synthetic/video?quality=720p",
      "reset:0",
      "after:3.5",
    ]);
  });
});
