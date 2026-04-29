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
