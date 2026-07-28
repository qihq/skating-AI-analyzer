import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MediaTimeline } from "./MediaTimeline";

describe("MediaTimeline", () => {
  it("previews while dragging and commits on release", () => {
    const preview = vi.fn(); const commit = vi.fn();
    render(<MediaTimeline duration={10} currentTime={2} previewTime={null} buffered={[]} markers={[{ id: "t", timestamp: 3, label: "T" }]} onPreview={preview} onCommit={commit} />);
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "4" } });
    fireEvent.pointerUp(slider, { target: { value: "4" } });
    expect(preview).toHaveBeenCalledWith(4);
    expect(commit).toHaveBeenCalledWith(4);
  });
});
