// @ts-expect-error Node builtin is used only by the offline fixture test runner.
import { readFileSync } from "node:fs";
import { forwardRef, useImperativeHandle, StrictMode } from "react";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ActionPhaseStrip from "./ActionPhaseStrip";
const { seek } = vi.hoisted(() => ({ seek: vi.fn() }));
vi.mock("../media/IceMediaPlayer", () => ({ IceMediaPlayer: forwardRef((_props, ref) => {
  useImperativeHandle(ref, () => ({ seek })); return <div data-testid="player-substitute" />;
}) }));
const fixturePath = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.JUMP_REPLAY_FIXTURE;
const fixtures = fixturePath ? JSON.parse(readFileSync(fixturePath, "utf8")) : null;
// Exported by the real builder -> report -> isolated SQLite -> GET path.
describe.skipIf(!fixturePath)("saved frame availability gates production playback", () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  const value = () => structuredClone(fixtures["synthetic-rotation"]);
  const panel = (kind: "trajectory" | "rotation") => within(screen.getByRole("region", { name: kind === "trajectory" ? "髋中点投影轨迹" : "旋转支持原帧" }));
  const image = (kind: "trajectory" | "rotation", frame: string) => panel(kind).getByAltText((kind === "trajectory" ? "髋轨迹原帧 " : "旋转支持原帧 ") + frame);
  const choose = (kind: "trajectory" | "rotation", frame: string) => fireEvent.click(panel(kind).getByRole("button", { name: new RegExp("^" + (kind === "trajectory" ? "轨迹点 " : "旋转支持帧 ") + frame) }));
  it("waits for the selected image load, seeks once in playback seconds, and never seeks on initial load", () => {
    const v = value(); const points = v.detail.bio_data.jump_measurements.trajectory.points;
    render(<StrictMode><ActionPhaseStrip analysis={v.detail} pose={v.pose} /></StrictMode>);
    fireEvent.load(image("trajectory", points[0].frame_id)); expect(seek).not.toHaveBeenCalled();
    choose("trajectory", "frame_0008");
    expect(panel("trajectory").getByRole("status")).toHaveTextContent("加载中");
    expect(panel("trajectory").queryByText(/可定位已有视频/)).not.toBeInTheDocument();
    expect(seek).not.toHaveBeenCalled();
    const img = image("trajectory", "frame_0008"); fireEvent.load(img); fireEvent.load(img);
    expect(seek).toHaveBeenCalledTimes(1); expect(seek).toHaveBeenLastCalledWith(.7, { play: true });
    expect(panel("trajectory").getByText(/可定位已有视频/)).toBeInTheDocument();
  });
  it.each(["trajectory", "rotation"] as const)("ignores stale load/error through A-B-A and requires the current request: %s", kind => {
    const v = value(); render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} />);
    choose(kind, "frame_0004"); const oldA = image(kind, "frame_0004");
    choose(kind, "frame_0005"); const oldB = image(kind, "frame_0005");
    choose(kind, "frame_0004"); const currentA = image(kind, "frame_0004");
    expect(currentA).not.toBe(oldA);
    fireEvent.load(oldA); fireEvent.error(oldB); fireEvent.load(oldB); fireEvent.error(oldA);
    expect(seek).not.toHaveBeenCalled(); expect(currentA).toBeInTheDocument();
    expect(panel(kind).getByRole("status")).toHaveTextContent("加载中");
    expect(panel(kind).queryByRole("button", { name: "定位旋转支持帧视频" })).not.toBeInTheDocument();
    fireEvent.load(currentA);
    if (kind === "rotation") {
      expect(seek).not.toHaveBeenCalled(); fireEvent.click(panel(kind).getByRole("button", { name: "定位旋转支持帧视频" }));
    }
    expect(seek).toHaveBeenLastCalledWith(.3, { play: true }); seek.mockClear();
    choose(kind, "frame_0005"); const currentB = image(kind, "frame_0005");
    fireEvent.load(currentA); fireEvent.error(currentA); expect(seek).not.toHaveBeenCalled();
    fireEvent.load(currentB);
    if (kind === "rotation") fireEvent.click(panel(kind).getByRole("button", { name: "定位旋转支持帧视频" }));
    fireEvent.error(oldB); expect(currentB).toBeInTheDocument();
    expect(seek).toHaveBeenCalledTimes(1); expect(seek).toHaveBeenLastCalledWith(.4, { play: true });
  });
  it.each(["trajectory", "rotation"] as const)("does not reuse readiness across analyses with identical frame names: %s", kind => {
    const a = value(); const b = value(); b.detail.id += "-other";
    const view = render(<ActionPhaseStrip analysis={a.detail} pose={a.pose} />);
    choose(kind, "frame_0005"); const old = image(kind, "frame_0005"); fireEvent.load(old); seek.mockClear();
    const oldControl = panel(kind).queryByRole("button", { name: "定位旋转支持帧视频" });
    view.rerender(<ActionPhaseStrip analysis={b.detail} pose={b.pose} />);
    choose(kind, "frame_0005"); const current = image(kind, "frame_0005");
    expect(current).toHaveAttribute("src", expect.stringContaining(encodeURIComponent(b.detail.id)));
    if (oldControl) fireEvent.click(oldControl); fireEvent.load(old); fireEvent.error(old);
    expect(seek).not.toHaveBeenCalled(); expect(panel(kind).getByRole("status")).toHaveTextContent("加载中");
    fireEvent.load(current);
    if (kind === "rotation") fireEvent.click(panel(kind).getByRole("button", { name: "定位旋转支持帧视频" }));
    expect(seek).toHaveBeenLastCalledWith(.4, { play: true }); seek.mockClear();
    view.rerender(<ActionPhaseStrip analysis={a.detail} pose={a.pose} />);
    expect(panel(kind).getByRole("status")).toHaveTextContent("加载中");
    fireEvent.error(current); fireEvent.load(current); expect(seek).not.toHaveBeenCalled();
  });
  it.each(["trajectory", "rotation"] as const)("keeps a failed request terminal and recovers on a valid frame: %s", kind => {
    const v = structuredClone(fixtures["synthetic-rotation-missing-image"]);
    expect(v.missing_image_names).toEqual(["frame_0008.jpg"]);
    render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} />);
    choose(kind, "frame_0008"); const failed = image(kind, "frame_0008"); fireEvent.error(failed); fireEvent.load(failed);
    expect(panel(kind).getByRole("status")).toHaveTextContent("保存原帧不可用：frame_0008");
    expect(panel(kind).queryByRole("img")).not.toBeInTheDocument();
    expect(panel(kind).queryByRole("button", { name: "定位旋转支持帧视频" })).not.toBeInTheDocument();
    expect(panel(kind).queryByText(/可定位已有视频/)).not.toBeInTheDocument(); expect(seek).not.toHaveBeenCalled();
    choose(kind, "frame_0005"); const good = image(kind, "frame_0005"); fireEvent.error(failed);
    expect(panel(kind).getByRole("status")).toHaveTextContent("加载中"); expect(seek).not.toHaveBeenCalled(); fireEvent.load(good);
    if (kind === "rotation") fireEvent.click(panel(kind).getByRole("button", { name: "定位旋转支持帧视频" }));
    expect(seek).toHaveBeenLastCalledWith(.4, { play: true });
  });
  it("revokes rotation locate after error and while selecting another frame", () => {
    const v = value(); render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} />);
    choose("rotation", "frame_0004");
    expect(panel("rotation").queryByRole("button", { name: "定位旋转支持帧视频" })).not.toBeInTheDocument();
    const img = image("rotation", "frame_0004"); fireEvent.load(img);
    const oldButton = panel("rotation").getByRole("button", { name: "定位旋转支持帧视频" });
    fireEvent.error(img); fireEvent.click(oldButton);
    expect(panel("rotation").queryByRole("button", { name: "定位旋转支持帧视频" })).not.toBeInTheDocument(); expect(seek).not.toHaveBeenCalled();
    choose("rotation", "frame_0005"); fireEvent.load(image("rotation", "frame_0005"));
    const readyButton = panel("rotation").getByRole("button", { name: "定位旋转支持帧视频" });
    choose("rotation", "frame_0004"); fireEvent.click(readyButton);
    expect(panel("rotation").getByRole("status")).toHaveTextContent("加载中"); expect(seek).not.toHaveBeenCalled();
  });
  it.each(["image-only", "missing-duration", "unverified-mapping"])("keeps keyboard/mouse selection after loading while refusing untrusted seek: %s", mode => {
    const v = value();
    if (mode === "missing-duration") { v.detail.source_duration_sec = null; v.detail.media_manifest = null; }
    if (mode === "unverified-mapping") {
      for (const p of [...v.detail.bio_data.jump_measurements.trajectory.points, ...v.detail.bio_data.jump_stages.rotation.evidence.support_frames]) p.time_source = "legacy_or_sampling_time_unverified";
    }
    render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} showVideo={mode !== "image-only"} />);
    const point = panel("trajectory").getByRole("button", { name: "轨迹点 frame_0005" });
    fireEvent.keyDown(point, { key: " " }); fireEvent.load(image("trajectory", "frame_0005"));
    choose("rotation", "frame_0005"); fireEvent.load(image("rotation", "frame_0005"));
    expect(image("trajectory", "frame_0005")).toHaveAttribute("src", expect.stringContaining("saved_only=true"));
    expect(image("rotation", "frame_0005")).toHaveAttribute("src", expect.stringContaining("saved_only=true"));
    expect(panel("rotation").queryByRole("button", { name: "定位旋转支持帧视频" })).not.toBeInTheDocument(); expect(seek).not.toHaveBeenCalled();
  });
});
