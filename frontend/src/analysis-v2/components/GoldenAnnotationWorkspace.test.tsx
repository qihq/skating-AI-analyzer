import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { useAppMode } from "../../components/AppModeContext";
import { deleteGoldenSource, fetchGoldenReviewQueue, fetchGoldenSourceFrame, fetchGoldenSourceMediaUrl, fetchGoldenWorkspace, saveGoldenAnnotations } from "../api";
import type { GoldenEvent, GoldenWorkspace } from "../golden-contracts";
import GoldenAnnotationWorkspace from "./GoldenAnnotationWorkspace";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({ fetchGoldenWorkspace: vi.fn(), fetchGoldenReviewQueue: vi.fn(), fetchGoldenSourceFrame: vi.fn(), fetchGoldenSourceMediaUrl: vi.fn(), saveGoldenAnnotations: vi.fn(), importGoldenSource: vi.fn(), attestGoldenReview: vi.fn(), updateGoldenSource: vi.fn(), deleteGoldenSource: vi.fn() }));
vi.mock("../../media/IceMediaPlayer", () => ({ IceMediaPlayer: (props: { className?: string; onStepSourceFrame: (direction: -1 | 1) => void; onTimeChange?: (value: number) => void; overlay?: unknown; aspectRatio?: number }) => <div data-testid="golden-player" className={props.className}><button onClick={() => props.onStepSourceFrame(1)}>Next source frame</button><button onClick={() => props.onTimeChange?.(0)}>Report stale player time</button><output data-testid="media-aspect-ratio">{props.aspectRatio}</output>{props.overlay as never}</div> }));

const workspace = vi.mocked(fetchGoldenWorkspace);
const review = vi.mocked(fetchGoldenReviewQueue);
const frame = vi.mocked(fetchGoldenSourceFrame);
const save = vi.mocked(saveGoldenAnnotations);

function mockData() {
  vi.clearAllMocks();
  vi.mocked(useAppMode).mockReturnValue({ parentPin: "1234" } as never);
  workspace.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 2, sources: [{ source_sha256: "d".repeat(64), duration_pts: 8, width: 1280, height: 720, source_frame_count: 240, display_rotation_degrees: 0, redacted_alias: "source-001", recording_session_id: "session-01", grouping_id: "group-01" }], events: [], tracks: [], poses: [] });
  review.mockResolvedValue([]); frame.mockResolvedValue({ sourceFrameIndex: 1, pts: .033, duration: .033 }); vi.mocked(fetchGoldenSourceMediaUrl).mockResolvedValue("blob:private-video");
}

describe("GoldenAnnotationWorkspace", () => {
  it("adds an unsaved event and keeps a source-frame PTS control available", async () => {
    mockData(); render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
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
      render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
      fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
      expect(screen.getByLabelText("Profile")).toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent(/动作草稿已创建/);
    } finally {
      Object.defineProperty(globalThis, "crypto", { configurable: true, value: originalCrypto });
    }
  });

  it("locks the nearest source frame before enabling box drawing", async () => {
    mockData(); render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /锁定当前画面并画主滑手框/ }));
    await waitFor(() => expect(frame).toHaveBeenCalledWith("1234", "d".repeat(64), 0));
    expect(await screen.findByRole("alert")).toHaveTextContent(/已锁定第 1 帧/);
    expect(screen.getByRole("button", { name: /正在等待画框/ })).toBeInTheDocument();
  });

  it("keeps a returned exact frame when the player reports its stale pre-seek time", async () => {
    mockData(); frame.mockResolvedValue({ sourceFrameIndex: 48, pts: 1.6, duration: .033 });
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(screen.getByText(/当前时间 1\.600000 秒；源帧 48/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Report stale player time" }));
    expect(screen.getByText(/当前时间 1\.600000 秒；源帧 48/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/已定位到第 48 帧/);
  });

  it("does not claim confirmation after a failed save", async () => {
    mockData(); save.mockRejectedValue(new Error("offline")); render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: /新建动作/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Save failed/));
  });

  it("captures a jump moment from the exact returned source frame and sends it as Ground Truth", async () => {
    mockData(); save.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
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
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
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
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
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

  it("explains the required workflow and deletes a source only after confirmation", async () => {
    mockData(); vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(deleteGoldenSource).mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("上传以后做什么？")).toBeInTheDocument());
    expect(screen.getByText(/普通事件最少要标/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /删除此视频和标签/ }));
    await waitFor(() => expect(deleteGoldenSource).toHaveBeenCalledWith("1234", "d".repeat(64), expect.objectContaining({ confirmation: "delete_source_and_labels" })));
  });

  it("supports pointer drawing for a main-skater box", async () => {
    mockData(); render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
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
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
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
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
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
    render(<StrictMode><MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter></StrictMode>);
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
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: /新建动作/i }));
    fireEvent.click(screen.getByRole("button", { name: /保存人工真值/i }));
    fireEvent.change(screen.getByLabelText("动作细分（可选）"), { target: { value: "late-edit" } });
    releaseSave({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/当前草稿仍需再保存一次/));
    expect(screen.getByLabelText("动作细分（可选）")).toHaveValue("late-edit");
    expect(screen.getByText(/有未保存修改/)).toBeInTheDocument();
  });
});
