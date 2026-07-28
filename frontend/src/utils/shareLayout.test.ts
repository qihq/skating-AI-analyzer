import { describe, expect, it } from "vitest";
import { paginateShareDocument } from "./shareLayout";

describe("paginateShareDocument", () => {
  it("keeps each semantic section intact while creating pages", () => {
    const pages = paginateShareDocument({ title: "Long report", subtitle: "", eyebrow: "Test", filename: "share.jpg", sections: Array.from({ length: 5 }, (_, index) => ({ label: `S${index}`, title: "x".repeat(900) })) }, 1500);
    expect(pages.length).toBeGreaterThan(1);
    expect(pages.flatMap((page) => page.sections).map((section) => section.label)).toEqual(["S0", "S1", "S2", "S3", "S4"]);
    expect(pages.every((page, index) => page.pageNumber === index + 1 && page.pageCount === pages.length)).toBe(true);
  });
});
