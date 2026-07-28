import { describe, expect, it, vi } from "vitest";
import { exportShareDocument } from "./shareExport";

vi.mock("./shareCanvas", () => ({ createAdaptiveSharePoster: vi.fn().mockResolvedValue({ blob: new Blob(), filename: "page.jpg", mimeType: "image/jpeg", sizeBytes: 1, canNativeShare: false }) }));

describe("exportShareDocument", () => {
  it("exports each calculated page", async () => {
    const result = await exportShareDocument({ title: "Long", subtitle: "", eyebrow: "Test", filename: "share.jpg", sections: Array.from({ length: 5 }, (_, index) => ({ label: `S${index}`, title: "x".repeat(900) })) });
    expect(result.pages.length).toBeGreaterThan(1);
  });
});
