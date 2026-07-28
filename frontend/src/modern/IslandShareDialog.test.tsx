import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import IslandShareDialog from "./IslandShareDialog";

const page = (index: number) => ({ url: `blob:page-${index}`, blob: new Blob([String(index)], { type: "image/jpeg" }), filename: `page-${index}.jpg`, copiedToClipboard: false, mimeType: "image/jpeg", sizeBytes: 1, canNativeShare: false });

describe("IslandShareDialog", () => {
  it("lets the user switch between exported pages", () => {
    render(<IslandShareDialog preview={null} previews={[page(1), page(2)]} title="分享" onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "第 2 页" }));
    expect(screen.getByAltText("分享预览")).toHaveAttribute("src", "blob:page-2");
    expect(screen.getByRole("button", { name: "下载全部" })).toBeInTheDocument();
  });
});
