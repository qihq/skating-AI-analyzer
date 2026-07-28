import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IceMediaPlayer } from "./IceMediaPlayer";

describe("IceMediaPlayer", () => {
  it("composes the shared surface and controls", () => {
    render(<IceMediaPlayer fallbackSrc="source.mp4" markers={[{ id: "T", label: "T", timestamp: 1 }]} />);
    expect(screen.getByLabelText("分析视频")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "跳到T" })).toBeInTheDocument();
  });
});
