import { describe, expect, it } from "vitest";

import { MODERN_NAV_ITEMS, modernSpaceForPath, PRIMARY_NAV_ITEMS, primaryTabForPath } from "./navigation";

describe("primary navigation", () => {
  it("contains exactly the four parent concepts", () => {
    expect(PRIMARY_NAV_ITEMS.map((item) => [item.label, item.to])).toEqual([
      ["首页", "/home"],
      ["复盘", "/review"],
      ["进步", "/archive"],
      ["档案", "/path"],
    ]);
  });

  it("keeps detail routes attached to their parent concept", () => {
    expect(primaryTabForPath("/report/analysis-1")).toBe("review");
    expect(primaryTabForPath("/analysis-chat")).toBe("review");
    expect(primaryTabForPath("/history")).toBe("archive");
    expect(primaryTabForPath("/compare/a/b")).toBe("archive");
    expect(primaryTabForPath("/settings")).toBeUndefined();
  });
});

describe("modern island navigation", () => {
  it("exposes exactly four family-growth spaces with review as the primary action", () => {
    expect(MODERN_NAV_ITEMS.map((item) => [item.label, item.to, item.primary])).toEqual([
      ["首页", "/home", false],
      ["开始复盘", "/review", true],
      ["成长", "/growth", false],
      ["我的", "/me", false],
    ]);
  });

  it("folds legacy routes into their modern parent spaces", () => {
    expect(modernSpaceForPath("/review")).toBe("review");
    expect(modernSpaceForPath("/analysis/analysis-1")).toBe("review");
    expect(modernSpaceForPath("/report/analysis-1/workspace")).toBe("review");
    expect(modernSpaceForPath("/analysis-chat")).toBe("review");
    expect(modernSpaceForPath("/home")).toBe("home");
    expect(modernSpaceForPath("/growth")).toBe("growth");
    expect(modernSpaceForPath("/me")).toBe("me");
    expect(modernSpaceForPath("/chapters")).toBe("growth");
    expect(modernSpaceForPath("/plan/plan-1")).toBe("growth");
    expect(modernSpaceForPath("/settings/api")).toBe("me");
    expect(modernSpaceForPath("/golden")).toBe("me");
  });
});
