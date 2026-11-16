import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import axios, { type AxiosResponse } from "axios";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppModeProvider, useAppMode } from "../components/AppModeContext";
import { uploadAnalysis as uploadAnalysisMock } from "../api/client";
import type { Skater, SkillNode, TrainingSessionRecord } from "../api/client";
import { fetchAnalysisExperienceV2Diagnostic, fetchEventProposals } from "../analysis-v2/api";
import ReviewPage from "./ReviewPage";
import { readVideoDuration } from "../utils/videoMetadata";

vi.mock("../components/AppModeContext", () => ({
  AppModeProvider: ({ children }: { children: ReactNode }) => children,
  useAppMode: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchSkaters: vi.fn(),
  fetchSkaterSkills: vi.fn(),
  fetchTrainingSessions: vi.fn(),
  fetchAnalysis: vi.fn(),
  createTrainingSession: vi.fn(),
  uploadAnalysis: vi.fn(),
  fetchHasPin: vi.fn().mockResolvedValue({ has_pin: false, pin_length: 4 }),
  verifyPin: vi.fn(),
  createMonthlyChapterFacts: vi.fn(),
  fetchMonthlyChapters: vi.fn(),
  generateMonthlyChapter: vi.fn(),
  patchMonthlyChapter: vi.fn(),
  publishMonthlyChapter: vi.fn(),
}));

vi.mock("../analysis-v2/api", () => ({
  fetchAnalysisExperienceV2Diagnostic: vi.fn(),
  fetchEventProposals: vi.fn(),
  mutateEventProposals: vi.fn(),
}));

// jsdom never fires media metadata events, so the duration read is mocked with a
// never-settling default. Race tests below replace it with deferred promises.
vi.mock("../utils/videoMetadata", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../utils/videoMetadata")>();
  return {
    ...actual,
    readVideoDuration: vi.fn(() => new Promise<number>(() => {})),
  };
});

const skaters = [{ id: "skater-1", name: "tantan", display_name: "坦坦", is_default: true }] as Skater[];
const skills: SkillNode[] = [];
const sessions: TrainingSessionRecord[] = [];

describe("ReviewPage highlight quote", () => {
  beforeEach(async () => {
    vi.mocked(useAppMode).mockReturnValue({ isParentMode: false, parentPin: null, childView: "tantan", setChildView: vi.fn() } as never);
    const client = await import("../api/client");
    vi.mocked(client.fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(client.fetchSkaterSkills).mockResolvedValue(skills);
    vi.mocked(client.fetchTrainingSessions).mockResolvedValue(sessions);
    vi.mocked(client.uploadAnalysis).mockResolvedValue({ id: "analysis-1", status: "pending" } as never);
    vi.mocked(client.uploadAnalysis).mockClear();
    vi.mocked(fetchEventProposals).mockReset();
    vi.mocked(fetchAnalysisExperienceV2Diagnostic).mockReset();
  });

  it("appends highlight_quote and quote_speaker=skater to FormData on submit", async () => {
    render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    await screen.findByText("开始诊断");

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["x"], "source.mp4", { type: "video/mp4" })] },
    });

    const quoteTextarea = screen.getByPlaceholderText("比如：我今天敢往后滑了。") as HTMLTextAreaElement;
    fireEvent.change(quoteTextarea, { target: { value: "我今天敢往后滑了" } });

    const speakerSelect = screen.getByRole("combobox", { name: "金句说话人" }) as HTMLSelectElement;
    fireEvent.change(speakerSelect, { target: { value: "skater" } });

    fireEvent.click(screen.getByRole("button", { name: "开始诊断" }));

    await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalled());

    const captured = vi.mocked(uploadAnalysisMock).mock.calls[0][0] as FormData;
    expect(captured.get("highlight_quote")).toBe("我今天敢往后滑了");
    expect(captured.get("quote_speaker")).toBe("skater");
  });

  it("omits quote fields when the quote is empty", async () => {
    render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    await screen.findByText("开始诊断");

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["x"], "source.mp4", { type: "video/mp4" })] },
    });

    fireEvent.click(screen.getByRole("button", { name: "开始诊断" }));

    await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalled());

    const captured = vi.mocked(uploadAnalysisMock).mock.calls[0][0] as FormData;
    expect(captured.get("highlight_quote")).toBeNull();
    expect(captured.get("quote_speaker")).toBeNull();
  });

  it("选择视频后即显示可选时间区间，即使无法读取时长", async () => {
    render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    await screen.findByText("开始诊断");
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(["x"], "source.mp4", { type: "video/mp4" })] },
    });

    expect(await screen.findByText("AI 输入片段（可选）")).toBeInTheDocument();
  });

  it("shows ambiguous rotation definition and exact PTS in parent review", async () => {
    vi.mocked(useAppMode).mockReturnValue({ isParentMode: true, parentPin: "1234", childView: "tantan", setChildView: vi.fn() } as never);
    vi.mocked(fetchEventProposals).mockResolvedValue({
      schema_version: "event-proposal-collection.v1",
      source_video_hash: "source",
      source_duration_sec: 3,
      pipeline_fingerprint: "pipeline",
      proposals: [{ event_id: "event-1", source_video_hash: "source", start_pts: 1, end_pts: 2, anchor_start_frame: 30, anchor_end_frame: 60, candidate_profile_scores: { jump: .8 }, proposed_profile: "unknown", status: "pending_confirmation", tracking_coverage: .9, pose_coverage: .8, observability: "partially_observable", evidence_sources: ["source_pts"], provenance_fingerprint: "proposal", revision: 1, parent_event_ids: [], superseded_event_ids: [] }],
      diagnostic_only: true,
      classifier_labels_consumed: false,
      revision: 1,
    });
    vi.mocked(fetchAnalysisExperienceV2Diagnostic).mockResolvedValue({
      schemaVersion: "analysis-experience.v2",
      analysisId: "analysis-1",
      authority: "v2",
      pipelineMode: "v2",
      sourcePipelineFingerprint: "pipeline",
      diagnosticOnly: true,
      familyUsable: false,
      claims: [],
      events: [{ eventId: "event-1", profile: "jump", subtype: "axel", state: "ambiguous", startPts: 1, endPts: 2, status: "uncertain", observability: "partially_observable" }],
      reviewTasks: [{ taskId: "rotation:event-1", authority: "v2", kind: "confirm_rotation_estimate", eventId: "event-1", startPts: 1.234, endPts: 1.567, definitionVersion: "airborne-body-rotation.source-pts.v1", convention: "airborne_body_rotation" }],
    });

    render(
      <MemoryRouter initialEntries={["/review?proposal_analysis_id=analysis-1"]}>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/标签定义：空中身体转体/)).toHaveTextContent("PTS 1.234–1.567");
    expect(screen.getByRole("link", { name: "打开精确时间复核" })).toHaveAttribute("href", "/analysis/analysis-1?view=moments&event=event-1&t=1.234");
  });
});

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

