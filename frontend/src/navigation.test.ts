import { describe, expect, it } from "vitest";

import { PRIMARY_NAV_ITEMS, primaryTabForPath } from "./navigation";

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
