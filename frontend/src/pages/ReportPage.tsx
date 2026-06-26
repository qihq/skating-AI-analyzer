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
  fetchMemorySuggestions,
  fetchSkaterSkills,
  fetchSkaters,
  MemorySuggestion,
  retryAnalysis,
  Skater,
  SkillNode,
} from "../api/client";
import { getAnalysisErrorMessage } from "../constants/analysisErrors";
import AnalysisQualityPanel from "../components/AnalysisQualityPanel";
import AnalysisDebugLogPanel from "../components/AnalysisDebugLogPanel";
import DeleteAnalysisModal from "../components/DeleteAnalysisModal";
import ForceScoreRing from "../components/ForceScoreRing";
import ParentPinVerifyModal from "../components/ParentPinVerifyModal";
import ReportCard from "../components/ReportCard";
import RetryAnalysisConfirmSheet from "../components/RetryAnalysisConfirmSheet";
import UnlockCelebration from "../components/UnlockCelebration";
import { useAppMode } from "../components/AppModeContext";
import { getAnalysisProcessingStage, getAnalysisStageDescription, getAnalysisStatusLabel, isAnalysisInProgress } from "../constants/analysisStatus";
import { apiDateTimeFormatter, parseApiDate } from "../utils/datetime";
import ZodiacAvatar from "../components/ZodiacAvatar";
import {
  canvasToCompressedBlob,
  copyImageBlobToClipboard,
  createShareImagePreview,
  createShareImageResult,
  drawRoundRect,
  drawWrappedText,
  measureWrappedText,
  normalizeShareText,
  shareImageFile,
  ShareImagePreview,
} from "../utils/shareCanvas";

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

