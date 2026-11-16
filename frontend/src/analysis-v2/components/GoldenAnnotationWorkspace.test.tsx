import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { useAppMode } from "../../components/AppModeContext";
import { deleteGoldenSource, fetchGoldenReviewQueue, fetchGoldenSourceFrame, fetchGoldenSourceFrameByPts, fetchGoldenSourceMediaUrl, fetchGoldenWorkspace, saveGoldenAnnotations } from "../api";
import type { GoldenEvent, GoldenWorkspace } from "../golden-contracts";
import GoldenAnnotationWorkspace from "./GoldenAnnotationWorkspace";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({ fetchGoldenWorkspace: vi.fn(), fetchGoldenReviewQueue: vi.fn(), fetchGoldenSourceFrame: vi.fn(), fetchGoldenSourceFrameByPts: vi.fn(), fetchGoldenSourceMediaUrl: vi.fn(), saveGoldenAnnotations: vi.fn(), importGoldenSource: vi.fn(), attestGoldenReview: vi.fn(), updateGoldenSource: vi.fn(), deleteGoldenSource: vi.fn() }));
vi.mock("../../media/IceMediaPlayer", () => ({ IceMediaPlayer: (props: { className?: string; onStepSourceFrame: (direction: -1 | 1) => void; onTimeChange?: (value: number) => void; overlay?: unknown; aspectRatio?: number }) => <div data-testid="golden-player" className={props.className}><button onClick={() => props.onStepSourceFrame(1)}>Next source frame</button><button onClick={() => props.onTimeChange?.(0)}>Report stale player time</button><button onClick={() => props.onTimeChange?.(4.2)}>Report current player time</button><output data-testid="media-aspect-ratio">{props.aspectRatio}</output>{props.overlay as never}</div> }));

const workspace = vi.mocked(fetchGoldenWorkspace);
const review = vi.mocked(fetchGoldenReviewQueue);
const frame = vi.mocked(fetchGoldenSourceFrame);
const frameByPts = vi.mocked(fetchGoldenSourceFrameByPts);
const save = vi.mocked(saveGoldenAnnotations);
const gateTemplate = {
  gate: "G1" as const,
  status: "not-run" as const,
  gate_policy_version: "golden-gate-policy.v2" as const,
  evidence_scope: "limited_sample" as const,
  required_source_videos: 18,
  required_valid_events: 18,
  profile_minimums: { jump: 10, spin: 4, step: 2, spiral: 2 },
  required_new_events: 18,
  pose_frame_range: [24, 40] as [number, number],
  g2_event_range: [24, 30] as [number, number],
  g2_profile_ranges: { jump: [10, 14], spin: [6, 8], step: [4, 5], spiral: [4, 5] } as Record<string, [number, number]>,
};

function mockData() {
  vi.clearAllMocks();
  vi.mocked(useAppMode).mockReturnValue({ parentPin: "1234" } as never);
  workspace.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 2, sources: [{ source_sha256: "d".repeat(64), duration_pts: 8, width: 1280, height: 720, source_frame_count: 240, display_rotation_degrees: 0, redacted_alias: "source-001", recording_session_id: "session-01", grouping_id: "group-01" }], events: [], tracks: [], poses: [] });
  review.mockResolvedValue([]); frame.mockResolvedValue({ sourceFrameIndex: 1, pts: .033, duration: .033 }); frameByPts.mockResolvedValue({ sourceFrameIndex: 0, pts: 0, duration: .033 }); vi.mocked(fetchGoldenSourceMediaUrl).mockResolvedValue("blob:private-video");
}

