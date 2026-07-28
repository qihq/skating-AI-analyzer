import { describe, expect, it } from "vitest";
import { formatTime } from "./formatTime";

describe("formatTime", () => {
  it("formats minutes and hours while guarding missing values", () => {
    expect(formatTime(65)).toBe("01:05");
    expect(formatTime(3661)).toBe("01:01:01");
    expect(formatTime(null)).toBe("--:--");
  });
});
