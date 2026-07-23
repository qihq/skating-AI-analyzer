import { act, renderHook } from "@testing-library/react";
import { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { IslandThemeProvider, periodForHour, useIslandTheme } from "./IslandThemeContext";

describe("island time themes", () => {
  beforeEach(() => window.localStorage.clear());

  it("maps local hours to the four atmosphere periods", () => {
    expect(periodForHour(5)).toBe("morning");
    expect(periodForHour(12)).toBe("day");
    expect(periodForHour(18)).toBe("sunset");
    expect(periodForHour(23)).toBe("night");
  });

  it("persists a manually pinned period", () => {
    const wrapper = ({ children }: PropsWithChildren) => <IslandThemeProvider>{children}</IslandThemeProvider>;
    const { result } = renderHook(() => useIslandTheme(), { wrapper });
    act(() => result.current.setPreference("night"));
    expect(result.current.preference).toBe("night");
    expect(result.current.period).toBe("night");
    expect(window.localStorage.getItem("icebuddy.island-theme")).toBe("night");
  });
});
