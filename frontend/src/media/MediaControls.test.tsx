import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MediaControls } from "./MediaControls";
import { useMediaController } from "./useMediaController";
import type { MediaManifest } from "./types";

describe("MediaControls", () => {
  it("keeps marker jumps directly accessible", () => {
    const controller = { state: { duration: 8, currentTime: 0, previewTime: null, buffered: [], paused: true, buffering: false, muted: false, playbackRate: 1, quality: "auto", isFullscreen: false, isPictureInPicture: false, volume: 1, error: null }, source: null, availableQualities: ["auto", "original"], togglePlay: vi.fn(), commitSeek: vi.fn(), previewSeek: vi.fn(), setMuted: vi.fn(), setPlaybackRate: vi.fn(), setQuality: vi.fn() } as never;
    render(<MediaControls controller={controller} markers={[{ id: "T", label: "T", timestamp: 2 }]} />);
    expect(screen.getByRole("button", { name: "跳到T" })).toBeInTheDocument();
  });

  it("exposes source-frame stepping and exact PTS identity", () => {
    const controller = { state: { duration: 8, currentTime: 0, previewTime: null, buffered: [], paused: true, buffering: false, muted: false, playbackRate: 1, quality: "auto", isFullscreen: false, isPictureInPicture: false, volume: 1, error: null }, source: null, availableQualities: ["auto", "original"], togglePlay: vi.fn(), commitSeek: vi.fn(), previewSeek: vi.fn(), setMuted: vi.fn(), setPlaybackRate: vi.fn(), setQuality: vi.fn() } as never;
    render(<MediaControls controller={controller} sourceFrame={{ sourceFrameIndex: 12, pts: .4, duration: .033 }} onStepSourceFrame={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Next source frame" })).toBeInTheDocument();
    expect(screen.getByText(/PTS 0.400000/)).toBeInTheDocument();
  });

  it("uses unclipped native selectors for playback speed and quality", () => {
    const setPlaybackRate = vi.fn();
    const setQuality = vi.fn();
    const controller = { state: { duration: 8, currentTime: 0, previewTime: null, buffered: [], paused: true, buffering: false, muted: false, playbackRate: 1, quality: "auto", isFullscreen: false, isPictureInPicture: false, volume: 1, error: null }, source: null, availableQualities: ["auto", "original"], togglePlay: vi.fn(), commitSeek: vi.fn(), previewSeek: vi.fn(), setMuted: vi.fn(), setPlaybackRate, setQuality } as never;
    render(<MediaControls controller={controller} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Playback speed" }), { target: { value: "1.5" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Video quality" }), { target: { value: "original" } });

    expect(setPlaybackRate).toHaveBeenCalledWith(1.5);
    expect(setQuality).toHaveBeenCalledWith("original");
  });

  it("lists Auto plus every ready manifest quality", () => {
    const manifest: MediaManifest = { schema_version: "analysis_media.v1", status: "ready", sources: [
      { quality: "original", status: "ready", width: 720, height: 1280, url: "/original", filename: "source.mov", error: null },
      { quality: "1080p", status: "ready", width: 1080, height: 1920, url: "/1080", filename: "1080.mp4", error: null },
      { quality: "720p", status: "ready", width: 720, height: 1280, url: "/720", filename: "720.mp4", error: null },
      { quality: "480p", status: "pending", width: null, height: null, url: null, filename: null, error: null },
    ] };
    function Fixture() { const controller = useMediaController(manifest); return <MediaControls controller={controller} />; }
    render(<Fixture />);

    const select = screen.getByRole("combobox", { name: "Video quality" });
    expect(within(select).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual(["auto", "original", "1080p", "720p"]);
  });

  it("does not offer a failed quality even when it still has a URL", () => {
    const manifest: MediaManifest = { schema_version: "analysis_media.v1", status: "ready", sources: [
      { quality: "original", status: "ready", width: 720, height: 1280, url: "/original", filename: "source.mov", error: null },
      { quality: "480p", status: "failed", width: 854, height: 480, url: "/480", filename: "480.mp4", error: "transcode failed" },
    ] };
    function Fixture() { const controller = useMediaController(manifest); return <MediaControls controller={controller} />; }
    render(<Fixture />);

    const select = screen.getByRole("combobox", { name: "Video quality" });
    expect(within(select).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual(["auto", "original"]);
  });

  it("routes a manual quality choice through the existing setQuality callback", () => {
    const setQuality = vi.fn();
    const controller = { state: { duration: 8, currentTime: 0, previewTime: null, buffered: [], paused: true, buffering: false, muted: false, playbackRate: 1, quality: "auto", isFullscreen: false, isPictureInPicture: false, volume: 1, error: null }, source: null, availableQualities: ["auto", "original", "720p"], togglePlay: vi.fn(), commitSeek: vi.fn(), previewSeek: vi.fn(), setMuted: vi.fn(), setPlaybackRate: vi.fn(), setQuality } as never;
    render(<MediaControls controller={controller} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Video quality" }), { target: { value: "720p" } });

    expect(setQuality).toHaveBeenCalledWith("720p");
  });
});
