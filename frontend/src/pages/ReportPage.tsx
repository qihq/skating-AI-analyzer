import axios from "axios";
import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  AnalysisDetail,
  createPlan,
  deleteAnalysis,
  dismissMemorySuggestion,
  fetchAnalysis,
  fetchAnalysisPlan,
  fetchAnalysisPose,
  fetchMemorySuggestions,
  fetchSkaterSkills,
  fetchSkaters,
  MemorySuggestion,
  PoseResponse,
  retryAnalysis,
  Skater,
  SkillNode,
} from "../api/client";
import { getAnalysisErrorMessage } from "../constants/analysisErrors";
import AnalysisQualityPanel from "../components/AnalysisQualityPanel";
import AnalysisDebugLogPanel from "../components/AnalysisDebugLogPanel";
import BiomechanicsPanel from "../components/BiomechanicsPanel";
import DeleteAnalysisModal from "../components/DeleteAnalysisModal";
import ForceScoreRing from "../components/ForceScoreRing";
import ParentPinVerifyModal from "../components/ParentPinVerifyModal";
import PoseViewer from "../components/PoseViewer";
import ReportCard from "../components/ReportCard";
import RetryAnalysisConfirmSheet from "../components/RetryAnalysisConfirmSheet";
import UnlockCelebration from "../components/UnlockCelebration";
import { useAppMode } from "../components/AppModeContext";
import { getAnalysisProcessingStage, getAnalysisStageDescription, getAnalysisStatusLabel, isAnalysisInProgress } from "../constants/analysisStatus";
import { apiDateTimeFormatter, parseApiDate } from "../utils/datetime";
import ZodiacAvatar from "../components/ZodiacAvatar";

declare global {
  interface Window {
    ClipboardItem?: typeof ClipboardItem;
  }
}

const STATUS_TEXT: Record<string, string> = {
  pending: "冰宝（IceBuddy）已收到视频，正在准备分析环境…",
  processing: "冰宝（IceBuddy）正在分析，通常需要 1-2 分钟…",
};

const ISSUE_STYLES: Record<string, string> = {
  high: "border-rose-200 bg-rose-50",
  medium: "border-amber-200 bg-amber-50",
  low: "border-sky-200 bg-sky-50",
};

const SUBSCORE_LABELS: Record<string, string> = {
  takeoff_power: "起跳发力",
  rotation_axis: "旋转轴心",
  arm_coordination: "手臂配合",
  landing_absorption: "落冰缓冲",
  core_stability: "核心稳定",
};

const DATA_QUALITY_LABELS: Record<string, string> = {
  good: "完整",
  partial: "部分可用",
  poor: "较弱",
};

const RADAR_VIEWBOX_SIZE = 300;
const RADAR_CENTER = RADAR_VIEWBOX_SIZE / 2;
const RADAR_RADIUS = 88;
const RADAR_LABEL_RADIUS = 122;
const RADAR_LEVELS = 4;

type SuggestionPreview = {
  suggestionId: string;
  index: number;
  title: string;
};

type ShareImagePreview = {
  url: string;
  blob: Blob;
  filename: string;
  copiedToClipboard: boolean;
};

const PROGRESS_STAGE_META = [
  { key: "extract_frames", label: "抽帧与锁定" },
  { key: "vision", label: "视觉分析" },
  { key: "report", label: "报告生成" },
  { key: "completed", label: "完成" },
] as const;

function formatDate(dateString: string) {
  return apiDateTimeFormatter({
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(dateString));
}

function formatShortDate(dateString: string) {
  return apiDateTimeFormatter({
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(parseApiDate(dateString));
}

function scoreLevelText(score: number | null | undefined) {
  const normalized = Math.max(0, Math.min(Math.round(score ?? 0), 100));
  if (normalized >= 85) {
    return "状态很稳";
  }
  if (normalized >= 70) {
    return "表现不错";
  }
  if (normalized >= 56) {
    return "持续进步中";
  }
  return "继续找感觉";
}

function scoreStars(score: number | null | undefined) {
  const normalized = Math.max(0, Math.min(Math.round(score ?? 0), 100));
  const stars = normalized >= 85 ? 5 : normalized >= 70 ? 4 : normalized >= 56 ? 3 : normalized >= 40 ? 2 : 1;
  return `${"★".repeat(stars)}${"☆".repeat(5 - stars)}`;
}

function buildSubscoreRadarData(subscores: Record<string, number>) {
  return Object.entries(SUBSCORE_LABELS).map(([key, label]) => ({
    label,
    value: Math.max(0, Math.min(Number(subscores[key] ?? 0), 100)),
  }));
}

function getRadarPoint(angleInDegrees: number, radius: number) {
  const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180;
  return {
    x: RADAR_CENTER + Math.cos(angleInRadians) * radius,
    y: RADAR_CENTER + Math.sin(angleInRadians) * radius,
  };
}

function buildRadarPolygonPoints(length: number, radiusResolver: (index: number) => number) {
  return Array.from({ length }, (_, index) => {
    const point = getRadarPoint((360 / length) * index, radiusResolver(index));
    return `${point.x.toFixed(2)},${point.y.toFixed(2)}`;
  }).join(" ");
}

function flattenSuggestionPreview(items: MemorySuggestion[]): SuggestionPreview[] {
  return items.flatMap((item) =>
    item.suggestions.map((suggestion, index) => {
      const action = String(suggestion.action ?? "").toLowerCase();
      if (action === "add") {
        return {
          suggestionId: item.id,
          index,
          title: String(suggestion.title ?? "发现新记忆"),
        };
      }
      if (action === "update") {
        return {
          suggestionId: item.id,
          index,
          title: String(suggestion.title ?? "建议更新已有记忆"),
        };
      }
      return {
        suggestionId: item.id,
        index,
        title: "建议设为过期",
      };
    }),
  );
}

function normalizeShareText(value: string | null | undefined, fallback: string, maxLength = 92) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) {
    return fallback;
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function wrapCanvasText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines: number) {
  const chars = Array.from(text);
  const lines: string[] = [];
  let current = "";

  for (const char of chars) {
    const next = `${current}${char}`;
    if (ctx.measureText(next).width <= maxWidth || !current) {
      current = next;
      continue;
    }
    lines.push(current);
    current = char;
    if (lines.length >= maxLines) {
      break;
    }
  }

  if (lines.length < maxLines && current) {
    lines.push(current);
  }
  if (lines.length > maxLines) {
    lines.length = maxLines;
  }
  if (lines.length === maxLines && chars.join("").length > lines.join("").length) {
    const last = lines[maxLines - 1];
    lines[maxLines - 1] = `${last.slice(0, Math.max(last.length - 1, 0))}…`;
  }
  return lines;
}

function drawRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const normalizedRadius = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + normalizedRadius, y);
  ctx.arcTo(x + width, y, x + width, y + height, normalizedRadius);
  ctx.arcTo(x + width, y + height, x, y + height, normalizedRadius);
  ctx.arcTo(x, y + height, x, y, normalizedRadius);
  ctx.arcTo(x, y, x + width, y, normalizedRadius);
  ctx.closePath();
}

function drawWrappedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  maxLines: number,
) {
  const lines = wrapCanvasText(ctx, text, maxWidth, maxLines);
  lines.forEach((line, index) => {
    ctx.fillText(line, x, y + index * lineHeight);
  });
  return lines.length * lineHeight;
}

function canvasToBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
        return;
      }
      reject(new Error("share_image_blob_failed"));
    }, "image/png", 0.96);
  });
}

async function copyImageBlobToClipboard(blob: Blob) {
  const ClipboardItemConstructor = window.ClipboardItem;
  if (!navigator.clipboard?.write || !ClipboardItemConstructor) {
    return false;
  }

  try {
    await navigator.clipboard.write([
      new ClipboardItemConstructor({
        [blob.type]: blob,
      }),
    ]);
    return true;
  } catch {
    return false;
  }
}

async function createReportShareImage(analysis: AnalysisDetail) {
  const canvas = document.createElement("canvas");
  const width = 1080;
  const height = 1440;
  const scale = window.devicePixelRatio > 1 ? 2 : 1;
  canvas.width = width * scale;
  canvas.height = height * scale;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("share_image_canvas_failed");
  }
  ctx.scale(scale, scale);

  const report = analysis.report;
  const score = analysis.force_score ?? 0;
  const topIssue = report?.issues?.[0];
  const secondIssue = report?.issues?.[1];
  const topImprovement = report?.improvements?.[0];
  const summary = normalizeShareText(report?.summary, "本次报告已生成，建议结合训练重点继续练习。", 108);
  const focus = normalizeShareText(report?.training_focus, "先把动作做稳，再慢慢加速度。", 76);
  const issueText = normalizeShareText(
    topIssue ? `${topIssue.category}：${topIssue.description}` : null,
    "本次没有识别到明显高风险问题。",
    86,
  );
  const secondIssueText = secondIssue
    ? normalizeShareText(`${secondIssue.category}：${secondIssue.description}`, "", 72)
    : null;
  const improvementText = normalizeShareText(
    topImprovement ? `${topImprovement.target}：${topImprovement.action}` : null,
    "保持低冲击、短时间、多鼓励的练习节奏。",
    86,
  );

  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#F8FBFF");
  gradient.addColorStop(0.5, "#EEF7F4");
  gradient.addColorStop(1, "#FFF7ED");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "rgba(255,255,255,0.86)";
  drawRoundRect(ctx, 64, 64, width - 128, height - 128, 48);
  ctx.fill();
  ctx.strokeStyle = "rgba(148,163,184,0.32)";
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.fillStyle = "#2563EB";
  ctx.font = "700 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("冰宝诊断分享", 112, 142);

  ctx.fillStyle = "#0F172A";
  ctx.font = "800 58px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, analysis.action_type, 112, 230, 520, 66, 2);

  ctx.fillStyle = "#64748B";
  ctx.font = "500 28px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const skaterLabel = analysis.skater_name ? `${analysis.skater_name} · ` : "";
  ctx.fillText(`${skaterLabel}${formatShortDate(analysis.created_at)}`, 112, 336);

  ctx.fillStyle = "#DBEAFE";
  drawRoundRect(ctx, 710, 142, 220, 220, 110);
  ctx.fill();
  ctx.strokeStyle = "#93C5FD";
  ctx.lineWidth = 5;
  ctx.stroke();
  ctx.fillStyle = "#1D4ED8";
  ctx.font = "800 72px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(String(score), 820, 248);
  ctx.font = "700 26px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("Force Score", 820, 292);
  ctx.fillStyle = "#64748B";
  ctx.font = "600 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText(scoreLevelText(score), 820, 326);
  ctx.textAlign = "start";

  ctx.fillStyle = "#F59E0B";
  ctx.font = "700 34px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText(scoreStars(score), 112, 416);

  ctx.fillStyle = "#334155";
  ctx.font = "500 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, summary, 112, 486, 856, 46, 3);

  const sections = [
    { label: "核心问题", title: issueText, sub: secondIssueText, color: "#F97316", bg: "#FFF7ED" },
    { label: "训练重点", title: focus, sub: null, color: "#2563EB", bg: "#EFF6FF" },
    { label: "下一步建议", title: improvementText, sub: null, color: "#059669", bg: "#ECFDF5" },
  ];

  let y = 664;
  sections.forEach((section) => {
    ctx.fillStyle = section.bg;
    drawRoundRect(ctx, 112, y, 856, section.sub ? 176 : 152, 28);
    ctx.fill();
    ctx.fillStyle = section.color;
    ctx.font = "800 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.fillText(section.label, 152, y + 48);
    ctx.fillStyle = "#0F172A";
    ctx.font = "700 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const usedHeight = drawWrappedText(ctx, section.title, 152, y + 94, 760, 40, section.sub ? 2 : 2);
    if (section.sub) {
      ctx.fillStyle = "#64748B";
      ctx.font = "500 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      drawWrappedText(ctx, section.sub, 152, y + 104 + usedHeight, 760, 32, 1);
    }
    y += section.sub ? 208 : 184;
  });

  ctx.strokeStyle = "rgba(148,163,184,0.34)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(112, 1260);
  ctx.lineTo(968, 1260);
  ctx.stroke();

  ctx.fillStyle = "#475569";
  ctx.font = "600 28px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("由冰宝（IceBuddy）生成", 112, 1320);
  ctx.fillStyle = "#94A3B8";
  ctx.font = "500 22px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("训练建议仅供复盘参考，冰上动作请在教练或家长陪同下完成", 112, 1360);

  const blob = await canvasToBlob(canvas);
  const filename = `icebuddy-report-${analysis.id.slice(0, 8)}.png`;
  return { blob, filename };
}

function formatDuration(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return `${value.toFixed(2)}s`;
}

function analysisInputWindowText(analysis: AnalysisDetail) {
  if (analysis.input_window_start_sec == null || analysis.input_window_end_sec == null) {
    return null;
  }
  const range = `${analysis.input_window_start_sec.toFixed(1)}s - ${analysis.input_window_end_sec.toFixed(1)}s`;
  const source = analysis.source_duration_sec != null ? ` / 原视频 ${analysis.source_duration_sec.toFixed(1)}s` : "";
  if (analysis.input_window_mode === "manual_window") {
    return `手动片段：${range}${source}`;
  }
  if (analysis.input_window_mode === "full_context") {
    return `全量上下文：${range}${source}`;
  }
  if (analysis.input_window_mode === "system_truncated") {
    return `系统截断：${range}${source}`;
  }
  return `AI 输入范围：${range}${source}`;
}

function analysisWindowFallbackText(analysis: AnalysisDetail) {
  if (analysis.action_window_start == null || analysis.action_window_end == null) {
    return null;
  }
  return `分析窗口：${analysis.action_window_start.toFixed(1)}s - ${analysis.action_window_end.toFixed(1)}s`;
}

