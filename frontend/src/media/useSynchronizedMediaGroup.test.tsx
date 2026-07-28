import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useSynchronizedMediaGroup } from "./useSynchronizedMediaGroup";

const side = { analysis_id: "a", video_url: "video.mp4", available: true, missing_reason: null, action_window_start: 2, action_window_end: 6, action_window_duration: 4, sync_start: 2, sync_duration: 4, is_slow_motion: false, source_fps: 30 };

describe("useSynchronizedMediaGroup", () => {
  it("maps a relative seek across each comparable window", () => {
    const left = { seek: vi.fn(), pause: vi.fn(), video: () => null };
    const right = { seek: vi.fn(), pause: vi.fn(), video: () => null };
    const { result } = renderHook(() => useSynchronizedMediaGroup({ current: left }, { current: right }, side, { ...side, sync_start: 10, sync_duration: 8 }));
    result.current.seekRelative(0.5);
    expect(left.seek).toHaveBeenCalledWith(4);
    expect(right.seek).toHaveBeenCalledWith(14);
  });
});
