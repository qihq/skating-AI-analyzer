// @ts-expect-error Node builtin is used only by the offline fixture test runner.
import { readFileSync } from "node:fs";
import { forwardRef, useImperativeHandle } from "react";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useNavigate } from "react-router-dom";
import { it, expect, vi, afterEach, beforeEach, describe } from "vitest";
import userEvent from "@testing-library/user-event";
import * as client from "../api/client";
import * as expApi from "../analysis-v2/api";
import { decodeAnalysisExperienceV2 } from "../analysis-v2/contracts";
import ActionPhaseStrip from "./ActionPhaseStrip";
import ModernAnalysisDetail from "../modern/ModernAnalysisDetail";
const { seek } = vi.hoisted(() => ({ seek: vi.fn() }));
vi.mock("../media/IceMediaPlayer", () => ({ IceMediaPlayer: forwardRef((_props, ref) => {
  useImperativeHandle(ref, () => ({ seek })); return <div data-testid="player-substitute" />;
}) }));
vi.mock("../api/client", async original => ({ ...await original<typeof import("../api/client")>(), fetchAnalysis: vi.fn(), fetchAnalysisPose: vi.fn() }));
vi.mock("../analysis-v2/api", async original => ({ ...await original<typeof import("../analysis-v2/api")>(), fetchAnalysisExperienceV2: vi.fn() }));
vi.mock("./AppModeContext", () => ({ useAppMode: () => ({ isParentMode: false, parentPin: null }) }));
const fixturePath = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env.JUMP_REPLAY_FIXTURE;
const fixtures = fixturePath ? JSON.parse(readFileSync(fixturePath, "utf8")) : null;
// These fixtures are exported by the actual builder -> report -> SQLite -> GET test.
describe.skipIf(!fixturePath)("rotation production GET consumers", () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  beforeEach(() => {
    vi.mocked(client.fetchAnalysis).mockImplementation(async id => structuredClone(fixtures[id].detail));
    vi.mocked(client.fetchAnalysisPose).mockImplementation(async id => structuredClone(fixtures[id].pose));
    vi.mocked(expApi.fetchAnalysisExperienceV2).mockImplementation(async id => decodeAnalysisExperienceV2(structuredClone(fixtures[id].experience)));
  });
  it("shows the saved representative, interval and every legal support frame, seeking in playback seconds", () => {
    const v = fixtures["synthetic-rotation"], r = v.detail.bio_data.jump_stages.rotation;
    render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} />);
    const panel = within(screen.getByRole("region", { name: "旋转支持原帧" }));
    expect(panel.getByText(/支持区间（分析时间）/)).toHaveTextContent("0.150s–0.350s");
    expect(panel.getByAltText("旋转支持原帧 " + r.frame_id)).toHaveAttribute("src", expect.stringContaining(r.frame_id + ".jpg?saved_only=true"));
    expect(panel.getAllByRole("button", { name: /旋转支持帧 frame_/ })).toHaveLength(r.evidence.support_frames.length);
    for (const p of r.evidence.support_frames) {
      expect(v.image_reads[p.frame_id + ".jpg"]).toMatch(/^[a-f0-9]{64}$/);
      fireEvent.click(panel.getByRole("button", { name: new RegExp("旋转支持帧 " + p.frame_id) }));
      expect(panel.getByAltText("旋转支持原帧 " + p.frame_id)).toHaveAttribute("src", expect.stringContaining(p.frame_id + ".jpg?saved_only=true"));
      fireEvent.load(panel.getByAltText("旋转支持原帧 " + p.frame_id));
      fireEvent.click(panel.getByRole("button", { name: "定位旋转支持帧视频" }));
      expect(seek).toHaveBeenLastCalledWith(p.playback_timestamp, { play: true });
    }
    expect(v.detail.report.jump_stages.rotation).toEqual(r);
  });
  it.each(["image-only", "missing-duration", "unverified-mapping"])("keeps support selection available without seek: %s", async mode => {
    const v = structuredClone(fixtures["synthetic-rotation"]);
    if (mode === "missing-duration") { v.detail.source_duration_sec = null; v.detail.media_manifest = null; }
    if (mode === "unverified-mapping") for (const p of v.detail.bio_data.jump_stages.rotation.evidence.support_frames) p.time_source = "legacy_or_sampling_time_unverified";
    render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} showVideo={mode !== "image-only"} />);
    const panel = within(screen.getByRole("region", { name: "旋转支持原帧" }));
    const p = v.detail.bio_data.jump_stages.rotation.evidence.support_frames[1];
    const button = panel.getByRole("button", { name: "旋转支持帧 " + p.frame_id });
    expect(button).toBeEnabled(); button.focus(); await userEvent.keyboard("{Enter}");
    expect(panel.getByAltText("旋转支持原帧 " + p.frame_id)).toBeInTheDocument();
    fireEvent.load(panel.getByAltText("旋转支持原帧 " + p.frame_id));
    expect(panel.getByText(/可以查看原帧，但无法定位视频/)).toBeInTheDocument();
    expect(panel.queryByRole("button", { name: "定位旋转支持帧视频" })).not.toBeInTheDocument();
    expect(seek).not.toHaveBeenCalled();
  });
  it("keeps observations on separate sides of an invalid face joint and labels a partial window", () => {
    const v = fixtures["synthetic-rotation-gap"];
    const view = render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} showVideo={false} />);
    let panel = within(screen.getByRole("region", { name: "旋转支持原帧" }));
    expect(panel.queryByRole("button", { name: /旋转支持帧 frame_/ })).not.toBeInTheDocument();
    const runs = v.detail.bio_data.jump_stages.rotation.evidence.observation_sequences;
    expect(panel.getAllByRole("button", { name: /投影观察帧/ })).toHaveLength(runs[0].support_frames.length);
    fireEvent.click(panel.getByRole("button", { name: "观察片段 2" }));
    expect(panel.getAllByRole("button", { name: /投影观察帧/ })).toHaveLength(runs[1].support_frames.length);
    expect(panel.queryByRole("button", { name: /frame_0006/ })).not.toBeInTheDocument();
    expect(panel.queryByRole("button", { name: /frame_0004/ })).not.toBeInTheDocument();
    view.unmount();
    const partial = fixtures["synthetic-rotation-partial"];
    render(<ActionPhaseStrip analysis={partial.detail} pose={partial.pose} showVideo={false} />);
    panel = within(screen.getByRole("region", { name: "旋转支持原帧" }));
    expect(panel.getByText(/缺少相容的起落候选/)).toBeInTheDocument();
    expect(panel.getAllByRole("button", { name: /投影观察帧/ }).length).toBeGreaterThan(0);
    expect(seek).not.toHaveBeenCalled();
  });
  it("replaces a missing saved frame with an explicit unavailable state, then permits another saved frame", () => {
    const v = fixtures["synthetic-rotation-missing-image"];
    expect(v.missing_image_names).toEqual(["frame_0008.jpg"]);
    render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} showVideo={false} />);
    const panel = within(screen.getByRole("region", { name: "旋转支持原帧" }));
    fireEvent.click(panel.getByRole("button", { name: "旋转支持帧 frame_0004" }));
    fireEvent.click(panel.getByRole("button", { name: /旋转支持帧 frame_0008/ }));
    fireEvent.error(panel.getByAltText("旋转支持原帧 frame_0008"));
    expect(panel.getByRole("status")).toHaveTextContent("保存原帧不可用：frame_0008");
    expect(panel.queryByRole("img")).not.toBeInTheDocument();
    fireEvent.click(panel.getByRole("button", { name: "旋转支持帧 frame_0005" }));
    expect(panel.getByAltText("旋转支持原帧 frame_0005")).toHaveAttribute("src", expect.stringContaining("saved_only=true"));
    expect(seek).not.toHaveBeenCalled();
  });
  it("selects saved trajectory images by keyboard and shows an error without seek or a stale image", () => {
    const v = fixtures["synthetic-rotation-missing-image"];
    render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} showVideo={false} />);
    const panel = within(screen.getByRole("region", { name: "髋中点投影轨迹" }));
    fireEvent.keyDown(panel.getByRole("button", { name: "轨迹点 frame_0005" }), { key: "Enter" });
    expect(panel.getByAltText("髋轨迹原帧 frame_0005")).toBeInTheDocument();
    fireEvent.keyDown(panel.getByRole("button", { name: "轨迹点 frame_0008" }), { key: " " });
    expect(panel.queryByAltText("髋轨迹原帧 frame_0005")).not.toBeInTheDocument();
    fireEvent.error(panel.getByAltText("髋轨迹原帧 frame_0008"));
    expect(panel.getByRole("status")).toHaveTextContent("保存原帧不可用：frame_0008");
    expect(panel.queryByRole("img")).not.toBeInTheDocument();
    expect(seek).not.toHaveBeenCalled();
  });
  it("reopens saved rotation in the real detail page and clears it on analysis change", async () => {
    function Switch() { const navigate = useNavigate(); return <button onClick={() => navigate("/analysis/synthetic-unavailable?view=moments")}>切换分析</button>; }
    const element = <MemoryRouter initialEntries={["/analysis/synthetic-rotation?view=moments"]}><Switch /><Routes><Route path="/analysis/:id" element={<ModernAnalysisDetail />} /></Routes></MemoryRouter>;
    let view = render(element);
    await screen.findByAltText("旋转支持原帧 frame_0008");
    fireEvent.click(screen.getByRole("button", { name: "旋转支持帧 frame_0005" }));
    view.unmount(); view = render(element);
    await screen.findByAltText("旋转支持原帧 frame_0008");
    expect(screen.queryByAltText("旋转支持原帧 frame_0005")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "切换分析" }));
    await waitFor(() => expect(client.fetchAnalysisPose).toHaveBeenCalledWith("synthetic-unavailable"));
    await waitFor(() => expect(screen.queryByRole("button", { name: /旋转支持帧 frame_/ })).not.toBeInTheDocument());
  });
});
