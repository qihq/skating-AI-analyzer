import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VideoSurface } from "./VideoSurface";
import { useMediaController } from "./useMediaController";

function Fixture() { const controller = useMediaController(null); return <VideoSurface controller={controller} manifest={{ schema_version: "x", status: "ready", sources: [{ quality: "original", status: "ready", width: null, height: null, url: "source.mp4", filename: null, error: null }] }} />; }
describe("VideoSurface", () => { it("owns one video element", () => { render(<Fixture />); expect(screen.getByLabelText("分析视频")).toHaveAttribute("src", "source.mp4"); }); });