function normalizeShareSnippet(value: string | null | undefined, fallback: string, maxLength = 92) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) {
    return fallback;
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function formatActionConfirmation(report: AnalysisDetail["report"] | null | undefined) {
  const confirmation = report?.action_confirmation;
  if (!confirmation) {
    return null;
  }
  const confirmed = String(confirmation.confirmed_action ?? confirmation.jump_type ?? "").trim();
  if (!confirmed || confirmed === "不可分析") {
    return null;
  }
  const confidence =
    typeof confirmation.confidence === "number" && Number.isFinite(confirmation.confidence)
      ? ` · ${Math.round(confirmation.confidence * 100)}%`
      : "";
  const family = confirmation.action_family ? `${confirmation.action_family} · ` : "";
  return `${family}${confirmed}${confidence}`;
}

async function createReportShareImage(analysis: AnalysisDetail) {
  const canvas = document.createElement("canvas");
  const width = 1080;
  const scale = 1;

  const report = analysis.report;
  const score = analysis.force_score ?? 0;
  const topIssue = report?.issues?.[0];
  const secondIssue = report?.issues?.[1];
  const topImprovement = report?.improvements?.[0];
  const summary = normalizeShareText(report?.summary, "本次报告已生成，建议结合训练重点继续练习。");
  const focus = normalizeShareText(report?.training_focus, "先把动作做稳，再慢慢加速度。");
  const issueText = normalizeShareText(
    topIssue ? `${topIssue.category}：${topIssue.description}` : null,
    "本次没有识别到明显高风险问题。",
  );
  const secondIssueText = secondIssue
    ? normalizeShareText(`${secondIssue.category}：${secondIssue.description}`, "")
    : null;
  const improvementText = normalizeShareText(
    topImprovement ? `${topImprovement.target}：${topImprovement.action}` : null,
    "保持低冲击、短时间、多鼓励的练习节奏。",
  );
  const actionTitle = normalizeShareSnippet(analysis.action_type, "滑冰复盘", 22);

  const measureCanvas = document.createElement("canvas");
  const measureCtx = measureCanvas.getContext("2d");
  if (!measureCtx) {
    throw new Error("share_image_canvas_failed");
  }
  const contentWidth = 856;
  const textWidth = 760;
  measureCtx.font = "500 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const summaryHeight = measureWrappedText(measureCtx, summary, contentWidth, 46);
  const sections = [
    { label: "核心问题", title: issueText, sub: secondIssueText, color: "#F97316", bg: "#FFF7ED" },
    { label: "训练重点", title: focus, sub: null, color: "#2563EB", bg: "#EFF6FF" },
    { label: "下一步建议", title: improvementText, sub: null, color: "#059669", bg: "#ECFDF5" },
  ];
  measureCtx.font = "700 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const sectionHeights = sections.map((section) => {
    const titleHeight = measureWrappedText(measureCtx, section.title, textWidth, 40);
    const subHeight = section.sub ? measureWrappedText(measureCtx, section.sub, textWidth, 32) : 0;
    return Math.max(section.sub ? 176 : 152, 88 + titleHeight + (section.sub ? 14 + subHeight : 0) + 34);
  });
  const height = Math.min(
    6000,
    Math.max(1080, 64 + 312 + 70 + summaryHeight + 70 + sectionHeights.reduce((sum, item) => sum + item + 32, 0) + 140),
  );
  canvas.width = width * scale;
  canvas.height = height * scale;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("share_image_canvas_failed");
  }
  ctx.scale(scale, scale);

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
  drawWrappedText(ctx, actionTitle, 112, 230, 520, 66, 2);

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
  const summaryUsedHeight = drawWrappedText(ctx, summary, 112, 486, contentWidth, 46);

  let y = 486 + summaryUsedHeight + 70;
  sections.forEach((section, index) => {
    ctx.fillStyle = section.bg;
    const blockHeight = sectionHeights[index];
    drawRoundRect(ctx, 112, y, contentWidth, blockHeight, 28);
    ctx.fill();
    ctx.fillStyle = section.color;
    ctx.font = "800 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.fillText(section.label, 152, y + 48);
    ctx.fillStyle = "#0F172A";
    ctx.font = "700 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const usedHeight = drawWrappedText(ctx, section.title, 152, y + 94, textWidth, 40);
    if (section.sub) {
      ctx.fillStyle = "#64748B";
      ctx.font = "500 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      drawWrappedText(ctx, section.sub, 152, y + 112 + usedHeight, textWidth, 32);
    }
    y += blockHeight + 32;
  });

  ctx.strokeStyle = "rgba(148,163,184,0.34)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(112, y + 26);
  ctx.lineTo(968, y + 26);
  ctx.stroke();

  ctx.fillStyle = "#475569";
  ctx.font = "600 28px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("由冰宝（IceBuddy）生成", 112, y + 86);
  ctx.fillStyle = "#94A3B8";
  ctx.font = "500 22px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("训练建议仅供复盘参考，冰上动作请在教练或家长陪同下完成", 112, y + 126);

  const blob = await canvasToCompressedBlob(canvas, { type: "image/jpeg", quality: 0.82, maxBytes: 1_500_000 });
  const filename = `icebuddy-report-${analysis.id.slice(0, 8)}.jpg`;
  return createShareImageResult(blob, filename);
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

