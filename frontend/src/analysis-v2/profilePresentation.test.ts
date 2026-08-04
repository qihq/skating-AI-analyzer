import { describe, expect, it } from "vitest";

import { actionEventLabel, actionFamilyLabel, actionStateLabel } from "./profilePresentation";

describe("profile presentation", () => {
  it("uses family language without converting unknown to step", () => {
    expect(actionFamilyLabel("unknown")).toBe("未知动作");
    expect(actionStateLabel("ambiguous")).toBe("有歧义");
    expect(actionEventLabel({ profile: "spiral", state: "confirmed", subtype: null })).toBe("燕式 · 已确认");
  });
});