describe("ReviewPage video duration race", () => {
  const createFile = (name: string) => new File(["x"], name, { type: "video/mp4" });

  function renderReviewPage() {
    return render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );
  }

  function selectFile(file: File) {
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });
    return fileInput;
  }

  beforeEach(async () => {
    vi.mocked(useAppMode).mockReturnValue({ isParentMode: false, parentPin: null, childView: "tantan", setChildView: vi.fn() } as never);
    const client = await import("../api/client");
    vi.mocked(client.fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(client.fetchSkaterSkills).mockResolvedValue(skills);
    vi.mocked(client.fetchTrainingSessions).mockResolvedValue(sessions);
    vi.mocked(client.fetchAnalysis).mockResolvedValue({ id: "analysis-1", status: "pending" } as never);
    vi.mocked(client.uploadAnalysis).mockResolvedValue({ id: "analysis-1", status: "pending" } as never);
    vi.mocked(client.uploadAnalysis).mockClear();
    vi.mocked(fetchEventProposals).mockReset();
    vi.mocked(fetchAnalysisExperienceV2Diagnostic).mockReset();
    vi.mocked(readVideoDuration).mockReset();
    vi.mocked(readVideoDuration).mockImplementation(() => new Promise<number>(() => {}));
  });

  it("keeps the newest duration when the previous read resolves late", async () => {
    const fileA = createFile("a.mp4");
    const fileB = createFile("b.mp4");
    const readA = createDeferred<number>();
    const readB = createDeferred<number>();
    vi.mocked(readVideoDuration).mockImplementation((file) => (file === fileA ? readA.promise : readB.promise));

    renderReviewPage();
    await screen.findByText("开始诊断");

    selectFile(fileA);
    selectFile(fileB);

    await act(async () => {
      readB.resolve(100);
      await readB.promise;
    });
    expect(await screen.findByText("视频时长：100.00s")).toBeInTheDocument();

    await act(async () => {
      readA.resolve(10);
      await readA.promise;
    });

    // The late 10s result from file A must not replace file B's 100s.
    expect(screen.getByText("视频时长：100.00s")).toBeInTheDocument();
    expect(screen.queryByText("视频时长：10.00s")).not.toBeInTheDocument();

    // A 50–80s window is valid for file B; the stale 10s duration would reject it.
    fireEvent.change(screen.getByLabelText("开始秒数"), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText("结束秒数"), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "开始诊断" }));

    await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("结束时间不能超过视频总时长。")).not.toBeInTheDocument();
    const captured = vi.mocked(uploadAnalysisMock).mock.calls[0][0] as FormData;
    expect(captured.get("manual_action_window_start_sec")).toBe("50");
    expect(captured.get("manual_action_window_end_sec")).toBe("80");
  });

  it("keeps the newest duration when the previous read rejects late", async () => {
    const fileA = createFile("a.mp4");
    const fileB = createFile("b.mp4");
    const readA = createDeferred<number>();
    const readB = createDeferred<number>();
    vi.mocked(readVideoDuration).mockImplementation((file) => (file === fileA ? readA.promise : readB.promise));

    renderReviewPage();
    await screen.findByText("开始诊断");

    selectFile(fileA);
    selectFile(fileB);

    await act(async () => {
      readB.resolve(100);
      await readB.promise;
    });
    expect(await screen.findByText("视频时长：100.00s")).toBeInTheDocument();

    await act(async () => {
      readA.reject(new Error("video_metadata_unavailable"));
      await readA.promise.catch(() => undefined);
    });

    // File A's late failure must not null out file B's duration.
    expect(screen.getByText("视频时长：100.00s")).toBeInTheDocument();
    expect(screen.queryByText("视频时长暂不可用，仍可填写；提交时会校验范围。")).not.toBeInTheDocument();

    // 120–150s exceeds file B's 100s and must still be blocked by the window check.
    fireEvent.change(screen.getByLabelText("开始秒数"), { target: { value: "120" } });
    fireEvent.change(screen.getByLabelText("结束秒数"), { target: { value: "150" } });
    fireEvent.click(screen.getByRole("button", { name: "开始诊断" }));

    expect(await screen.findByText("结束时间不能超过视频总时长。")).toBeInTheDocument();
    expect(uploadAnalysisMock).not.toHaveBeenCalled();
  });

  it("does not revive a duration after the file selection is cleared", async () => {
    const fileA = createFile("a.mp4");
    const readA = createDeferred<number>();
    vi.mocked(readVideoDuration).mockImplementation(() => readA.promise);

    renderReviewPage();
    await screen.findByText("开始诊断");

    const fileInput = selectFile(fileA);
    fireEvent.change(fileInput, { target: { files: [] } });

    await act(async () => {
      readA.resolve(100);
      await readA.promise;
    });

    expect(screen.queryByText("视频时长：100.00s")).not.toBeInTheDocument();
    expect(screen.queryByText("AI 输入片段（可选）")).not.toBeInTheDocument();
    expect(screen.getAllByText("尚未选择视频").length).toBeGreaterThan(0);
    expect(uploadAnalysisMock).not.toHaveBeenCalled();
  });
});