function formatLogTimestamp(value: string) {
  return apiDateTimeFormatter({
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parseApiDate(value));
}

function AnalysisProgressCard({ analysis }: { analysis: AnalysisDetail }) {
  const currentStage = getAnalysisProcessingStage(analysis.status);
  const progressPercent = Math.max(8, Math.min(currentStage * 25, analysis.status === "completed" ? 100 : 92));
  const logs = analysis.processing_logs ?? [];
  const latestLog = logs.length ? logs[logs.length - 1] : null;
  const timings = analysis.processing_timings ?? {};

  return (
    <section className="app-card overflow-hidden border border-cyan-100 bg-gradient-to-br from-cyan-50 via-white to-sky-50 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-cyan-600">Analysis Progress</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">{getAnalysisStatusLabel(analysis.status)}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-7 text-slate-600">{getAnalysisStageDescription(analysis.status)}</p>
          {analysis.retry_from_stage ? (
            <p className="mt-2 text-xs text-slate-500">当前重试起点：{analysis.retry_from_stage}</p>
          ) : null}
        </div>
        <div className="rounded-[22px] border border-cyan-100 bg-white/80 px-4 py-3 text-sm text-slate-600">
          <p>Pipeline: {analysis.pipeline_version ?? "v5.2.1"}</p>
          {typeof timings.total_s === "number" ? <p className="mt-1">累计耗时：{formatDuration(timings.total_s)}</p> : null}
        </div>
      </div>

      <div className="mt-5 h-3 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-sky-500 to-blue-500 transition-[width] duration-500"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-4">
        {PROGRESS_STAGE_META.map((stage, index) => {
          const done = currentStage > index + 1 || (stage.key === "completed" && analysis.status === "completed");
          const active =
            (stage.key === "extract_frames" && currentStage === 1) ||
            (stage.key === "vision" && currentStage === 2) ||
            (stage.key === "report" && currentStage === 3) ||
            (stage.key === "completed" && analysis.status === "completed");
          return (
            <div
              key={stage.key}
              className={`rounded-[22px] border px-4 py-3 text-sm ${
                active
                  ? "border-cyan-200 bg-cyan-50 text-cyan-700"
                  : done
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : "border-slate-200 bg-white text-slate-500"
              }`}
            >
              <p className="font-semibold">{stage.label}</p>
              <p className="mt-1 text-xs">{done ? "已完成" : active ? "进行中" : "等待中"}</p>
            </div>
          );
        })}
      </div>

      {latestLog ? (
        <div className="mt-5 rounded-[22px] border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-600">
          <p className="font-semibold text-slate-900">最新日志</p>
          <p className="mt-2">
            [{formatLogTimestamp(latestLog.timestamp)}] {latestLog.message}
          </p>
        </div>
      ) : null}
    </section>
  );
}

function LoadingState({ status }: { status: string }) {
  return (
    <div className="app-card mx-auto max-w-2xl p-10 text-center">
      <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-blue-50 text-4xl animate-pulse">🎬</div>
      <h2 className="mt-6 text-3xl font-semibold text-slate-900">视频分析进行中</h2>
      <p className="mt-4 text-base text-slate-500">{STATUS_TEXT[status] ?? STATUS_TEXT.processing}</p>
      <div className="mx-auto mt-8 h-2 w-56 overflow-hidden rounded-full bg-slate-100">
        <div className="animate-shimmer h-full w-1/2 rounded-full bg-blue-500" />
      </div>
    </div>
  );
}

function FailedState({ message }: { message: string | null }) {
  return (
    <div className="app-card border border-rose-200 bg-rose-50 p-8 text-rose-600">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-rose-400">分析失败</p>
      <h2 className="mt-3 text-2xl font-semibold text-rose-600">这次报告没有成功生成</h2>
      <p className="mt-4 text-base leading-7">{message ?? "请稍后重试，或检查 AI 供应商配置。"}</p>
    </div>
  );
}

function ForceScoreStars({ score }: { score: number }) {
  const stars = score >= 85 ? 5 : score >= 70 ? 4 : score >= 56 ? 3 : score >= 40 ? 2 : 1;
  const encouragements = [
    "继续加油，你做到了！💪",
    "不错哦，再练几次就更好了！",
    "今天的动作有进步！⭐",
    "超棒！冰宝（IceBuddy）为你骄傲！🎉",
    "完美！你是冰上小明星！🌟",
  ];

  return (
    <div className="flex w-full max-w-[240px] flex-col items-center gap-2">
      {/* 修改前：使用 emoji 星号，依赖平台字体度量，不同设备上容易出现星形大小和基线偏差。 */}
      {/* 修改后：改成固定 viewBox 的 SVG 星形，让移动端和桌面端保持一致对齐。 */}
      <div className="flex flex-wrap justify-center gap-2 leading-none">
        {Array.from({ length: 5 }).map((_, index) => (
          <span key={index} className="block h-8 w-8 tablet:h-10 tablet:w-10" aria-hidden="true">
            <svg viewBox="0 0 24 24" style={{ width: "100%", height: "100%", display: "block" }}>
              <path
                d="M12 2.75l2.78 5.63 6.22.9-4.5 4.39 1.06 6.2L12 16.96 6.44 19.87l1.06-6.2L3 9.28l6.22-.9L12 2.75z"
                fill={index < stars ? "#FBBF24" : "#FFFFFF"}
                stroke={index < stars ? "#F59E0B" : "#CBD5E1"}
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        ))}
      </div>
      <p className="max-w-[240px] text-center text-base font-bold leading-7 text-[#6C63FF] tablet:text-lg">{encouragements[stars - 1]}</p>
    </div>
  );
}

function SubscoreRadarChart({ subscores }: { subscores: Record<string, number> }) {
  const data = buildSubscoreRadarData(subscores);
  const axisCount = Math.max(data.length, 1);
  const gridPolygons = Array.from({ length: RADAR_LEVELS }, (_, level) =>
    buildRadarPolygonPoints(axisCount, () => (RADAR_RADIUS * (level + 1)) / RADAR_LEVELS),
  );
  // 修改前：雷达图中心点和多边形坐标交给第三方布局推断，不同断点下不容易保持绝对居中。
  // 修改后：所有点位都基于同一个 viewBox 中心显式计算，保证双端图形始终围绕同一中心。
  const valuePolygon = buildRadarPolygonPoints(axisCount, (index) => (RADAR_RADIUS * data[index].value) / 100);

  return (
    <div className="mx-auto flex aspect-square h-64 w-full max-w-[320px] items-center justify-center rounded-[28px] border border-slate-200 bg-slate-50 p-4">
      {/* 修改前：图表尺寸依赖内部布局实现，排查缩放错位时不够直观。 */}
      {/* 修改后：改成 viewBox + width:100% 的响应式 SVG，让图案始终跟随容器内容区缩放。 */}
      <svg
        viewBox={`0 0 ${RADAR_VIEWBOX_SIZE} ${RADAR_VIEWBOX_SIZE}`}
        style={{ width: "100%", height: "100%", display: "block" }}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="subscore radar chart"
      >
        {gridPolygons.map((points, index) => (
          <polygon
            key={`grid-${index}`}
            points={points}
            fill="none"
            stroke="rgba(148,163,184,0.25)"
            strokeWidth="1"
          />
        ))}

        {data.map((item, index) => {
          const axisPoint = getRadarPoint((360 / axisCount) * index, RADAR_RADIUS);
          const labelPoint = getRadarPoint((360 / axisCount) * index, RADAR_LABEL_RADIUS);
          const textAnchor =
            Math.abs(labelPoint.x - RADAR_CENTER) < 8 ? "middle" : labelPoint.x > RADAR_CENTER ? "start" : "end";

          return (
            <g key={item.label}>
              <line
                x1={RADAR_CENTER}
                y1={RADAR_CENTER}
                x2={axisPoint.x}
                y2={axisPoint.y}
                stroke="rgba(148,163,184,0.22)"
                strokeWidth="1"
              />
              <text
                x={labelPoint.x}
                y={labelPoint.y}
                fill="#64748b"
                fontSize="12"
                textAnchor={textAnchor}
                dominantBaseline="central"
              >
                {item.label}
              </text>
            </g>
          );
        })}

        <polygon points={valuePolygon} fill="#60A5FA" fillOpacity="0.28" stroke="#3B82F6" strokeWidth="2.5" />

        {data.map((item, index) => {
          const point = getRadarPoint((360 / axisCount) * index, (RADAR_RADIUS * item.value) / 100);
          return <circle key={`dot-${item.label}`} cx={point.x} cy={point.y} r="3.5" fill="#1D4ED8" />;
        })}
      </svg>
    </div>
  );
}

function DetailedFailedState({
  analysis,
  isParentMode,
  isRetrying,
  hideRetry,
  onRetry,
  onReupload,
}: {
  analysis: AnalysisDetail;
  isParentMode: boolean;
  isRetrying: boolean;
  hideRetry: boolean;
  onRetry: () => void;
  onReupload: () => void;
}) {
  const errorMessage = getAnalysisErrorMessage(analysis.error_code);

  if (!isParentMode) {
    return (
      <div className="app-card border border-amber-200 bg-gradient-to-br from-amber-50 via-white to-sky-50 p-7 text-center shadow-[0_22px_60px_rgba(148,163,184,0.18)] tablet:p-9">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-white text-3xl shadow-sm">🤔</div>
        <h2 className="mt-5 text-2xl font-semibold text-slate-900">{errorMessage.title}</h2>
        <p className="mt-3 text-base leading-7 text-slate-600">冰宝遇到了一点问题，请让爸爸妈妈来看看。</p>
      </div>
    );
  }

  return (
    <div className="app-card border border-rose-200 bg-gradient-to-br from-rose-50 via-white to-orange-50 p-6 text-rose-700 shadow-[0_22px_60px_rgba(251,113,133,0.14)] tablet:p-8">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-rose-400">分析失败</p>
      <h2 className="mt-3 text-2xl font-semibold text-rose-600">{errorMessage.title}</h2>
      <p className="mt-4 text-base leading-7 text-slate-600">{errorMessage.hint}</p>
      <div className="mt-5 rounded-[22px] border border-rose-100 bg-white/80 px-4 py-3 text-sm text-slate-600">
        错误代码：{analysis.error_code ?? "UNKNOWN_ERROR"}
      </div>
      {analysis.error_detail ? (
        <details className="mt-4 rounded-[22px] border border-slate-200 bg-white/70 px-4 py-3 text-sm text-slate-500">
          <summary className="cursor-pointer font-medium text-slate-700">调试详情</summary>
          <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6">{analysis.error_detail}</pre>
        </details>
      ) : null}
      <div className="mt-6 flex flex-wrap gap-3">
        {!hideRetry ? (
          <button
            type="button"
            onClick={onRetry}
            disabled={isRetrying}
            className="min-h-[46px] rounded-full bg-orange-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-orange-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isRetrying ? "提交中..." : "🔄 重新分析"}
          </button>
        ) : null}
        <button
          type="button"
          onClick={onReupload}
          className="min-h-[46px] rounded-full border border-slate-300 bg-white px-5 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
        >
          📤 重新上传
        </button>
      </div>
    </div>
  );
}

function ForceScoreCard({ score, isParentMode }: { score: number; isParentMode: boolean }) {
  const normalized = Math.max(0, Math.min(Math.round(score), 100));
  const levelText = normalized >= 85 ? "状态很稳" : normalized >= 70 ? "表现不错" : normalized >= 56 ? "持续进步中" : "继续找感觉";

  return (
    <div className="w-full max-w-[280px] rounded-[30px] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-blue-50 p-5 shadow-[0_18px_50px_rgba(15,23,42,0.08)]">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Force Score</p>
      <div className="mt-4 flex flex-col items-center gap-4 tablet:items-start">
        <ForceScoreStars score={normalized} />
        <div className="flex w-full items-center gap-4 rounded-[24px] border border-white/80 bg-white/90 px-4 py-3">
          <ForceScoreRing score={normalized} sizeClassName="h-20 w-20 tablet:h-20 tablet:w-20" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-900">{levelText}</p>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              {isParentMode ? "家长模式同时保留星级感知和量化得分。" : "儿童模式优先展示直观的星级反馈。"}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { isParentMode, enterParentMode, pinLength } = useAppMode();
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [skills, setSkills] = useState<SkillNode[]>([]);
  const [pose, setPose] = useState<PoseResponse | null>(null);
  const [selectedPoseFrame, setSelectedPoseFrame] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [isCreatingPlan, setIsCreatingPlan] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [deleteStep, setDeleteStep] = useState<"confirm" | "pin">("confirm");
  const [deletePin, setDeletePin] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [celebrateSkillName, setCelebrateSkillName] = useState<string | null>(null);
  const [celebratedSkillId, setCelebratedSkillId] = useState<string | null>(null);
  const [memorySuggestions, setMemorySuggestions] = useState<MemorySuggestion[]>([]);
  const [isSuggestionLoading, setIsSuggestionLoading] = useState(false);
  const [isSuggestionMutating, setIsSuggestionMutating] = useState(false);
  const [isRetryingAnalysis, setIsRetryingAnalysis] = useState(false);
  const [hideRetryAfterMissingVideo, setHideRetryAfterMissingVideo] = useState(false);
  const [isRetryConfirmOpen, setIsRetryConfirmOpen] = useState(false);
  const [isRetryPinOpen, setIsRetryPinOpen] = useState(false);
  const [retryMode, setRetryMode] = useState<"analysis" | "report">("analysis");
  const [isSharing, setIsSharing] = useState(false);
  const [shareImagePreview, setShareImagePreview] = useState<ShareImagePreview | null>(null);
  const deferredAnalysis = useDeferredValue(analysis);
  const subscores = deferredAnalysis?.report?.subscores ?? deferredAnalysis?.bio_data?.bio_subscores ?? null;
  const reportDataQuality = deferredAnalysis?.report?.data_quality ?? "partial";
  const hasReliableSubscores = reportDataQuality === "good" && Boolean(subscores);
  const reportSkater = skaters.find((item) => item.id === deferredAnalysis?.skater_id) ?? null;
  const autoUnlockedSkill = skills.find((item) => item.id === deferredAnalysis?.auto_unlocked_skill) ?? null;
  const flattenedSuggestions = useMemo(() => flattenSuggestionPreview(memorySuggestions), [memorySuggestions]);
  const shouldPollAnalysis = Boolean(id && analysis && isAnalysisInProgress(analysis.status));

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (!cancelled) {
          setSkaters(data);
        }
      } catch {
        if (!cancelled) {
          setSkaters([]);
        }
      }
    };

    void loadSkaters();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!deferredAnalysis?.skater_id) {
      setSkills([]);
      return;
    }

    let cancelled = false;
    const loadSkills = async () => {
      try {
        const skaterId = deferredAnalysis.skater_id;
        if (!skaterId) {
          return;
        }
        const data = await fetchSkaterSkills(skaterId);
        if (!cancelled) {
          setSkills(data);
        }
      } catch {
        if (!cancelled) {
          setSkills([]);
        }
      }
    };

    void loadSkills();
    return () => {
      cancelled = true;
    };
  }, [deferredAnalysis?.skater_id]);

  useEffect(() => {
    if (!deferredAnalysis?.auto_unlocked_skill || celebratedSkillId === deferredAnalysis.auto_unlocked_skill) {
      return;
    }

    const label = autoUnlockedSkill?.name ?? deferredAnalysis.skill_category ?? "新技能";
    setCelebrateSkillName(label);
    setCelebratedSkillId(deferredAnalysis.auto_unlocked_skill);
    const timer = window.setTimeout(() => setCelebrateSkillName(null), 1400);
    return () => window.clearTimeout(timer);
  }, [autoUnlockedSkill?.name, celebratedSkillId, deferredAnalysis?.auto_unlocked_skill, deferredAnalysis?.skill_category]);

  useEffect(() => {
    return () => {
      if (shareImagePreview?.url) {
        URL.revokeObjectURL(shareImagePreview.url);
      }
    };
  }, [shareImagePreview?.url]);

  useEffect(() => {
    setHideRetryAfterMissingVideo(false);
    setIsRetryConfirmOpen(false);
    setIsRetryPinOpen(false);
  }, [id]);

  useEffect(() => {
    if (!id) {
      setError("无效的报告 ID。");
      return;
    }

    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      try {
        const data = await fetchAnalysis(id, { isParentRequest: isParentMode });
        if (cancelled) {
          return;
        }
        if (data.status === "awaiting_target_selection" || data.target_lock_status === "awaiting_manual") {
          navigate(`/report/${data.id}/target`, { replace: true });
          return;
        }
        startTransition(() => {
          setAnalysis(data);
          setError(null);
        });

        if (isAnalysisInProgress(data.status)) {
          timer = window.setTimeout(load, 3000);
        }
      } catch {
        if (!cancelled) {
          setError("报告加载失败，请稍后刷新页面。");
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [id, isParentMode, shouldPollAnalysis]);

  useEffect(() => {
    if (!id || analysis?.status !== "completed") {
      return;
    }

    let cancelled = false;
    const loadPlan = async () => {
      try {
        const data = await fetchAnalysisPlan(id);
        if (!cancelled) {
          setPlanId(data.id);
        }
      } catch (requestError) {
        if (axios.isAxiosError(requestError) && requestError.response?.status === 404) {
          if (!cancelled) {
            setPlanId(null);
          }
          return;
        }
        if (!cancelled) {
          setError("训练计划状态加载失败，请稍后重试。");
        }
      }
    };

    void loadPlan();
    return () => {
      cancelled = true;
    };
  }, [analysis?.status, id]);

  useEffect(() => {
    if (!id || analysis?.status !== "completed") {
      return;
    }

    let cancelled = false;
    const loadPose = async () => {
      try {
        const data = await fetchAnalysisPose(id);
        if (!cancelled) {
          setPose(data);
        }
      } catch {
        if (!cancelled) {
          setPose(null);
        }
      }
    };

    void loadPose();
    return () => {
      cancelled = true;
    };
  }, [analysis?.status, id]);

  useEffect(() => {
    if (!isParentMode || deferredAnalysis?.status !== "completed" || !deferredAnalysis.skater_id) {
      setMemorySuggestions([]);
      return;
    }

    let cancelled = false;
    const loadSuggestions = async () => {
      setIsSuggestionLoading(true);
      try {
        const skaterId = deferredAnalysis.skater_id;
        if (!skaterId) {
          return;
        }
        const data = await fetchMemorySuggestions(skaterId);
        if (!cancelled) {
          setMemorySuggestions(data);
        }
      } catch {
        if (!cancelled) {
          setMemorySuggestions([]);
        }
      } finally {
        if (!cancelled) {
          setIsSuggestionLoading(false);
        }
      }
    };

    void loadSuggestions();
    return () => {
      cancelled = true;
    };
  }, [deferredAnalysis?.skater_id, deferredAnalysis?.status, isParentMode]);

  const handleCreatePlan = async () => {
    if (!id) {
      return;
    }
    if (planId) {
      const shouldRegenerate = window.confirm("重新生成会覆盖当前训练内容和已勾选进度，确定继续吗？");
      if (!shouldRegenerate) {
        return;
      }
    }
    setIsCreatingPlan(true);
    setError(null);
    try {
      const plan = await createPlan(id, { force: true });
      setPlanId(plan.id);
      navigate(`/plan/${plan.id}`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "训练计划生成失败，请稍后重试。"));
      } else {
        setError("训练计划生成失败，请稍后重试。");
      }
    } finally {
      setIsCreatingPlan(false);
    }
  };

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const openDeleteModal = () => {
    setDeleteStep("confirm");
    setDeletePin("");
    setDeleteError(null);
    setIsDeleteModalOpen(true);
  };

  const closeDeleteModal = () => {
    setIsDeleteModalOpen(false);
    setDeleteStep("confirm");
    setDeletePin("");
    setDeleteError(null);
    setIsDeleting(false);
  };

  const handleDeleteAnalysis = async () => {
    if (!id) {
      return;
    }

    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteAnalysis(id, deletePin);
      closeDeleteModal();
      navigate("/archive", { state: { notice: "已删除这条分析记录" } });
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setDeleteError(String(requestError.response?.data?.detail ?? "删除失败，请稍后重试。"));
      } else {
        setDeleteError("删除失败，请稍后重试。");
      }
      setIsDeleting(false);
    }
  };

  const handleDismissSuggestions = async () => {
    if (!deferredAnalysis?.skater_id || !memorySuggestions.length) {
      return;
    }

    setIsSuggestionMutating(true);
    try {
      const skaterId = deferredAnalysis.skater_id;
      if (!skaterId) {
        return;
      }
      await Promise.all(memorySuggestions.map((item) => dismissMemorySuggestion(skaterId, item.id)));
      setMemorySuggestions([]);
      showNotice("这批记忆建议已忽略。");
    } catch {
      setError("记忆建议处理失败，请稍后再试。");
    } finally {
      setIsSuggestionMutating(false);
    }
  };

  const handleViewSuggestions = async () => {
    if (!deferredAnalysis?.skater_id) {
      return;
    }
    if (!isParentMode) {
      await enterParentMode();
      return;
    }
    navigate("/snowball", {
      state: {
        focusSkaterId: deferredAnalysis.skater_id,
        focusSuggestions: true,
      },
    });
  };

  const handleRetryAnalysis = async () => {
    if (!id) {
      return;
    }
    const isReportOnlyRetry = retryMode === "report";
    setIsRetryingAnalysis(true);
    setError(null);
    try {
      await retryAnalysis(id, isReportOnlyRetry ? { retryFrom: "report" } : undefined);
      setPose(null);
      setPlanId(null);
      startTransition(() => {
        setAnalysis((current) =>
          current
            ? {
                ...current,
                status: "pending",
                processing_timings: null,
                processing_logs: [],
                error_code: null,
                error_detail: null,
                error_message: null,
              }
            : current,
        );
      });
      setHideRetryAfterMissingVideo(false);
      showNotice(isReportOnlyRetry ? "已提交报告重生成，请稍候" : "已重新提交，请稍候");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        if (requestError.response?.status === 404) {
          setHideRetryAfterMissingVideo(true);
          showNotice('原始视频已清理，请点击"重新上传"');
          return;
        }
        setError(String(requestError.response?.data?.detail ?? "重新分析失败，请稍后重试。"));
      } else {
        setError("重新分析失败，请稍后重试。");
      }
    } finally {
      setIsRetryingAnalysis(false);
    }
  };

  const handleShareReport = async () => {
    if (!id || !deferredAnalysis || deferredAnalysis.status !== "completed") {
      return;
    }

    setIsSharing(true);
    setError(null);
    try {
      const { blob, filename } = await createReportShareImage(deferredAnalysis);
      const copiedToClipboard = await copyImageBlobToClipboard(blob);
      const url = URL.createObjectURL(blob);
      setShareImagePreview({ url, blob, filename, copiedToClipboard });
      showNotice(copiedToClipboard ? "分享图已生成并复制" : "分享图已生成");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "分享图生成失败，请稍后重试。"));
      } else {
        setError("分享图生成失败，请稍后重试。");
      }
    } finally {
      setIsSharing(false);
    }
  };

  const handleCopyShareImage = async () => {
    if (!shareImagePreview) {
      return;
    }
    const copied = await copyImageBlobToClipboard(shareImagePreview.blob);
    if (!copied) {
      setError("当前浏览器不能直接复制图片，请先下载后分享。");
      return;
    }
    setShareImagePreview((current) => (current ? { ...current, copiedToClipboard: true } : current));
    showNotice("分享图已复制");
  };

  const requestRetryAnalysis = (mode: "analysis" | "report" = "analysis") => {
    if (!deferredAnalysis || isAnalysisInProgress(deferredAnalysis.status) || isRetryingAnalysis) {
      return;
    }

    setRetryMode(mode);
    if (isParentMode) {
      setIsRetryConfirmOpen(true);
      return;
    }

    setIsRetryPinOpen(true);
  };

  const canDeleteAnalysis = deferredAnalysis?.status === "completed" || deferredAnalysis?.status === "failed";
  const deleteDisabled = !deferredAnalysis || !canDeleteAnalysis;
  const deleteTitle =
    deferredAnalysis?.status === "processing"
      ? "分析进行中，无法删除"
      : deleteDisabled
        ? "当前状态暂不支持删除"
        : "删除这条分析记录";

  return (
    <div className="space-y-6">
      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/review" className="app-pill">
          ← 返回复盘
        </Link>
        <div className="flex flex-wrap gap-3">
          {isParentMode && deferredAnalysis?.status === "completed" ? (
            <button
              type="button"
              onClick={() => void handleShareReport()}
              disabled={isSharing}
              className="min-h-[44px] rounded-full border border-sky-200 bg-sky-50 px-4 py-2 text-sm font-semibold text-sky-700 transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSharing ? "生成中..." : "生成分享图"}
            </button>
          ) : null}
          {isParentMode ? (
            <button
              type="button"
              onClick={openDeleteModal}
              disabled={deleteDisabled}
              title={deleteTitle}
              className="min-h-[44px] rounded-full border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              🗑️ 删除
            </button>
          ) : null}
          <Link to="/archive" className="app-pill">
            查看练习档案
          </Link>
          {deferredAnalysis?.status === "completed" ? (
            <>
              <Link
                to={`/report/${deferredAnalysis.id}`}
                className="min-h-[44px] rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600"
              >
                📄 查看报告
              </Link>
              <button
                type="button"
                onClick={() => requestRetryAnalysis("report")}
                disabled={isRetryingAnalysis}
                className="min-h-[44px] rounded-full border border-orange-200 bg-white px-4 py-2 text-sm font-semibold text-orange-600 transition hover:bg-orange-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isRetryingAnalysis ? "提交中..." : "🔄 重新生成报告"}
              </button>
              <button
                type="button"
                onClick={() => requestRetryAnalysis("analysis")}
                disabled={isRetryingAnalysis}
                className="min-h-[44px] rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                完整重新分析
              </button>
            </>
          ) : null}
          {planId ? (
            <>
              <Link to={`/plan/${planId}`} className="min-h-[44px] rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600">
                查看 7 天训练计划
              </Link>
              <button
                type="button"
                onClick={handleCreatePlan}
                disabled={isCreatingPlan}
                className="min-h-[44px] rounded-full border border-blue-200 bg-white px-4 py-2 text-sm font-semibold text-blue-600 transition hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCreatingPlan ? "正在重新生成..." : "重新生成训练计划"}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={handleCreatePlan}
              disabled={!deferredAnalysis || deferredAnalysis.status !== "completed" || isCreatingPlan}
              className="min-h-[44px] rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isCreatingPlan ? "正在生成训练计划..." : "重新生成 7 天训练计划"}
            </button>
          )}
        </div>
      </div>

      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      {!deferredAnalysis ? (
        <LoadingState status="processing" />
      ) : deferredAnalysis.status === "failed" ? (
        <>
          <AnalysisProgressCard analysis={deferredAnalysis} />
          <DetailedFailedState
            analysis={deferredAnalysis}
            isParentMode={isParentMode}
            isRetrying={isRetryingAnalysis}
            hideRetry={hideRetryAfterMissingVideo}
            onRetry={() => requestRetryAnalysis("analysis")}
            onReupload={() =>
              navigate("/review", {
                state: deferredAnalysis.skater_id ? { skaterId: deferredAnalysis.skater_id } : undefined,
              })
            }
          />
          <AnalysisDebugLogPanel
            logs={deferredAnalysis.processing_logs ?? []}
            timings={deferredAnalysis.processing_timings}
            pipelineVersion={deferredAnalysis.pipeline_version}
            videoTemporalDiagnostics={deferredAnalysis.video_temporal_diagnostics}
            analysisId={deferredAnalysis.id}
            targetLock={deferredAnalysis.target_lock}
            poseData={pose ?? deferredAnalysis.pose_data}
          />
        </>
      ) : deferredAnalysis.status !== "completed" ? (
        <>
          <AnalysisProgressCard analysis={deferredAnalysis} />
          <LoadingState status={deferredAnalysis.status} />
          <AnalysisDebugLogPanel
            logs={deferredAnalysis.processing_logs ?? []}
            timings={deferredAnalysis.processing_timings}
            pipelineVersion={deferredAnalysis.pipeline_version}
            videoTemporalDiagnostics={deferredAnalysis.video_temporal_diagnostics}
            analysisId={deferredAnalysis.id}
            targetLock={deferredAnalysis.target_lock}
            poseData={pose ?? deferredAnalysis.pose_data}
          />
        </>
      ) : (
        <>
          {deferredAnalysis.report?.data_quality === "poor" ? (
            <div className="rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-7 text-amber-700">
              当前视频可能存在人物过小、遮挡、模糊或关键帧不足，报告已尽量保守分析。建议用更近、更稳定的角度重新拍摄后复盘。
            </div>
          ) : null}

          {isParentMode && deferredAnalysis.input_window_truncated ? (
            <div className="rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-7 text-amber-700">
              本次 AI 没有看到完整视频：{analysisInputWindowText(deferredAnalysis)}
            </div>
          ) : null}

          <section className="app-card overflow-hidden p-6 tablet:p-8">
            <div className="grid gap-6 tablet:grid-cols-[minmax(220px,240px)_1fr] tablet:items-center web:gap-8">
              <div className="flex justify-center tablet:justify-start">
                <ForceScoreCard score={deferredAnalysis.force_score ?? 0} isParentMode={isParentMode} />
              </div>

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">诊断报告</p>
                <h1 className="text-3xl font-semibold text-slate-900 tablet:text-4xl">{deferredAnalysis.action_type}</h1>
                {reportSkater ? (
                  <div className="flex w-fit items-center gap-3 rounded-[24px] bg-slate-50 px-4 py-3">
                    <ZodiacAvatar avatarType={reportSkater.avatar_type} avatarEmoji={reportSkater.avatar_emoji} size="md" />
                    <span className="text-sm font-medium text-slate-700">{reportSkater.display_name || reportSkater.name}</span>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-3 text-sm text-slate-500">
                  <span>{formatDate(deferredAnalysis.created_at)}</span>
                  {deferredAnalysis.skater_name ? <span>练习档案：{deferredAnalysis.skater_name}</span> : null}
                  {deferredAnalysis.skill_category ? <span>技能分类：{deferredAnalysis.skill_category}</span> : null}
                </div>
                {isParentMode && (analysisInputWindowText(deferredAnalysis) || (deferredAnalysis.action_window_start != null && deferredAnalysis.action_window_end != null)) ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    {analysisInputWindowText(deferredAnalysis) ? <span>{analysisInputWindowText(deferredAnalysis)}</span> : null}
                    {!analysisInputWindowText(deferredAnalysis) && analysisWindowFallbackText(deferredAnalysis) ? (
                      <span>{analysisWindowFallbackText(deferredAnalysis)}</span>
                    ) : null}
                    {deferredAnalysis.is_slow_motion ? (
                      <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-orange-600">
                        慢动作 {Math.round(deferredAnalysis.source_fps ?? 0)}fps
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {deferredAnalysis.note ? (
                  <div className="rounded-[24px] bg-slate-50 px-5 py-4 text-sm leading-7 text-slate-600">
                    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">补充说明</p>
                    <p className="mt-2">{deferredAnalysis.note}</p>
                  </div>
                ) : null}
              </div>
            </div>
          </section>

          <div className="grid min-w-0 max-w-full gap-6 overflow-hidden web:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)]">
            <div className="min-w-0 space-y-6">
              <ReportCard title="总体评价" eyebrow="Summary">
                <p className="max-w-3xl text-base leading-8 text-slate-600">{deferredAnalysis.report?.summary ?? "暂无总体评价。"}</p>
              </ReportCard>

              {isParentMode ? <AnalysisQualityPanel analysis={deferredAnalysis} /> : null}

              {subscores || reportDataQuality !== "good" ? (
                <ReportCard title="分项评分" eyebrow="Subscores">
                  {hasReliableSubscores && subscores ? (
                    <div className="grid min-w-0 gap-6 ipad:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] web:grid-cols-1">
                      <SubscoreRadarChart subscores={subscores} />

                      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                        {Object.entries(subscores).map(([key, value]) => (
                          <article key={key} className="rounded-[24px] bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">{SUBSCORE_LABELS[key] ?? key}</p>
                            <p className="mt-3 text-2xl font-semibold text-slate-900">{value}</p>
                          </article>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="grid min-w-0 gap-6 ipad:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] web:grid-cols-1">
                      <div className="relative h-64 overflow-hidden rounded-[28px] border border-slate-200 bg-slate-100">
                        <div className="absolute inset-0 opacity-60 [background-image:radial-gradient(circle_at_center,rgba(148,163,184,0.14)_0,rgba(148,163,184,0.14)_1px,transparent_1px)] [background-size:28px_28px]" />
                        <div className="absolute inset-6 rounded-full border border-dashed border-slate-300" />
                        <div className="absolute inset-[20%] rounded-full border border-dashed border-slate-300" />
                        <div className="absolute inset-[34%] rounded-full border border-dashed border-slate-300" />
                        <div className="absolute inset-0 flex items-center justify-center">
                          <span className="rounded-full bg-white/90 px-4 py-2 text-sm font-medium text-slate-500 shadow-sm">
                            雷达图已隐藏
                          </span>
                        </div>
                      </div>

                      <article className="flex min-h-64 flex-col justify-center rounded-[24px] border border-slate-200 bg-slate-50 p-6 text-center sm:text-left">
                        <p className="text-lg font-semibold text-slate-900">数据有限，暂不提供可靠分项评分</p>
                        <p className="mt-3 text-sm leading-7 text-slate-500">
                          当前视频关键帧不足，或识别稳定性不够，继续展示五项数字容易造成误导。建议补拍更近、更稳、更完整的视频后再查看分项评分。
                        </p>
                      </article>
                    </div>
                  )}

                  <p className="mt-4 text-sm text-slate-500">
                    数据质量：
                    {DATA_QUALITY_LABELS[reportDataQuality] ?? reportDataQuality}
                  </p>
                </ReportCard>
              ) : null}

              {pose?.frames?.length ? (
                <ReportCard title="姿态回放与生物力学" eyebrow="Pose Replay">
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm text-slate-500">查看骨架、bbox 与逐帧追踪数据。</p>
                    <Link to={`/report/${deferredAnalysis.id}/pose-debug`} className="app-pill text-sm font-semibold">
                      打开大屏调试
                    </Link>
                  </div>
                  <PoseViewer pose={pose} activeFrameId={selectedPoseFrame} onFrameChange={setSelectedPoseFrame} />
                  {deferredAnalysis.bio_data ? (
                    <div className="mt-5">
                      <BiomechanicsPanel bioData={deferredAnalysis.bio_data} mode={isParentMode ? "parent" : "child"} onSelectFrame={setSelectedPoseFrame} />
                    </div>
                  ) : null}
                </ReportCard>
              ) : null}

              <AnalysisDebugLogPanel
                logs={deferredAnalysis.processing_logs ?? []}
                timings={deferredAnalysis.processing_timings}
                pipelineVersion={deferredAnalysis.pipeline_version}
                videoTemporalDiagnostics={deferredAnalysis.video_temporal_diagnostics}
                analysisId={deferredAnalysis.id}
                targetLock={deferredAnalysis.target_lock}
                poseData={pose ?? deferredAnalysis.pose_data}
              />
            </div>

            <div className="min-w-0 space-y-6">
              {!isParentMode ? (
                <>
                  <ReportCard title="冰宝提醒" eyebrow="Simple View">
                    <div className="space-y-4">
                      {(deferredAnalysis.report?.improvements?.slice(0, 3) ?? []).map((improvement, index) => (
                        <article key={`${improvement.target}-${index}`} className="rounded-[24px] bg-slate-50 p-4">
                          <p className="text-sm font-semibold text-blue-500">{improvement.target}</p>
                          <p className="mt-2 text-sm leading-7 text-slate-600">{improvement.action}</p>
                        </article>
                      ))}
                      {!deferredAnalysis.report?.improvements?.length ? <p className="text-sm text-slate-500">今天表现很棒，继续保持稳定节奏。</p> : null}
                    </div>
                  </ReportCard>

                  <ReportCard title="今天先记住这一点" eyebrow="Focus" className="border border-blue-100 bg-blue-50/60">
                    <p className="text-lg leading-8 text-slate-700">{deferredAnalysis.report?.training_focus ?? "先把动作做稳，再慢慢加速度。"}
                    </p>
                    <button type="button" onClick={() => void enterParentMode()} className="app-pill mt-5">
                      家长模式查看完整报告
                    </button>
                  </ReportCard>
                </>
              ) : (
                <>
                  <ReportCard title="问题列表" eyebrow="Issues">
                    <div className="space-y-4">
                      {deferredAnalysis.report?.issues?.length ? (
                        deferredAnalysis.report.issues.map((issue, index) => (
                          <article key={`${issue.category}-${index}`} className={`rounded-[24px] border p-4 ${ISSUE_STYLES[issue.severity] ?? ISSUE_STYLES.low}`}>
                            <div className="flex items-center justify-between gap-3">
                              <h3 className="text-base font-semibold text-slate-900">{issue.category}</h3>
                              <span className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">{issue.severity}</span>
                            </div>
                            <p className="mt-3 text-sm leading-7 text-slate-600">{issue.description}</p>
                            {issue.phase || issue.frames?.length ? (
                              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                                {issue.phase ? <span className="rounded-full bg-white px-3 py-1">阶段：{issue.phase}</span> : null}
                                {issue.frames?.length ? <span className="rounded-full bg-white px-3 py-1">帧号：{issue.frames.join(", ")}</span> : null}
                              </div>
                            ) : null}
                          </article>
                        ))
                      ) : (
                        <p className="text-sm text-slate-500">没有识别到明显问题。</p>
                      )}
                    </div>
                  </ReportCard>

                  <ReportCard title="改进建议" eyebrow="Next Reps">
                    <div className="space-y-4">
                      {deferredAnalysis.report?.improvements?.length ? (
                        deferredAnalysis.report.improvements.map((improvement, index) => (
                          <article key={`${improvement.target}-${index}`} className="rounded-[24px] bg-slate-50 p-4">
                            <p className="text-sm font-semibold text-blue-500">{improvement.target}</p>
                            <p className="mt-2 text-sm leading-7 text-slate-600">{improvement.action}</p>
                          </article>
                        ))
                      ) : (
                        <p className="text-sm text-slate-500">暂无改进建议。</p>
                      )}
                    </div>
                  </ReportCard>

                  <ReportCard title="训练重点" eyebrow="Focus" className="border border-blue-100 bg-blue-50/60">
                    <p className="text-lg leading-8 text-slate-700">{deferredAnalysis.report?.training_focus ?? "暂无训练重点。"}</p>
                  </ReportCard>
                </>
              )}
            </div>
          </div>

          <div className="app-card flex flex-col gap-4 border border-blue-100 bg-blue-50/60 p-6 tablet:flex-row tablet:items-center tablet:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">7-Day Plan</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">把这次诊断转成一周训练安排</h2>
              <p className="mt-2 text-sm leading-7 text-slate-500">系统会按这次报告、孩子档案和备注即时生成一周训练安排。</p>
            </div>
            {planId ? (
              <div className="flex flex-wrap gap-3">
                <Link to={`/plan/${planId}`} className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600">
                  查看训练计划
                </Link>
                <button
                  type="button"
                  onClick={handleCreatePlan}
                  disabled={isCreatingPlan}
                  className="min-h-[44px] rounded-full border border-blue-200 bg-white px-5 py-3 text-sm font-semibold text-blue-600 transition hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCreatingPlan ? "正在重新生成..." : "重新生成"}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={handleCreatePlan}
                disabled={isCreatingPlan}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCreatingPlan ? "正在生成训练计划..." : "重新生成训练计划"}
              </button>
            )}
          </div>

          {isParentMode && !isSuggestionLoading && flattenedSuggestions.length ? (
            <section className="app-card border border-amber-200 bg-amber-50/70 p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-600">Memory Suggestions</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">💡 冰宝（IceBuddy）有 {flattenedSuggestions.length} 条记忆更新建议</h2>
              <p className="mt-3 text-sm leading-7 text-slate-600">「{flattenedSuggestions[0]?.title ?? "发现新卡点"}」</p>
              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => void handleViewSuggestions()}
                  disabled={isSuggestionMutating}
                  className="min-h-[44px] rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
                >
                  查看建议
                </button>
                <button
                  type="button"
                  onClick={() => void handleDismissSuggestions()}
                  disabled={isSuggestionMutating}
                  className="min-h-[44px] rounded-full border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                >
                  {isSuggestionMutating ? "处理中..." : "忽略"}
                </button>
              </div>
            </section>
          ) : null}
        </>
      )}

      {isDeleteModalOpen ? (
        <DeleteAnalysisModal
          step={deleteStep}
          pin={deletePin}
          pinLength={pinLength}
          error={deleteError}
          isSubmitting={isDeleting}
          onChangePin={setDeletePin}
          onClose={closeDeleteModal}
          onConfirmDelete={() => setDeleteStep("pin")}
          onSubmitPin={() => void handleDeleteAnalysis()}
        />
      ) : null}

      {isRetryPinOpen ? (
        <ParentPinVerifyModal
          pinLength={pinLength}
          title="输入家长 PIN"
          description="验证通过后才能重新分析这个视频。"
          confirmLabel="继续"
          onClose={() => setIsRetryPinOpen(false)}
          onVerified={() => {
            setIsRetryPinOpen(false);
            setIsRetryConfirmOpen(true);
          }}
        />
      ) : null}

      {isRetryConfirmOpen ? (
        <RetryAnalysisConfirmSheet
          isSubmitting={isRetryingAnalysis}
          retryFromStage={retryMode === "report" ? "report" : deferredAnalysis?.retry_from_stage}
          mode={retryMode}
          onClose={() => {
            if (!isRetryingAnalysis) {
              setIsRetryConfirmOpen(false);
            }
          }}
          onConfirm={() =>
            void (async () => {
              await handleRetryAnalysis();
              setIsRetryConfirmOpen(false);
            })()
          }
        />
      ) : null}

      {shareImagePreview ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/36 px-4 py-6 backdrop-blur-sm">
          <section className="app-card max-h-[92vh] w-full max-w-3xl overflow-y-auto p-5 tablet:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Share Image</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">报告分享图</h2>
                <p className="mt-2 text-sm text-slate-500">
                  {shareImagePreview.copiedToClipboard ? "已复制到剪贴板，可以直接粘贴分享。" : "当前浏览器未开放图片剪贴板，可下载后分享。"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShareImagePreview(null)}
                className="min-h-[40px] rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
              >
                关闭
              </button>
            </div>

            <div className="mt-5 overflow-hidden rounded-[28px] border border-slate-200 bg-slate-100">
              <img src={shareImagePreview.url} alt="报告分享图预览" className="mx-auto block max-h-[62vh] w-auto max-w-full object-contain" />
            </div>

            <div className="mt-5 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => void handleCopyShareImage()}
                className="min-h-[44px] rounded-full border border-blue-200 bg-blue-50 px-5 py-3 text-sm font-semibold text-blue-700 transition hover:bg-blue-100"
              >
                复制图片
              </button>
              <a
                href={shareImagePreview.url}
                download={shareImagePreview.filename}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
              >
                下载 PNG
              </a>
            </div>
          </section>
        </div>
      ) : null}

      {celebrateSkillName ? <UnlockCelebration label={celebrateSkillName} /> : null}
    </div>
  );
}