describe("GoldenAnnotationWorkspace", () => {
  it("adds an unsaved event and keeps a source-frame PTS control available", async () => {
    mockData(); render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/source-001/)).toBeInTheDocument());
    const nextFrame = await screen.findByRole("button", { name: "Next source frame" });
    fireEvent.click(screen.getByRole("button", { name: /新建动作/i }));
    expect(screen.getByText(/有未保存修改/)).toBeInTheDocument();
    fireEvent.click(nextFrame);
    await waitFor(() => expect(frame).toHaveBeenCalled());
  });

  it("creates an event when randomUUID is unavailable on an HTTP origin", async () => {
    mockData();
    const originalCrypto = globalThis.crypto;
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: { getRandomValues: (bytes: Uint8Array) => bytes.fill(7) } });
    try {
      render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
      fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
      expect(screen.getByLabelText("Profile")).toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(/动作草稿已创建/);
    } finally {
      Object.defineProperty(globalThis, "crypto", { configurable: true, value: originalCrypto });
    }
  });

  it("locks the nearest source frame at the current playback PTS before enabling box drawing", async () => {
    mockData();
    frameByPts.mockResolvedValue({ sourceFrameIndex: 126, pts: 4.2, duration: .033 });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Report current player time" }));
    fireEvent.click(screen.getByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /锁定当前画面并画主滑手框/ }));
    await waitFor(() => expect(frameByPts).toHaveBeenCalledWith("1234", "d".repeat(64), 4.2));
    expect(frame).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/已锁定第 126 帧/);
    expect(screen.getByRole("button", { name: /正在等待画框/ })).toBeInTheDocument();
  });

  it("keeps a returned exact frame when the player reports its stale pre-seek time", async () => {
    mockData(); frame.mockResolvedValue({ sourceFrameIndex: 48, pts: 1.6, duration: .033 });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(screen.getByText(/当前时间 1\.600000 秒；源帧 48/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Report stale player time" }));
    expect(screen.getByText(/当前时间 1\.600000 秒；源帧 48/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/已定位到第 48 帧/);
  });

  it("steps forward from the current playback PTS when no source frame is locked", async () => {
    mockData();
    frameByPts.mockResolvedValue({ sourceFrameIndex: 126, pts: 4.2, duration: .033 });
    frame.mockResolvedValue({ sourceFrameIndex: 127, pts: 4.233, duration: .033 });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Report current player time" }));
    fireEvent.click(screen.getByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(frameByPts).toHaveBeenCalledWith("1234", "d".repeat(64), 4.2));
    expect(frame).toHaveBeenCalledWith("1234", "d".repeat(64), 127);
    expect(await screen.findByText(/当前时间 4\.233000 秒；源帧 127/)).toBeInTheDocument();
  });

  it("does not claim confirmation after a failed save", async () => {
    mockData(); save.mockRejectedValue(new Error("offline")); render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: /新建动作/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/保存失败.*没有写入任何修改/));
  });

  it("rejects track and pose labels outside the selected event before saving", async () => {
    mockData();
    frameByPts.mockResolvedValue({ sourceFrameIndex: 126, pts: 4.2, duration: .033 });
    save.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: "Report current player time" }));
    fireEvent.click(screen.getByRole("button", { name: /锁定当前画面并画主滑手框/ }));
    await waitFor(() => expect(frameByPts).toHaveBeenCalledWith("1234", "d".repeat(64), 4.2));

    fireEvent.change(screen.getByLabelText("Box left"), { target: { value: "0.1" } });
    fireEvent.change(screen.getByLabelText("Box top"), { target: { value: "0.1" } });
    fireEvent.change(screen.getByLabelText("Box right"), { target: { value: "0.8" } });
    fireEvent.change(screen.getByLabelText("Box bottom"), { target: { value: "0.9" } });
    fireEvent.click(screen.getAllByRole("button", { name: "添加到当前帧" })[0]);
    expect(screen.getByRole("alert")).toHaveTextContent(/主滑手框帧不在动作区间内/);

    fireEvent.change(screen.getByLabelText("Pose joint X"), { target: { value: "0.5" } });
    fireEvent.change(screen.getByLabelText("Pose joint Y"), { target: { value: "0.5" } });
    fireEvent.click(screen.getAllByRole("button", { name: "添加到当前帧" })[1]);
    expect(screen.getByRole("alert")).toHaveTextContent(/Pose 帧不在动作区间内/);

    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const payload = save.mock.calls[save.mock.calls.length - 1][1];
    expect(payload.tracks).toEqual([]);
    expect(payload.poses).toEqual([]);
  });

  it("adds and saves a track when the locked frame is inside the selected event", async () => {
    mockData();
    frameByPts.mockResolvedValue({ sourceFrameIndex: 126, pts: 4.2, duration: .033 });
    save.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Report current player time" }));
    fireEvent.click(screen.getByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /锁定当前画面并画主滑手框/ }));
    await waitFor(() => expect(frameByPts).toHaveBeenCalledWith("1234", "d".repeat(64), 4.2));

    fireEvent.change(screen.getByLabelText("Box left"), { target: { value: "0.1" } });
    fireEvent.change(screen.getByLabelText("Box top"), { target: { value: "0.1" } });
    fireEvent.change(screen.getByLabelText("Box right"), { target: { value: "0.8" } });
    fireEvent.change(screen.getByLabelText("Box bottom"), { target: { value: "0.9" } });
    fireEvent.click(screen.getAllByRole("button", { name: "添加到当前帧" })[0]);
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    const payload = save.mock.calls[save.mock.calls.length - 1][1];
    expect(payload.tracks).toEqual([expect.objectContaining({ source_frame_index: 126, pts: 4.2 })]);
  });

  it("blocks an existing out-of-range label and identifies the offending frame before the request", async () => {
    mockData();
    const sourceHash = "d".repeat(64);
    workspace.mockResolvedValue({
      dataset_id: "golden-v2-private-catalog", revision: 2,
      sources: [{ source_sha256: sourceHash, duration_pts: 8, width: 1280, height: 720, source_frame_count: 240, display_rotation_degrees: 0, redacted_alias: "source-001", recording_session_id: "session-01", grouping_id: "group-01" }],
      events: [{ event_id: "event-01", source_sha256: sourceHash, start_pts: 2, end_pts: 3, profile: "spin", subtype: null, observability: "observable", strata: [], ambiguity_tags: [], failure_tags: [], annotator_confidence: .9, main_skater_confirmed: true, split: "development", challenge_intervals: [] }],
      tracks: [{ label_id: "track-01", event_id: "event-01", source_sha256: sourceHash, source_frame_index: 0, pts: 0, bbox: { left: .1, top: .1, right: .8, bottom: .9 }, state: "confirmed" }],
      poses: [],
    });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /旋转 2\.00-3\.00 秒/ }));
    fireEvent.change(screen.getByLabelText("动作细分（可选）"), { target: { value: "dirty" } });
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));

    expect(screen.getByRole("alert")).toHaveTextContent(/主滑手框第 0 帧（0\.000 秒）不在动作区间 2\.000-3\.000 秒内/);
    expect(save).not.toHaveBeenCalled();
  });

  it("explains a schema validation failure without claiming anything was saved", async () => {
    mockData();
    save.mockRejectedValue({ isAxiosError: true, response: { status: 422 } });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/人物框\/Pose 帧是否位于对应动作区间内/));
    expect(screen.getByText(/有未保存修改/)).toBeInTheDocument();
  });

  it("captures a jump moment from the exact returned source frame and sends it as Ground Truth", async () => {
    mockData(); save.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: /新建动作/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /新建动作/i }));
    fireEvent.change(screen.getByLabelText("Profile"), { target: { value: "jump" } });
    await waitFor(() => expect(screen.getByText("跳跃关键时刻")).toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(frame).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/当前时间 0\.033000 秒/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByRole("button", { name: /使用当前精确帧/i })).toHaveLength(3));
    fireEvent.click(screen.getAllByRole("button", { name: /使用当前精确帧/i })[0]);
    await waitFor(() => expect(screen.getByText(/起跳：0\.033000 秒 \/ 帧 1/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const payload = save.mock.calls[save.mock.calls.length - 1][1];
    expect(payload.events[0]).toMatchObject({ jump: { takeoff: { pts: .033, source_frame_index: 1 } } });
  });

  it("stores a clear rotation as an exact convention-specific source-PTS label", async () => {
    mockData(); save.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.change(screen.getByLabelText("Profile"), { target: { value: "jump" } });
    fireEvent.change(await screen.findByLabelText("jump rotation definition"), { target: { value: "competition_naming" } });
    fireEvent.change(screen.getByLabelText("jump rotation status"), { target: { value: "exact" } });
    fireEvent.change(screen.getByLabelText("jump reported turns"), { target: { value: "2.5" } });
    fireEvent.change(screen.getByLabelText("jump rotation review start PTS"), { target: { value: "1.234" } });
    fireEvent.change(screen.getByLabelText("jump rotation review end PTS"), { target: { value: "1.456" } });
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const event = save.mock.calls[save.mock.calls.length - 1]?.[1].events[0] as GoldenEvent;
    const rotation = event.jump?.rotation;
    expect(rotation).toMatchObject({
      status: "exact",
      value_turns: 2.5,
      range_turns: null,
      definition: "competition_naming",
      convention: "axel_includes_forward_takeoff",
      review_start_pts: 1.234,
      review_end_pts: 1.456,
      review_method: "source_frame_step",
    });
  });

  it("stores a partial rotation only as an interval", async () => {
    mockData(); save.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.change(screen.getByLabelText("Profile"), { target: { value: "jump" } });
    fireEvent.change(await screen.findByLabelText("jump minimum turns"), { target: { value: "1.5" } });
    fireEvent.change(screen.getByLabelText("jump maximum turns"), { target: { value: "2.25" } });
    fireEvent.change(screen.getByLabelText("jump rotation review start PTS"), { target: { value: ".75" } });
    fireEvent.change(screen.getByLabelText("jump rotation review end PTS"), { target: { value: "1.25" } });
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const event = save.mock.calls[save.mock.calls.length - 1]?.[1].events[0] as GoldenEvent;
    const rotation = event.jump?.rotation;
    expect(rotation).toMatchObject({
      status: "range",
      value_turns: null,
      reported_turns: null,
      range_turns: [1.5, 2.25],
      definition: "airborne_body_rotation",
      review_start_pts: .75,
      review_end_pts: 1.25,
      review_method: "source_frame_step",
    });
  });

  it("upgrades a legacy spin rotation before editing its turn count", async () => {
    mockData();
    const sourceHash = "d".repeat(64);
    workspace.mockResolvedValue({
      dataset_id: "golden-v2-private-catalog", revision: 92,
      sources: [{ source_sha256: sourceHash, duration_pts: 10, width: 1280, height: 720, source_frame_count: 300, display_rotation_degrees: 0, redacted_alias: "spin01", recording_session_id: "spin01", grouping_id: "spin01" }],
      events: [{
        event_id: "legacy-spin", source_sha256: sourceHash, start_pts: 0, end_pts: 10, profile: "spin", subtype: null,
        observability: "observable", strata: [], ambiguity_tags: [], failure_tags: [], annotator_confidence: .9,
        main_skater_confirmed: true, split: "development", challenge_intervals: [],
        spin: { entry: { start_pts: 1, end_pts: 2 }, main: { start_pts: 2, end_pts: 9 }, exit: { start_pts: 9, end_pts: 10 }, rotation: { observed_turns_min: 5, observed_turns_max: 6, reported_turns: 5, convention: "unknown", observability: "observable", definition: null, status: null, value_turns: null, range_turns: null, review_start_pts: null, review_end_pts: null, review_method: "source_frame_step" } as never },
      }], tracks: [], poses: [],
    });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /旋转 0\.00-10\.00 秒/ }));
    expect(screen.getByLabelText("spin rotation definition")).toHaveValue("observed_spin_rotation");
    expect(screen.getByLabelText("spin rotation status")).toHaveValue("range");
    fireEvent.change(screen.getByLabelText("spin minimum turns"), { target: { value: "5.25" } });
    expect(screen.getByLabelText("spin minimum turns")).toHaveValue(5.25);
    expect(screen.getByLabelText("spin maximum turns")).toHaveValue(6);
  });

  it("explains the required workflow and deletes a source only after confirmation", async () => {
    mockData(); vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(deleteGoldenSource).mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("上传以后做什么？")).toBeInTheDocument());
    expect(screen.getByText(/普通事件最少要标/)).toBeInTheDocument();
    expect(screen.getByTestId("golden-gate-guidance")).toHaveTextContent("G1 18/18; G2 24-30; Pose 24-40");
    fireEvent.click(screen.getByRole("button", { name: /删除此视频和标签/ }));
    await waitFor(() => expect(deleteGoldenSource).toHaveBeenCalledWith("1234", "d".repeat(64), expect.objectContaining({ confirmation: "delete_source_and_labels" })));
  });

  it("supports pointer drawing for a main-skater box", async () => {
    mockData(); render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(frame).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /锁定当前画面并画主滑手框/ }));
    const overlay = await screen.findByRole("img", { name: /Golden 标注叠加结果/ });
    vi.spyOn(overlay, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 800, bottom: 450, width: 800, height: 450, toJSON: () => ({}) });
    Object.defineProperty(overlay, "setPointerCapture", { value: vi.fn() });
    fireEvent.pointerDown(overlay, { pointerId: 1, clientX: 100, clientY: 50 });
    fireEvent.pointerMove(overlay, { pointerId: 1, clientX: 500, clientY: 350 });
    fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 500, clientY: 350 });
    await waitFor(() => expect(screen.getByLabelText("Box left")).toHaveValue("0.1250"));
    expect(screen.getByLabelText("Box bottom")).toHaveValue("0.7778");
  });

  it("maps pointer boxes from a rotated display back to source-frame coordinates", async () => {
    mockData();
    workspace.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 2, sources: [{ source_sha256: "d".repeat(64), duration_pts: 8, width: 1280, height: 720, source_frame_count: 240, display_rotation_degrees: 90, redacted_alias: "source-001", recording_session_id: "session-01", grouping_id: "group-01" }], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(frame).toHaveBeenCalled());
    expect(Number(screen.getByTestId("media-aspect-ratio").textContent)).toBeCloseTo(720 / 1280);
    fireEvent.click(screen.getByRole("button", { name: /锁定当前画面并画主滑手框/ }));
    const overlay = await screen.findByRole("img", { name: /Golden 标注叠加结果/ });
    vi.spyOn(overlay, "getBoundingClientRect").mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 360, bottom: 640, width: 360, height: 640, toJSON: () => ({}) });
    Object.defineProperty(overlay, "setPointerCapture", { value: vi.fn() });
    fireEvent.pointerDown(overlay, { pointerId: 1, clientX: 36, clientY: 128 });
    fireEvent.pointerMove(overlay, { pointerId: 1, clientX: 180, clientY: 512 });
    fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 180, clientY: 512 });
    await waitFor(() => expect(screen.getByLabelText("Box left")).toHaveValue("0.2000"));
    expect(screen.getByLabelText("Box top")).toHaveValue("0.5000");
    expect(screen.getByLabelText("Box right")).toHaveValue("0.8000");
    expect(screen.getByLabelText("Box bottom")).toHaveValue("0.9000");
  });

  it("uses a compact portrait player while preserving the source aspect ratio", async () => {
    mockData();
    workspace.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 2, sources: [{ source_sha256: "d".repeat(64), duration_pts: 8, width: 720, height: 1280, source_frame_count: 240, display_rotation_degrees: 0, redacted_alias: "source-001", recording_session_id: "session-01", grouping_id: "group-01" }], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("golden-player")).toHaveClass("is-portrait"));
    expect(Number(screen.getByTestId("media-aspect-ratio").textContent)).toBeCloseTo(720 / 1280);
  });

  it("does not let a delayed duplicate load overwrite an unsaved event", async () => {
    mockData();
    const initial: GoldenWorkspace = { dataset_id: "golden-v2-private-catalog", revision: 2, sources: [{ source_sha256: "d".repeat(64), duration_pts: 8, width: 1280, height: 720, source_frame_count: 240, display_rotation_degrees: 0, redacted_alias: "source-001", recording_session_id: "session-01", grouping_id: "group-01" }], events: [], tracks: [], poses: [] };
    workspace.mockClear();
    let releaseDuplicate!: (value: GoldenWorkspace) => void;
    workspace
      .mockResolvedValueOnce(initial)
      .mockImplementationOnce(() => new Promise((resolve) => { releaseDuplicate = resolve; }));
    render(<StrictMode><MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter></StrictMode>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    expect(screen.getByLabelText("Profile")).toBeInTheDocument();
    releaseDuplicate?.(initial);
    await waitFor(() => expect(workspace).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Profile")).toBeInTheDocument();
    expect(screen.getByText(/有未保存修改/)).toBeInTheDocument();
  });

  it("preserves edits made while an earlier revision is saving", async () => {
    mockData();
    let releaseSave!: (value: GoldenWorkspace) => void;
    save.mockImplementationOnce(() => new Promise((resolve) => { releaseSave = resolve; }));
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={gateTemplate} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    fireEvent.change(screen.getByLabelText("动作细分（可选）"), { target: { value: "late-edit" } });
    releaseSave({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/当前草稿仍需再保存一次/));
    expect(screen.getByLabelText("动作细分（可选）")).toHaveValue("late-edit");
    expect(screen.getByText(/有未保存修改/)).toBeInTheDocument();
  });

  it("renders policy guidance defaults for a legacy gate template", async () => {
    mockData();
    render(<MemoryRouter><GoldenAnnotationWorkspace gateTemplate={{ gate: "G1", status: "not-run", required_new_events: 36 } as never} /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("golden-gate-guidance")).toHaveTextContent("golden-gate-policy.v1 (legacy evidence); G1 36/36; G2 60-80; Pose not versioned in legacy evidence"));
  });
});
