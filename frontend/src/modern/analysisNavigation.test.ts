import { describe, expect, it } from "vitest";

import { resolveAnalysisView } from "./analysisNavigation";

describe("modern analysis navigation", () => {
  it.each([
    ["evidence", "moments"],
    ["pose", "body"],
    ["followup", "ask"],
    ["diagnostics", "more"],
  ] as const)("maps the legacy %s workspace tab to %s", (legacyTab, expected) => {
    expect(resolveAnalysisView({ legacyTab })).toBe(expected);
  });

  it("prefers an explicit modern view and rejects unknown values", () => {
    expect(resolveAnalysisView({ view: "ask", legacyTab: "pose" })).toBe("ask");
    expect(resolveAnalysisView({ view: "unknown", legacyTab: "unknown" })).toBe("summary");
  });
});
