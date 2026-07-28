import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MediaControls } from "./MediaControls";

describe("MediaControls", () => {
  it("keeps marker jumps directly accessible", () => {
    const controller = { state: { duration: 8, currentTime: 0, previewTime: null, buffered: [], paused: true, buffering: false, muted: false, playbackRate: 1, quality: "auto", isFullscreen: false, isPictureInPicture: false, volume: 1, error: null }, source: null, togglePlay: vi.fn(), commitSeek: vi.fn(), previewSeek: vi.fn(), setMuted: vi.fn(), setPlaybackRate: vi.fn(), setQuality: vi.fn() } as never;
    render(<MediaControls controller={controller} markers={[{ id: "T", label: "T", timestamp: 2 }]} />);
    expect(screen.getByRole("button", { name: "跳到T" })).toBeInTheDocument();
  });
});
