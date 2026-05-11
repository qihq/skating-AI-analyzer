import type { AnalysisStatus } from "../api/client";

export const ANALYSIS_IN_PROGRESS_STATUSES: AnalysisStatus[] = [
  "pending",
  "processing",
  "extracting_frames",
  "awaiting_target_selection",
  "analyzing",
  "generating_report",
];

export function isAnalysisInProgress(status: AnalysisStatus | string | null | undefined): boolean {
  return Boolean(status && ANALYSIS_IN_PROGRESS_STATUSES.includes(status as AnalysisStatus));
}

export function getAnalysisStatusLabel(status: AnalysisStatus | string): string {
  switch (status) {
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    case "extracting_frames":
      return "提取画面中";
    case "awaiting_target_selection":
      return "等待确认主滑行者";
    case "analyzing":
      return "AI 分析中";
    case "generating_report":
      return "生成报告中";
    case "processing":
      return "分析中";
    case "pending":
    default:
      return "待处理";
  }
}

export function getAnalysisStageDescription(status: AnalysisStatus | string | null | undefined): string {
  switch (status) {
    case "pending":
      return "任务已入队，正在准备分析环境。";
    case "processing":
      return "分析流程已启动，正在进入首个处理阶段。";
    case "extracting_frames":
      return "正在抽取关键帧，并尝试锁定主滑行者。";
    case "awaiting_target_selection":
      return "自动锁定置信度不足，等待确认主滑行者后继续。";
    case "analyzing":
      return "关键帧已送入视觉模型，正在生成结构化观察。";
    case "generating_report":
      return "视觉结果与生物力学指标已就绪，正在汇总报告。";
    case "completed":
      return "分析已完成，可以查看完整报告。";
    case "failed":
      return "分析已中断，请查看调试日志或重试。";
    default:
      return "正在同步分析状态。";
  }
}

export function getAnalysisProcessingStage(status: AnalysisStatus | string | null | undefined): number {
  switch (status) {
    case "pending":
    case "processing":
    case "extracting_frames":
    case "awaiting_target_selection":
      return 1;
    case "analyzing":
      return 2;
    case "generating_report":
      return 3;
    case "completed":
      return 4;
    default:
      return 0;
  }
}
