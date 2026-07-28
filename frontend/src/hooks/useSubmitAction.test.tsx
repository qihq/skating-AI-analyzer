import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useSubmitAction } from "./useSubmitAction";

describe("useSubmitAction", () => {
  it("prevents duplicate in-flight actions and shows success temporarily", async () => {
    vi.useFakeTimers();
    let resolveAction: ((value: string) => void) | undefined;
    const action = vi.fn(() => new Promise<string>((resolve) => { resolveAction = resolve; }));
    const { result } = renderHook(() => useSubmitAction({ successDurationMs: 100 }));

    let firstRun: Promise<string | undefined> | undefined;
    await act(async () => {
      firstRun = result.current.run(action);
      await Promise.resolve();
    });
    expect(result.current.status).toBe("submitting");
    await act(async () => { await result.current.run(action); });
    expect(action).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveAction?.("done");
      await firstRun;
    });
    expect(result.current.status).toBe("success");
    act(() => vi.advanceTimersByTime(100));
    expect(result.current.status).toBe("idle");
    vi.useRealTimers();
  });

  it("reports an error and resets without updating after unmount", async () => {
    vi.useFakeTimers();
    const onError = vi.fn();
    const { result, unmount } = renderHook(() => useSubmitAction({ errorDurationMs: 100, onError }));

    await act(async () => {
      try {
        await result.current.run(() => { throw new Error("offline"); });
      } catch (error) {
        expect(error).toEqual(new Error("offline"));
      }
    });
    expect(result.current.status).toBe("error");
    expect(onError).toHaveBeenCalledTimes(1);
    unmount();
    act(() => vi.advanceTimersByTime(100));
    vi.useRealTimers();
  });
});
