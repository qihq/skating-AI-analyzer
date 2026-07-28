import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
