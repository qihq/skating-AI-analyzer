import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, Link } from "react-router-dom";
import LocalAnalysisRoute from "./LocalAnalysisRoute";
import { fetchAnalysis, fetchAnalysisPose, retryAnalysis } from "../api/client";
vi.mock("../api/client", () => ({fetchAnalysis: vi.fn(), fetchAnalysisPose: vi.fn(), retryAnalysis: vi.fn()}));

const WARNING = "证据不足，暂不能自动区分跳跃和旋转。当前选择仅用于分析路由，不能确认动作类型、周数或单跳/连跳。";

function show(path = "/analysis/synthetic") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/analysis/:id" element={<LocalAnalysisRoute><p>normal presenter</p></LocalAnalysisRoute>} />
        <Route path="/report/:id" element={<LocalAnalysisRoute><p>normal presenter</p></LocalAnalysisRoute>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchAnalysisPose).mockResolvedValue({frames: [], frame_urls: {}, connections: []});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok:true, json:async () => ({profile:"legacy-analysis-preview"})}));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("local result route", () => {
  it.each(["/analysis/synthetic", "/report/synthetic"])("loads saved pose through native %s without changing the report", async (path) => {
    vi.mocked(fetchAnalysis).mockResolvedValue({id: "synthetic", status: "completed", report: {summary: "保存的报告", profile_warning: WARNING}} as never);
    show(path);
    await waitFor(() => expect(fetchAnalysisPose).toHaveBeenCalledWith("synthetic"));
    fireEvent.click(await screen.findByRole("button", {name: "骨架叠加"}));
    expect(screen.getByRole("button", {name: "骨架叠加"})).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("分析视频")).toBeInTheDocument();
    expect(screen.getByText("保存的报告")).toBeInTheDocument();
    expect(retryAnalysis).not.toHaveBeenCalled();
  });
  it("keeps video/report available when the saved pose request fails", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({id: "synthetic", status: "completed", report: {summary: "保存的报告"}} as never);
    vi.mocked(fetchAnalysisPose).mockRejectedValue(new Error("pose offline"));
    show();
    expect(await screen.findByText(/读取保存姿态失败/)).toBeInTheDocument();
    expect(screen.getByLabelText("分析视频")).toBeInTheDocument();
    expect(screen.getByText("保存的报告")).toBeInTheDocument();
  });
  it("discards late pose responses after switching record IDs", async () => {
    let finishOld!: (value: never) => void;
    vi.mocked(fetchAnalysis).mockImplementation(async id => ({id, status: "completed"}) as never);
    vi.mocked(fetchAnalysisPose).mockImplementation(id => id === "old" ? new Promise(resolve => {finishOld = resolve;}) : Promise.reject(new Error("new unavailable")));
    render(<MemoryRouter initialEntries={["/analysis/old"]}><Link to="/analysis/new">另一条记录</Link><Routes><Route path="/analysis/:id" element={<LocalAnalysisRoute><p>normal</p></LocalAnalysisRoute>} /></Routes></MemoryRouter>);
    await waitFor(() => expect(fetchAnalysisPose).toHaveBeenCalledWith("old"));
    fireEvent.click(screen.getByText("另一条记录"));
    expect(await screen.findByText(/读取保存姿态失败/)).toBeInTheDocument();
    finishOld({frames: [{frame: "old.jpg", keypoints: []}], connections: [], frame_urls: {}} as never);
    await waitFor(() => expect(screen.getByText(/读取保存姿态失败/)).toBeInTheDocument());
    expect(document.querySelector('img[src*="old"]')).toBeNull();
  });
  it("shows an appended native summary warning exactly once", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic", status: "completed",
      report: { summary: "本地结果已保存。 " + WARNING, profile_warning: WARNING },
      bio_data: { profile_warning: WARNING },
    } as never);
    show("/report/synthetic");
    expect(await screen.findByTestId("profile-evidence-warning")).toHaveTextContent(WARNING);
    expect(screen.getByText("本地结果已保存。")).toBeInTheDocument();
    expect(document.body.textContent?.split(WARNING)).toHaveLength(2);
  });
  it("reopens saved evidence without a default score", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({id:"synthetic", status:"completed", report:{summary:"未找到人物目标", local_execution:{pose:false}}} as never);
    show();
    expect(await screen.findByText("未找到人物目标")).toBeInTheDocument();
    expect(screen.getByText("pose：未执行")).toBeInTheDocument();
    expect(screen.queryByText("normal presenter")).not.toBeInTheDocument();
    expect(document.querySelector("video")?.getAttribute("src")).toBe("/api/analysis/synthetic/video");
  });

  it("plays the ready transcode instead of the HEVC original", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({id:"synthetic", status:"completed", report:{summary:"转码可播放"}, media_manifest:{schema_version:"analysis_media.v1", status:"ready", sources:[
      {quality:"original", status:"ready", width:720, height:1280, url:"/api/analysis/synthetic/video", filename:"source.mov", error:null},
      {quality:"720p", status:"ready", width:720, height:1280, url:"/api/analysis/synthetic/media/720p.mp4", filename:"720p.mp4", error:null},
      {quality:"1080p", status:"failed", width:1080, height:1920, url:"/api/analysis/synthetic/media/1080p.mp4", filename:"1080p.mp4", error:"transcode failed"}
    ]}} as never);
    show();
    expect(await screen.findByText("转码可播放")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector("video")?.getAttribute("src")).toBe("/api/analysis/synthetic/media/720p.mp4"));
  });

  it("shows the backend bio profile warning on the analysis route without relying on summary", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic",
      status: "completed",
      report: { summary: "旧摘要可能未反映分类不确定", local_execution: { pose: true } },
      bio_data: { profile_warning: WARNING },
    } as never);
    show();
    const warning = await screen.findByTestId("profile-evidence-warning");
    expect(warning).toHaveAttribute("role", "status");
    expect(warning).toHaveAccessibleName("分类不确定提示");
    expect(warning).toHaveTextContent("证据不足，暂不能自动区分跳跃和旋转。");
    expect(warning).toHaveTextContent("不能确认动作类型、周数或单跳/连跳。");
    expect(screen.getByText("旧摘要可能未反映分类不确定")).toBeInTheDocument();
    expect(screen.getByText("pose：已执行")).toBeInTheDocument();
  });

  it("shows the warning on the report route and prefers report.profile_warning", async () => {
    const reportWarning = "报告提示：本次证据不足，动作类别尚未确认。";
    const bioWarning = "生物力学提示：旋转周数无法确认。";
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic",
      status: "completed",
      report: { summary: "报告摘要", profile_warning: reportWarning },
      bio_data: { profile_warning: bioWarning },
    } as never);
    show("/report/synthetic");
    const warning = await screen.findByTestId("profile-evidence-warning");
    expect(warning).toHaveTextContent(reportWarning);
    expect(warning).not.toHaveTextContent(bioWarning);
    expect(screen.getByText("报告摘要")).toBeInTheDocument();
  });

  it("shows the bio warning on the report route when the report has no warning", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic",
      status: "completed",
      report: { summary: "报告页摘要" },
      bio_data: { profile_warning: WARNING },
    } as never);
    show("/report/synthetic");
    expect(await screen.findByTestId("profile-evidence-warning")).toHaveTextContent(WARNING);
    expect(screen.getByText("报告页摘要")).toBeInTheDocument();
  });

  it("renders only one warning when report and bio warnings are identical", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic",
      status: "completed",
      report: { summary: "去重摘要", profile_warning: WARNING },
      bio_data: { profile_warning: WARNING },
    } as never);
    show();
    expect(await screen.findAllByText(WARNING)).toHaveLength(1);
    expect(screen.getByTestId("profile-evidence-warning")).toHaveTextContent(WARNING);
  });

  it("leaves legacy records without warning fields compatible", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic",
      status: "completed",
      report: { summary: "旧记录结果", local_execution: { pose: false } },
      bio_data: { jump_metrics_status: "ok" },
    } as never);
    show();
    expect(await screen.findByText("旧记录结果")).toBeInTheDocument();
    expect(screen.queryByTestId("profile-evidence-warning")).not.toBeInTheDocument();
    expect(screen.getByText("pose：未执行")).toBeInTheDocument();
  });

  it("hides blank warning fields", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic",
      status: "completed",
      report: { summary: "仅摘要", profile_warning: "   " },
      bio_data: { profile_warning: "\n\t" },
    } as never);
    show("/report/synthetic");
    expect(await screen.findByText("仅摘要")).toBeInTheDocument();
    expect(screen.queryByTestId("profile-evidence-warning")).not.toBeInTheDocument();
  });

  it("shows the warning after retrying the same failed record succeeds", async () => {
    vi.mocked(fetchAnalysis)
      .mockResolvedValueOnce({ id: "synthetic", status: "failed", error_message: "任务中断" } as never)
      .mockResolvedValueOnce({
        id: "synthetic",
        status: "completed",
        report: { summary: "同一条记录重试完成", profile_warning: WARNING },
      } as never);
    vi.mocked(retryAnalysis).mockResolvedValue({} as never);
    show();
    fireEvent.click(await screen.findByText("重试同一条记录"));
    await waitFor(() => expect(retryAnalysis).toHaveBeenCalledWith("synthetic"));
    expect(await screen.findByText("同一条记录重试完成")).toBeInTheDocument();
    const warning = screen.getByTestId("profile-evidence-warning");
    expect(warning).toHaveTextContent("不能确认动作类型、周数或单跳/连跳。");
    expect(fetchAnalysis).toHaveBeenCalledTimes(2);
  });

  it("does not invent a warning from an internal profile or action label", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({
      id: "synthetic",
      status: "completed",
      analysis_profile: "spin",
      action_type: "spin",
      report: { summary: "已确认摘要", action_confirmation: { action_family: "spin" } },
      bio_data: { jump_metrics_status: "ok" },
    } as never);
    show();
    expect(await screen.findByText("已确认摘要")).toBeInTheDocument();
    expect(screen.queryByTestId("profile-evidence-warning")).not.toBeInTheDocument();
  });

  it("retries the existing record", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({id:"synthetic",status:"failed",error_message:"任务中断"} as never);
    vi.mocked(retryAnalysis).mockResolvedValue({} as never);
    show(); fireEvent.click(await screen.findByText("重试同一条记录"));
    await waitFor(() => expect(retryAnalysis).toHaveBeenCalledWith("synthetic"));
    await waitFor(() => expect(fetchAnalysis).toHaveBeenCalledTimes(2));
  });

  it("offers target confirmation", async () => {
    vi.mocked(fetchAnalysis).mockResolvedValue({id:"synthetic",status:"awaiting_target_selection"} as never);
    show(); expect(await screen.findByText("确认主滑行者并继续")).toHaveAttribute("href", "/report/synthetic/target");
  });

  it("keeps the ordinary presenter outside the local profile", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok:true,json:async () => ({profile:"off"})}));
    show(); expect(await screen.findByText("normal presenter")).toBeInTheDocument(); expect(fetchAnalysis).not.toHaveBeenCalled();
  });
});