function CompactForceScoreSummary({ score }: { score: number }) {
  const normalized = Math.max(0, Math.min(Math.round(score), 100));

  return (
    <div className="flex min-w-0 items-center gap-3 rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
      <ForceScoreRing score={normalized} sizeClassName="h-16 w-16" />
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-500">Force Score</p>
        <p className="mt-1 text-base font-semibold text-slate-900">{normalized} 分</p>
        <p className="mt-1 text-sm leading-6 text-slate-500">{scoreLevelText(normalized)}</p>
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
  const actionConfirmationText = formatActionConfirmation(deferredAnalysis?.report);

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
      await retryAnalysis(id, isReportOnlyRetry ? { retryFrom: "report" } : { resetTargetLock: true });
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
      const result = await createReportShareImage(deferredAnalysis);
      const copiedToClipboard = await copyImageBlobToClipboard(result.blob);
      setShareImagePreview((current) => {
        if (current?.url) {
          URL.revokeObjectURL(current.url);
        }
        return createShareImagePreview(result, copiedToClipboard);
      });
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

  const handleNativeShareImage = async () => {
    if (!shareImagePreview) {
      return;
    }
    const shared = await shareImageFile(shareImagePreview.blob, shareImagePreview.filename, "IceBuddy 报告分享图");
    if (!shared) {
      setError("当前浏览器不支持直接系统分享图片，请先下载后保存或发送。");
    }
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
  const reportIssues = deferredAnalysis?.report?.issues ?? [];
  const reportImprovements = deferredAnalysis?.report?.improvements ?? [];
  const visibleImprovements = isParentMode ? reportImprovements : reportImprovements.slice(0, 3);
  const planButtonText = planId ? "查看训练计划" : "生成训练计划";

  return (
    <div className="space-y-6">
      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/review" className="app-pill">
          ← 返回复盘
        </Link>
        <div className="flex flex-wrap justify-end gap-3">
          <Link to="/archive" className="app-pill">
            查看练习档案
          </Link>
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
            poseData={deferredAnalysis.pose_data}
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
            poseData={deferredAnalysis.pose_data}
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

          <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-6">
            <div className="grid min-w-0 gap-5 web:grid-cols-[minmax(0,1fr)_minmax(0,320px)] web:items-start">
              <div className="min-w-0 space-y-4">
                <div className="flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">诊断报告</p>
                    <h1 className="mt-2 break-words text-3xl font-semibold text-slate-900 tablet:text-4xl">{deferredAnalysis.action_type}</h1>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-500">
                      {reportSkater ? (
                        <span className="inline-flex items-center gap-2 rounded-full bg-slate-50 px-3 py-2 text-slate-700">
                          <ZodiacAvatar avatarType={reportSkater.avatar_type} avatarEmoji={reportSkater.avatar_emoji} size="sm" />
                          {reportSkater.display_name || reportSkater.name}
                        </span>
                      ) : null}
                      <span>{formatDate(deferredAnalysis.created_at)}</span>
                      {deferredAnalysis.skill_category ? <span>{deferredAnalysis.skill_category}</span> : null}
                    </div>
                  </div>
                  <CompactForceScoreSummary score={deferredAnalysis.force_score ?? 0} />
                </div>

                <div className="rounded-[22px] bg-slate-50 px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">本次结论</p>
                  <p className="mt-3 text-base leading-8 text-slate-700">{deferredAnalysis.report?.summary ?? "暂无总体评价。"}</p>
                </div>
              </div>

              <div className="grid min-w-0 gap-3">
                {planId ? (
                  <Link to={`/plan/${planId}`} className="flex min-h-[44px] items-center justify-center rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600">
                    {planButtonText}
                  </Link>
                ) : (
                  <button
                    type="button"
                    onClick={handleCreatePlan}
                    disabled={isCreatingPlan}
                    className="min-h-[44px] rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isCreatingPlan ? "生成中..." : planButtonText}
                  </button>
                )}
                {isParentMode ? (
                  <button
                    type="button"
                    onClick={() => void handleShareReport()}
                    disabled={isSharing}
                    className="min-h-[44px] rounded-full border border-sky-200 bg-white px-4 py-2 text-sm font-semibold text-sky-700 transition hover:bg-sky-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isSharing ? "生成中..." : "生成分享图"}
                  </button>
                ) : (
                  <button type="button" onClick={() => void enterParentMode()} className="min-h-[44px] rounded-full border border-blue-200 bg-white px-4 py-2 text-sm font-semibold text-blue-600 transition hover:bg-blue-50">
                    家长模式
                  </button>
                )}
                <div className="grid grid-cols-2 gap-2">
                  <Link to={`/report/${deferredAnalysis.id}/workspace?tab=pose`} className="min-h-[40px] rounded-full border border-slate-200 bg-white px-3 py-2 text-center text-sm font-semibold text-slate-600 transition hover:bg-slate-50">
                    查看姿态
                  </Link>
                  <Link to={`/report/${deferredAnalysis.id}/workspace?tab=evidence`} className="min-h-[40px] rounded-full border border-slate-200 bg-white px-3 py-2 text-center text-sm font-semibold text-slate-600 transition hover:bg-slate-50">
                    查看证据
                  </Link>
                  <Link to={`/report/${deferredAnalysis.id}/workspace?tab=diagnostics`} className="min-h-[40px] rounded-full border border-slate-200 bg-white px-3 py-2 text-center text-sm font-semibold text-slate-600 transition hover:bg-slate-50">
                    诊断日志
                  </Link>
                  <Link to={`/report/${deferredAnalysis.id}/workspace?tab=followup`} className="min-h-[40px] rounded-full border border-slate-200 bg-white px-3 py-2 text-center text-sm font-semibold text-slate-600 transition hover:bg-slate-50">
                    AI 追问
                  </Link>
                </div>
                <details className="rounded-[20px] border border-slate-200 bg-white px-4 py-3">
                  <summary className="cursor-pointer text-sm font-semibold text-slate-700">更多操作</summary>
                  <div className="mt-3 space-y-2">
                    <button
                      type="button"
                      onClick={() => requestRetryAnalysis("report")}
                      disabled={isRetryingAnalysis}
                      className="min-h-[40px] w-full rounded-full border border-orange-200 bg-orange-50 px-4 py-2 text-sm font-semibold text-orange-600 transition hover:bg-orange-100 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isRetryingAnalysis ? "提交中..." : "重新生成报告"}
                    </button>
                    <button
                      type="button"
                      onClick={() => requestRetryAnalysis("analysis")}
                      disabled={isRetryingAnalysis}
                      className="min-h-[40px] w-full rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      完整重新分析
                    </button>
                    {isParentMode ? (
                      <button
                        type="button"
                        onClick={openDeleteModal}
                        disabled={deleteDisabled}
                        title={deleteTitle}
                        className="min-h-[40px] w-full rounded-full border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        删除记录
                      </button>
                    ) : null}
                  </div>
                </details>
              </div>
            </div>
          </section>

          <div className="grid min-w-0 gap-6 web:grid-cols-[minmax(0,1fr)_360px]">
            <main className="min-w-0 space-y-6">
              <AnalysisQualityPanel analysis={deferredAnalysis} />

              <ReportCard title="训练重点" eyebrow="Focus" className="border border-blue-100 bg-blue-50/60">
                <p className="text-lg leading-8 text-slate-700">{deferredAnalysis.report?.training_focus ?? "先把动作做稳，再慢慢加速度。"}</p>
              </ReportCard>

              <ReportCard title={isParentMode ? "问题与建议" : "冰宝提醒"} eyebrow="Next">
                <div className={`grid gap-5 ${isParentMode ? "ipad:grid-cols-2" : ""}`}>
                  {isParentMode ? (
                    <div className="min-w-0 space-y-3">
                      <h3 className="text-sm font-semibold text-slate-900">需要关注</h3>
                      {reportIssues.length ? (
                        reportIssues.map((issue, index) => (
                          <article key={`${issue.category}-${index}`} className={`rounded-[20px] border p-4 ${ISSUE_STYLES[issue.severity] ?? ISSUE_STYLES.low}`}>
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-base font-semibold text-slate-900">{issue.category}</p>
                              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">{issue.severity}</span>
                            </div>
                            <p className="mt-2 text-sm leading-7 text-slate-600">{issue.description}</p>
                            {issue.phase || issue.frames?.length ? (
                              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                                {issue.phase ? <span className="rounded-full bg-white px-3 py-1">阶段：{issue.phase}</span> : null}
                                {issue.frames?.length ? <span className="rounded-full bg-white px-3 py-1">帧号：{issue.frames.join(", ")}</span> : null}
                              </div>
                            ) : null}
                          </article>
                        ))
                      ) : (
                        <p className="rounded-[20px] bg-slate-50 px-4 py-5 text-sm text-slate-500">没有识别到明显问题。</p>
                      )}
                    </div>
                  ) : null}

                  <div className="min-w-0 space-y-3">
                    <h3 className="text-sm font-semibold text-slate-900">{isParentMode ? "下一步练习" : "先练这几项"}</h3>
                    {visibleImprovements.length ? (
                      visibleImprovements.map((improvement, index) => (
                        <article key={`${improvement.target}-${index}`} className="rounded-[20px] bg-slate-50 p-4">
                          <p className="text-sm font-semibold text-blue-500">{improvement.target}</p>
                          <p className="mt-2 text-sm leading-7 text-slate-600">{improvement.action}</p>
                        </article>
                      ))
                    ) : (
                      <p className="rounded-[20px] bg-slate-50 px-4 py-5 text-sm text-slate-500">今天表现很棒，继续保持稳定节奏。</p>
                    )}
                  </div>
                </div>
              </ReportCard>

              {(hasReliableSubscores && subscores) || (isParentMode && (subscores || reportDataQuality !== "good")) ? (
                <ReportCard title="分项评分" eyebrow="Subscores">
                  {hasReliableSubscores && subscores ? (
                    <div className="grid min-w-0 gap-6 ipad:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
                      <SubscoreRadarChart subscores={subscores} />
                      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                        {Object.entries(subscores).map(([key, value]) => (
                          <article key={key} className="rounded-[20px] bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">{SUBSCORE_LABELS[key] ?? key}</p>
                            <p className="mt-3 text-2xl font-semibold text-slate-900">{value}</p>
                          </article>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-[20px] border border-slate-200 bg-slate-50 p-5">
                      <p className="text-base font-semibold text-slate-900">数据有限，暂不提供可靠分项评分</p>
                      <p className="mt-2 text-sm leading-7 text-slate-500">当前视频关键帧不足，或识别稳定性不够，继续展示五项数字容易造成误导。</p>
                    </div>
                  )}
                  <p className="mt-4 text-sm text-slate-500">数据质量：{DATA_QUALITY_LABELS[reportDataQuality] ?? reportDataQuality}</p>
                </ReportCard>
              ) : null}
            </main>

            <aside className="min-w-0 space-y-6">
              {(deferredAnalysis.note || deferredAnalysis.report?.user_note_response || actionConfirmationText || (isParentMode && analysisInputWindowText(deferredAnalysis))) ? (
                <section className="app-card p-5">
                  <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">补充信息</p>
                  <div className="mt-4 space-y-4 text-sm leading-7 text-slate-600">
                    {deferredAnalysis.note ? (
                      <div>
                        <p className="font-semibold text-slate-900">上传备注</p>
                        <p className="mt-1">{deferredAnalysis.note}</p>
                      </div>
                    ) : null}
                    {deferredAnalysis.report?.user_note_response ? (
                      <div>
                        <p className="font-semibold text-slate-900">备注回应</p>
                        <p className="mt-1">{deferredAnalysis.report.user_note_response}</p>
                      </div>
                    ) : null}
                    {actionConfirmationText ? <p className="text-xs font-semibold text-blue-700">视频语义识别：{actionConfirmationText}</p> : null}
                    {isParentMode && (analysisInputWindowText(deferredAnalysis) || analysisWindowFallbackText(deferredAnalysis)) ? (
                      <p className="text-xs text-slate-400">{analysisInputWindowText(deferredAnalysis) ?? analysisWindowFallbackText(deferredAnalysis)}</p>
                    ) : null}
                    {deferredAnalysis.is_slow_motion ? (
                      <span className="inline-flex rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-orange-600">
                        慢动作 {Math.round(deferredAnalysis.source_fps ?? 0)}fps
                      </span>
                    ) : null}
                  </div>
                </section>
              ) : null}

              {isParentMode && !isSuggestionLoading && flattenedSuggestions.length ? (
                <section className="app-card border border-amber-200 bg-amber-50/70 p-5">
                  <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-600">Memory Suggestions</p>
                  <h2 className="mt-2 text-xl font-semibold text-slate-900">{flattenedSuggestions.length} 条记忆更新建议</h2>
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
            </aside>
          </div>
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
          resetTargetLock={retryMode === "analysis"}
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
                  {shareImagePreview.copiedToClipboard
                    ? "已复制到剪贴板，也可以用系统分享保存或发送。"
                    : shareImagePreview.canNativeShare
                      ? "可用系统分享保存到照片或发送给别人。"
                      : "当前浏览器未开放图片分享能力，可下载后保存。"}
                </p>
                <p className="mt-1 text-xs text-slate-400">{Math.max(1, Math.round(shareImagePreview.sizeBytes / 1024))} KB · JPEG</p>
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
                onClick={() => void handleNativeShareImage()}
                disabled={!shareImagePreview.canNativeShare}
                className="min-h-[44px] rounded-full border border-emerald-200 bg-emerald-50 px-5 py-3 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                系统分享/保存
              </button>
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
                下载图片
              </a>
            </div>
          </section>
        </div>
      ) : null}

      {celebrateSkillName ? <UnlockCelebration label={celebrateSkillName} /> : null}
    </div>
  );
}