function createUploadAxiosError(status: number, data: unknown, code = "ERR_BAD_REQUEST") {
  const response = { data, status, statusText: "", headers: {}, config: {} } as unknown as AxiosResponse;
  return new axios.AxiosError(`Request failed with status code ${status}`, code, undefined, undefined, response);
}

describe("ReviewPage upload failure recovery", () => {
  const createFile = (name: string) => new File(["x"], name, { type: "video/mp4" });

  function renderReviewPage() {
    return render(
      <MemoryRouter>
        <AppModeProvider>
          <ReviewPage />
        </AppModeProvider>
      </MemoryRouter>,
    );
  }

  function selectFile(file: File) {
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });
    return fileInput;
  }

  function submitUpload() {
    fireEvent.click(screen.getByRole("button", { name: "开始诊断" }));
  }

  beforeEach(async () => {
    vi.mocked(useAppMode).mockReturnValue({ isParentMode: false, parentPin: null, childView: "tantan", setChildView: vi.fn() } as never);
    const client = await import("../api/client");
    vi.mocked(client.fetchSkaters).mockResolvedValue(skaters);
    vi.mocked(client.fetchSkaterSkills).mockResolvedValue(skills);
    vi.mocked(client.fetchTrainingSessions).mockResolvedValue(sessions);
    vi.mocked(client.fetchAnalysis).mockResolvedValue({ id: "analysis-1", status: "pending" } as never);
    vi.mocked(client.uploadAnalysis).mockResolvedValue({ id: "analysis-1", status: "pending" } as never);
    vi.mocked(client.uploadAnalysis).mockClear();
    vi.mocked(fetchEventProposals).mockReset();
    vi.mocked(fetchAnalysisExperienceV2Diagnostic).mockReset();
    vi.mocked(readVideoDuration).mockReset();
    vi.mocked(readVideoDuration).mockImplementation(() => new Promise<number>(() => {}));
  });

  it("shows detail.message with the backend code for a structured upload error", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(
      createUploadAxiosError(400, { detail: { code: "VIDEO_FORMAT_INVALID", message: "视频编码不支持，请转成 H.264" } }),
    );

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("bad.mp4"));
    submitUpload();

    expect(await screen.findByText("视频编码不支持，请转成 H.264（VIDEO_FORMAT_INVALID）")).toBeInTheDocument();
  });

  it("shows a plain string detail from the backend", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(createUploadAxiosError(409, { detail: "同一视频正在处理中，请稍后再试。" }));

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    submitUpload();

    expect(await screen.findByText("同一视频正在处理中，请稍后再试。")).toBeInTheDocument();
  });

  it("joins FastAPI 422 validation details into a readable message", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(
      createUploadAxiosError(422, {
        detail: [
          { loc: ["body", "file"], msg: "文件格式不支持", type: "value_error" },
          { loc: ["body", "action_type"], msg: "缺少动作大类", type: "value_error.missing" },
        ],
      }),
    );

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    submitUpload();

    expect(await screen.findByText("body.file: 文件格式不支持；body.action_type: 缺少动作大类")).toBeInTheDocument();
  });

  it("falls back to a readable HTTP message instead of [object Object] for unknown payloads", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(
      createUploadAxiosError(500, { detail: { nested: { unexpected: true } } }, "ERR_BAD_RESPONSE"),
    );

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    submitUpload();

    expect(await screen.findByText("上传失败（HTTP 500），请稍后重试。")).toBeInTheDocument();
    expect(screen.queryByText(/\[object Object\]/)).not.toBeInTheDocument();
  });

  it("uses an HTTP fallback for a non-JSON HTML error body", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(
      createUploadAxiosError(502, "<html><body><h1>Bad Gateway</h1><p>upstream down</p></body></html>", "ERR_BAD_RESPONSE"),
    );

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    submitUpload();

    expect(await screen.findByText("上传失败（HTTP 502），请稍后重试。")).toBeInTheDocument();
    expect(screen.queryByText(/Bad Gateway/)).not.toBeInTheDocument();
  });

  it("asks to check records when a 2xx upload response is unreadable", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(createUploadAxiosError(202, { message: "ok" }, "ERR_BAD_RESPONSE"));
    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    submitUpload();
    expect(await screen.findByText(/无法识别的响应（HTTP 202）/)).toHaveTextContent("先到记录列表确认");
    expect(screen.getByRole("button", { name: "开始诊断" })).toBeEnabled();
  });

  it("gives an actionable hint for network failures without claiming no record was created", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(new axios.AxiosError("Network Error", "ERR_NETWORK"));

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    submitUpload();

    const hint = await screen.findByText(/网络连接中断/);
    expect(hint).toHaveTextContent(/后端服务/);
    expect(hint).toHaveTextContent(/可能/);
    expect(hint).toHaveTextContent(/记录/);
  });

  it("gives an actionable hint for upload timeouts", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(new axios.AxiosError("Timeout", "ECONNABORTED"));

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    submitUpload();

    const hint = await screen.findByText(/上传超时/);
    expect(hint).toHaveTextContent(/记录/);
  });

  it("allows resubmitting after a failure and keeps the selected file and window", async () => {
    vi.mocked(uploadAnalysisMock).mockRejectedValueOnce(createUploadAxiosError(400, { detail: "视频太短，请重新选择。" }));
    vi.mocked(readVideoDuration).mockResolvedValueOnce(100);

    renderReviewPage();
    await screen.findByText("开始诊断");
    selectFile(createFile("run.mp4"));
    expect(await screen.findByText("视频时长：100.00s")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("开始秒数"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("结束秒数"), { target: { value: "2" } });
    submitUpload();

    expect(await screen.findByText("视频太短，请重新选择。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始诊断" })).toBeEnabled();
    expect(screen.getAllByText("run.mp4").length).toBeGreaterThan(0);
    expect((screen.getByLabelText("开始秒数") as HTMLInputElement).value).toBe("1");
    expect((screen.getByLabelText("结束秒数") as HTMLInputElement).value).toBe("2");

    vi.mocked(uploadAnalysisMock).mockResolvedValueOnce({ id: "analysis-2", status: "pending" } as never);
    submitUpload();

    await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("正在生成分析结果")).toBeInTheDocument();
    expect(screen.queryByText("视频太短，请重新选择。")).not.toBeInTheDocument();

    const retryForm = vi.mocked(uploadAnalysisMock).mock.calls[1][0] as FormData;
    expect(retryForm.get("manual_action_window_start_sec")).toBe("1");
    expect(retryForm.get("manual_action_window_end_sec")).toBe("2");
  });
});
