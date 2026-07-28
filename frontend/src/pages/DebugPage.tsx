import { CSSProperties, ChangeEvent, FormEvent, PointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import {
  AnalysisDetail,
  AnalysisListItem,
  DebugGoldenLabel,
  DebugGoldenLabelPayload,
  DebugRunDetail,
  DebugRunMode,
  DebugRunSummary,
  GoldenOverrideApplyResponse,
  TargetBBox,
  TargetCandidate,
  createLocalDebugRun,
  createVideoAiDebugRun,
  deleteDebugRun,
  ensureGoldenAnalysisDebugRun,
  applyGoldenOverridesAndRetry,
  confirmDebugTargetLock,
  fetchAnalyses,
  fetchAnalysis,
  fetchDebugGoldenLabel,
  fetchDebugFrameCatalog,
  fetchDebugRun,
  fetchDebugRuns,
  saveDebugGoldenLabel,
} from "../api/client";
import AnalysisDebugLogPanel from "../components/AnalysisDebugLogPanel";
import { useAppMode } from "../components/AppModeContext";
import { IceMediaPlayer, type IceMediaPlayerHandle } from "../media/IceMediaPlayer";
import ProviderMetricsPanel from "../components/ProviderMetricsPanel";
import { getAnalysisStatusLabel } from "../constants/analysisStatus";
import { apiDateTimeFormatter, parseApiDate } from "../utils/datetime";
import { readVideoDuration, shouldShowManualWindow, validateManualWindow } from "../utils/videoMetadata";

type LoadState = "idle" | "loading" | "ready" | "error";
type DebugSource = "analysis" | "upload";
type DebugTab = "overview" | "frames" | "tracking" | "video" | "label" | "raw";
type DebugWorkspace = "debug" | "golden";
type TargetSelectionMode = "candidate" | "manual";

const ACTION_TYPES = ["跳跃", "旋转", "步法", "自由滑"];
const PROFILE_OPTIONS = ["jump", "spin", "step", "spiral"];

const STRATUM_OPTIONS = ["unspecified", "single_skater", "multi_skater", "small_target", "occlusion", "known_bad_keyframes"];
const REVIEW_FLAG_OPTIONS = [
  "identity_switch",
  "target_lost",
  "takeoff_early",
  "takeoff_late",
  "apex_drift",
  "landing_glideout",
  "multi_person_motion_pollution",
];
const KEYFRAME_SPECS: Record<string, Array<{ key: string; label: string }>> = {
  jump: [
    { key: "T", label: "Takeoff" },
    { key: "A", label: "Apex" },
    { key: "L", label: "Landing" },
  ],
  spin: [
    { key: "spin_entry", label: "Entry" },
    { key: "spin_main", label: "Main" },
    { key: "spin_exit", label: "Exit" },
  ],
  step: [{ key: "step_sequence", label: "Sequence" }],
  spiral: [
    { key: "spiral_entry", label: "Entry" },
    { key: "spiral_hold", label: "Hold" },
    { key: "spiral_exit", label: "Exit" },
  ],
};

interface LabelFrameRow {
  id: string;
  title: string;
  source: "sampled" | "semantic" | "partial";
  url?: string;
  timestamp: number | null;
  bboxKey: string;
  poseFrame?: Record<string, unknown>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function asNumber(value: unknown): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return value;
}

function frameIdFromName(value: unknown) {
  return String(value ?? "").replace(/\.jpg$/i, "");
}

function keypointTone(id: number) {
  if ([0, 11, 12, 23, 24].includes(id)) {
    return "#f8fafc";
  }
  if ([11, 12, 13, 14, 15, 16].includes(id)) {
    return "#34d399";
  }
  if ([23, 24, 25, 26, 27, 28, 29, 30, 31, 32].includes(id)) {
    return "#f59e0b";
  }
  return "#38bdf8";
}

function bboxStyle(value: unknown) {
  const bbox = asRecord(value);
  const x = asNumber(bbox.x);
  const y = asNumber(bbox.y);
  const width = asNumber(bbox.width);
  const height = asNumber(bbox.height);
  if (x == null || y == null || width == null || height == null) {
    return null;
  }
  return {
    left: `${Math.max(0, Math.min(1, x)) * 100}%`,
    top: `${Math.max(0, Math.min(1, y)) * 100}%`,
    width: `${Math.max(0, Math.min(1, width)) * 100}%`,
    height: `${Math.max(0, Math.min(1, height)) * 100}%`,
  };
}

function normalizedBBox(value: unknown): { x: number; y: number; width: number; height: number } | null {
  const bbox = asRecord(value);
  const x = asNumber(bbox.x);
  const y = asNumber(bbox.y);
  const width = asNumber(bbox.width);
  const height = asNumber(bbox.height);
  if (x == null || y == null || width == null || height == null) {
    return null;
  }
  return {
    x: Math.max(0, Math.min(1, x)),
    y: Math.max(0, Math.min(1, y)),
    width: Math.max(0, Math.min(1, width)),
    height: Math.max(0, Math.min(1, height)),
  };
}

function cropBoundsToBBox(value: unknown): { x: number; y: number; width: number; height: number } | null {
  const bounds = asArray(value).map((item) => asNumber(item));
  if (bounds.length < 4 || bounds.some((item) => item == null)) {
    return null;
  }
  const frameWidth = 854;
  const frameHeight = 480;
  const [left, top, right, bottom] = bounds as number[];
  return normalizedBBox({
    x: left / frameWidth,
    y: top / frameHeight,
    width: (right - left) / frameWidth,
    height: (bottom - top) / frameHeight,
  });
}

function normalizeDragBox(start: { x: number; y: number }, end: { x: number; y: number }): TargetBBox {
  const x1 = Math.max(0, Math.min(1, Math.min(start.x, end.x)));
  const y1 = Math.max(0, Math.min(1, Math.min(start.y, end.y)));
  const x2 = Math.max(0, Math.min(1, Math.max(start.x, end.x)));
  const y2 = Math.max(0, Math.min(1, Math.max(start.y, end.y)));
  return {
    x: Number(x1.toFixed(4)),
    y: Number(y1.toFixed(4)),
    width: Number((x2 - x1).toFixed(4)),
    height: Number((y2 - y1).toFixed(4)),
  };
}

function candidateFromRecord(value: unknown): TargetCandidate | null {
  const candidate = asRecord(value);
  const bbox = asRecord(candidate.bbox);
  const x = asNumber(bbox.x);
  const y = asNumber(bbox.y);
  const width = asNumber(bbox.width);
  const height = asNumber(bbox.height);
  const confidence = asNumber(candidate.confidence) ?? 0;
  const id = typeof candidate.id === "string" ? candidate.id : "";
  if (!id || x == null || y == null || width == null || height == null) {
    return null;
  }
  return {
    id,
    bbox: { x, y, width, height },
    confidence,
    source: typeof candidate.source === "string" ? candidate.source : "debug",
  };
}

function formatDate(value: string) {
  return apiDateTimeFormatter({
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(value));
}

function formatDuration(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return `${value.toFixed(2)}s`;
}

function scoreTone(score: number | null) {
  if (score == null) {
    return "bg-slate-100 text-slate-500";
  }
  if (score >= 80) {
    return "bg-emerald-50 text-emerald-700";
  }
  if (score >= 65) {
    return "bg-amber-50 text-amber-700";
  }
  return "bg-rose-50 text-rose-600";
}

function statusTone(status: string) {
  if (status === "completed") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (status === "failed") {
    return "bg-rose-100 text-rose-600";
  }
  if (status === "awaiting_target_selection" || status === "pending") {
    return "bg-amber-100 text-amber-700";
  }
  return "bg-blue-100 text-blue-700";
}

function modeLabel(mode: string) {
  if (mode === "local_pose_keyframes") {
    return "本地骨架关键帧";
  }
  if (mode === "video_ai_keyframes") {
    return "视频 AI 关键帧";
  }
  return mode;
}

function sourceLabel(source: string) {
  return source === "analysis" ? "历史记录" : "新上传";
}

function samplingSourceLabel(value: unknown) {
  if (value === "analysis_replay") {
    return "正式采样回放";
  }
  if (value === "formal_pipeline_resample") {
    return "正式路径重采样";
  }
  if (value === "upload_formal_pipeline") {
    return "上传正式路径";
  }
  return typeof value === "string" && value ? value : "-";
}

function buildTitle(item: AnalysisListItem) {
  const parts = [item.skater_name, item.action_type, item.action_subtype].filter(Boolean);
  return parts.join(" · ") || item.id;
}

function metricFromSummary(run: DebugRunSummary, key: string) {
  const summary = asRecord(run.summary);
  const timings = asRecord(summary.timings);
  return timings[key];
}

function stageLabelFromSummary(value: unknown) {
  const summary = asRecord(value);
  if (typeof summary.stage_label === "string" && summary.stage_label.trim()) {
    return summary.stage_label;
  }
  if (typeof summary.stage === "string" && summary.stage.trim()) {
    return summary.stage.replace(/_/g, " ");
  }
  return null;
}

function progressFromSummary(value: unknown) {
  const progress = asNumber(asRecord(value).progress);
  return progress == null ? null : Math.max(0, Math.min(1, progress));
}

function goldenStatusFromRun(run: DebugRunSummary) {
  const summary = asRecord(run.summary);
  return typeof summary.golden_label_status === "string" ? summary.golden_label_status : "unlabeled";
}

function evalStatusFromRun(run: DebugRunSummary) {
  const summary = asRecord(run.summary);
  return typeof summary.eval_status === "string" ? summary.eval_status : goldenStatusFromRun(run);
}

function keyframeRows(value: unknown, poseFrameById: Map<string, Record<string, unknown>>) {
  const candidates = asRecord(value);
  return ["T", "A", "L"].map((label) => {
    const candidate = asRecord(candidates[label]);
    const frameId = typeof candidate.frame_id === "string" ? candidate.frame_id : null;
    const poseFrame = frameId ? poseFrameById.get(frameId) : undefined;
    return {
      label,
      frameId,
      timestamp: candidate.timestamp,
      confidence: asNumber(candidate.confidence),
      warnings: asStringArray(candidate.warnings),
      poseState: typeof poseFrame?.tracking_state === "string" ? poseFrame.tracking_state : null,
      poseConfidence: asNumber(poseFrame?.tracking_confidence),
    };
  });
}

function profileForLabel(run: DebugRunDetail, draftProfile?: string | null) {
  const raw = String(draftProfile || run.analysis_profile || run.action_type || "").toLowerCase();
  if (raw.includes("spin") || raw.includes("旋")) {
    return "spin";
  }
  if (raw.includes("step") || raw.includes("步")) {
    return "step";
  }
  if (raw.includes("spiral") || raw.includes("燕") || raw.includes("螺旋")) {
    return "spiral";
  }
  return "jump";
}

function numericInputValue(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? "" : String(value);
}

function parseOptionalNumber(value: string) {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function bboxIou(a: unknown, b: unknown) {
  const boxA = normalizedBBox(a);
  const boxB = normalizedBBox(b);
  if (!boxA || !boxB) {
    return null;
  }
  const ax2 = boxA.x + boxA.width;
  const ay2 = boxA.y + boxA.height;
  const bx2 = boxB.x + boxB.width;
  const by2 = boxB.y + boxB.height;
  const ix1 = Math.max(boxA.x, boxB.x);
  const iy1 = Math.max(boxA.y, boxB.y);
  const ix2 = Math.min(ax2, bx2);
  const iy2 = Math.min(ay2, by2);
  if (ix2 <= ix1 || iy2 <= iy1) {
    return 0;
  }
  const inter = (ix2 - ix1) * (iy2 - iy1);
  const union = boxA.width * boxA.height + boxB.width * boxB.height - inter;
  return union > 0 ? inter / union : null;
}

function frameTimestamp(frame: Record<string, unknown> | undefined) {
  return asNumber(frame?.timestamp ?? frame?.timestamp_sec ?? frame?.time_sec);
}

function normalizeKeyframeKey(value: unknown) {
  const raw = String(value ?? "").trim();
  if (["T", "takeoff", "T_takeoff_sec"].includes(raw)) {
    return "T";
  }
  if (["A", "air", "apex", "A_air_sec"].includes(raw)) {
    return "A";
  }
  if (["L", "landing", "L_landing_sec"].includes(raw)) {
    return "L";
  }
  return raw;
}

function predictionKeyframes(run: DebugRunDetail) {
  const result = asRecord(run.result_json);
  const resolved = asRecord(result.resolved_keyframes);
  const keyframes: Record<string, { timestamp: number | null; source: string | null; confidence: number | null }> = {};
  const selected = asArray(resolved.selected).filter(isRecord);
  selected.forEach((item) => {
    const key = normalizeKeyframeKey(item.key ?? item.phase_code ?? item.key_moment);
    const timestamp = asNumber(item.timestamp ?? item.timestamp_sec);
    if (key && timestamp != null) {
      keyframes[key] = {
        timestamp,
        source: typeof item.selection_reason === "string" ? item.selection_reason : typeof resolved.source === "string" ? resolved.source : null,
        confidence: asNumber(item.confidence),
      };
    }
  });
  const candidates = asRecord(result.key_frame_candidates ?? asRecord(result.bio_data).key_frame_candidates);
  Object.entries(candidates).forEach(([key, raw]) => {
    const normalizedKey = normalizeKeyframeKey(key);
    if (keyframes[normalizedKey]) {
      return;
    }
    const candidate = asRecord(raw);
    const timestamp = asNumber(candidate.timestamp);
    if (timestamp != null) {
      keyframes[normalizedKey] = {
        timestamp,
        source: "key_frame_candidates",
        confidence: asNumber(candidate.confidence),
      };
    }
  });
  return keyframes;
}

function predictionBboxes(run: DebugRunDetail) {
  const result = asRecord(run.result_json);
  const targetLock = asRecord(result.target_lock);
  const raw = asArray(targetLock.bbox_per_frame ?? result.bbox_per_frame);
  const output = new Map<string, TargetBBox>();
  raw.forEach((item, index) => {
    const record = asRecord(item);
    const frameIndex = asNumber(record.frame_index ?? record.index) ?? index;
    const bbox = normalizedBBox(isRecord(record.bbox) ? record.bbox : record);
    if (bbox) {
      output.set(String(frameIndex), bbox);
    }
  });
  return output;
}

function buildLabelFrames(
  sampledFrames: Record<string, unknown>[],
  semanticFrames: Record<string, unknown>[],
  partialSemanticFrames: Record<string, unknown>[],
  poseFrameById: Map<string, Record<string, unknown>>,
) {
  const rows: LabelFrameRow[] = [];
  sampledFrames.forEach((frame, index) => {
    const id = String(frame.frame_id ?? frameIdFromName(frame.filename) ?? `frame_${String(index + 1).padStart(4, "0")}`);
    rows.push({
      id,
      title: id,
      source: "sampled",
      url: typeof frame.url === "string" ? frame.url : undefined,
      timestamp: frameTimestamp(frame),
      bboxKey: String(index),
      poseFrame: poseFrameById.get(id),
    });
  });
  semanticFrames.forEach((frame, index) => {
    const id = String(frame.frame_id ?? frameIdFromName(frame.filename) ?? `semantic_${String(index + 1).padStart(4, "0")}`);
    rows.push({
      id,
      title: id,
      source: "semantic",
      url: typeof frame.url === "string" ? frame.url : undefined,
      timestamp: frameTimestamp(frame),
      bboxKey: `semantic:${id}`,
      poseFrame: poseFrameById.get(id),
    });
  });
  partialSemanticFrames.forEach((frame, index) => {
    const id = String(frame.frame_id ?? frameIdFromName(frame.filename) ?? `partial_semantic_${String(index + 1).padStart(4, "0")}`);
    rows.push({
      id,
      title: id,
      source: "partial",
      url: typeof frame.url === "string" ? frame.url : undefined,
      timestamp: frameTimestamp(frame),
      bboxKey: `partial:${id}`,
      poseFrame: poseFrameById.get(id),
    });
  });
  const seen = new Set<string>();
  return rows
    .filter((row) => {
      const key = `${row.source}:${row.id}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .sort((a, b) => (a.timestamp ?? Number.POSITIVE_INFINITY) - (b.timestamp ?? Number.POSITIVE_INFINITY));
}

function defaultLabelDraft(run: DebugRunDetail, label?: DebugGoldenLabel | null): DebugGoldenLabelPayload {
  const result = asRecord(run.result_json);
  const summary = asRecord(run.summary);
  const samplingMetadata = asRecord(result.sampling_metadata);
  const fps = asNumber(label?.fps) ?? asNumber(samplingMetadata.effective_fps) ?? asNumber(summary.effective_fps) ?? null;
  return {
    skater_id: label?.skater_id ?? "",
    action_type: label?.action_type ?? run.action_type,
    action_subtype: label?.action_subtype ?? run.action_subtype,
    analysis_profile: label?.analysis_profile ?? run.analysis_profile,
    stratum: label?.stratum ?? "unspecified",
    fps,
    keyframes: { ...(label?.keyframes ?? {}) },
    target_bboxes: { ...(label?.target_bboxes ?? {}) },
    tracking_anchors: [...(label?.tracking_anchors ?? [])],
    action_window_start_sec: label?.action_window_start_sec ?? null,
    action_window_end_sec: label?.action_window_end_sec ?? null,
    expected_review_flags: [...(label?.expected_review_flags ?? [])],
    notes: label?.notes ?? "",
  };
}

function selectedAnalysisLabel(analysisId: string | null, analyses: AnalysisListItem[]) {
  const item = analyses.find((analysis) => analysis.id === analysisId);
  return item ? buildTitle(item) : "选择正式分析记录";
}

function defaultManualWindowFromAnalysis(analysis: AnalysisDetail | null | undefined) {
  const start = analysis?.manual_action_window_start ?? analysis?.action_window_start;
  const end = analysis?.manual_action_window_end ?? analysis?.action_window_end;
  return {
    start: start == null || Number.isNaN(start) ? "" : String(Number(start.toFixed(3))),
    end: end == null || Number.isNaN(end) ? "" : String(Number(end.toFixed(3))),
  };
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[34rem] overflow-auto rounded-[18px] bg-slate-950 p-4 text-xs leading-6 text-slate-100">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function inputWindowLabel(value: unknown) {
  const inputWindow = asRecord(value);
  const rawMode = typeof inputWindow.input_window_mode === "string" ? inputWindow.input_window_mode : "-";
  const mode =
    rawMode === "full_context"
      ? "全量上下文"
      : rawMode === "manual_window"
        ? "手动片段"
        : rawMode === "system_truncated"
          ? "系统截断"
          : rawMode;
  const start = formatDuration(inputWindow.input_window_start_sec);
  const end = formatDuration(inputWindow.input_window_end_sec);
  const sourceDuration = formatDuration(inputWindow.source_duration_sec);
  const truncated = Boolean(inputWindow.input_window_truncated);
  return {
    mode,
    range: `${start} - ${end}`,
    sourceDuration,
    reason: typeof inputWindow.input_window_reason === "string" ? inputWindow.input_window_reason : "-",
    truncated,
  };
}

function InputWindowPanel({ value }: { value: unknown }) {
  const label = inputWindowLabel(value);
  if (label.mode === "-") {
    return null;
  }
  return (
    <div className={`rounded-[18px] border p-4 ${label.truncated ? "border-amber-200 bg-amber-50" : "border-emerald-100 bg-emerald-50"}`}>
      <p className="text-xs font-semibold text-slate-500">AI 输入范围</p>
      <p className="mt-2 text-sm font-semibold text-slate-900">
        {label.mode} · {label.range}
      </p>
      <p className="mt-1 text-xs text-slate-500">
        source {label.sourceDuration} · {label.reason}
      </p>
    </div>
  );
}

function DebugFrameImage({
  url,
  alt,
  className = "h-full w-full object-contain",
  onImageSize,
}: {
  url?: string;
  alt: string;
  className?: string;
  onImageSize?: (size: { width: number; height: number }) => void;
}) {
  const [failed, setFailed] = useState(false);

  if (!url || failed) {
    return <div className="flex h-full items-center justify-center px-3 text-center text-xs text-slate-400">Frame unavailable</div>;
  }

  return (
    <img
      src={url}
      alt={alt}
      loading="lazy"
      draggable={false}
      onDragStart={(event) => event.preventDefault()}
      onLoad={(event) => {
        const { naturalWidth, naturalHeight } = event.currentTarget;
        if (naturalWidth > 0 && naturalHeight > 0) {
          onImageSize?.({ width: naturalWidth, height: naturalHeight });
        }
      }}
      onError={() => setFailed(true)}
      className={className}
    />
  );
}

function PoseSkeletonOverlay({
  frame,
  connections,
  showLabels = false,
}: {
  frame?: Record<string, unknown>;
  connections: number[][];
  showLabels?: boolean;
}) {
  const rawKeypoints = asArray(frame?.keypoints).filter(isRecord);
  if (!rawKeypoints.length) {
    return null;
  }

  const points = new Map<number, Record<string, unknown>>();
  rawKeypoints.forEach((point) => {
    const id = asNumber(point.id);
    const x = asNumber(point.x);
    const y = asNumber(point.y);
    if (id == null || x == null || y == null) {
      return;
    }
    points.set(id, point);
  });

  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {connections.map(([from, to]) => {
        const a = points.get(from);
        const b = points.get(to);
        const ax = asNumber(a?.x);
        const ay = asNumber(a?.y);
        const bx = asNumber(b?.x);
        const by = asNumber(b?.y);
        const av = asNumber(a?.visibility) ?? 0;
        const bv = asNumber(b?.visibility) ?? 0;
        if (ax == null || ay == null || bx == null || by == null || av < 0.5 || bv < 0.5) {
          return null;
        }
        return (
          <line
            key={`${from}-${to}`}
            x1={ax * 100}
            y1={ay * 100}
            x2={bx * 100}
            y2={by * 100}
            vectorEffect="non-scaling-stroke"
            stroke="rgba(248,250,252,0.92)"
            strokeWidth={showLabels ? 4 : 2.75}
            strokeLinecap="round"
          />
        );
      })}
      {Array.from(points.values()).map((point) => {
        const id = asNumber(point.id);
        const x = asNumber(point.x);
        const y = asNumber(point.y);
        const visibility = asNumber(point.visibility) ?? 0;
        if (id == null || x == null || y == null || visibility < 0.5) {
          return null;
        }
        return (
          <g key={id}>
            <circle
              cx={x * 100}
              cy={y * 100}
              r={showLabels ? 1.35 : 0.95}
              vectorEffect="non-scaling-stroke"
              fill={keypointTone(id)}
              stroke="rgba(2,6,23,0.82)"
              strokeWidth={showLabels ? 1.2 : 0.8}
            />
            {showLabels ? (
              <text x={x * 100 + 1.6} y={y * 100 - 1.2} fill="#f8fafc" fontSize="2.4" paintOrder="stroke" stroke="#020617" strokeWidth="0.7">
                {id}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

function PoseFrameStage({
  frame,
  poseFrame,
  connections,
  title,
}: {
  frame?: Record<string, unknown>;
  poseFrame?: Record<string, unknown>;
  connections: number[][];
  title: string;
}) {
  const url = typeof frame?.url === "string" ? frame.url : undefined;
  const frameId = String(frame?.frame_id ?? frame?.filename ?? title);
  const targetStyle = bboxStyle(poseFrame?.target_bbox);

  return (
    <div className="overflow-hidden rounded-[24px] border border-slate-200 bg-slate-950 shadow-[0_18px_55px_rgba(15,23,42,0.18)]">
      <div className="relative aspect-video min-h-[260px] tablet:min-h-[420px] web:min-h-[540px]">
        <DebugFrameImage url={url} alt={frameId} />
        {targetStyle ? <div className="pointer-events-none absolute border-2 border-cyan-300 shadow-[0_0_0_1px_rgba(8,47,73,0.65)]" style={targetStyle} /> : null}
        <PoseSkeletonOverlay frame={poseFrame} connections={connections} showLabels />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 bg-slate-900 px-4 py-3 text-sm text-slate-200">
        <span className="font-mono">{frameId}</span>
        <span>{formatDuration(frame?.timestamp)}</span>
      </div>
    </div>
  );
}

function DebugTargetSelectionPanel({
  run,
  onSubmitted,
}: {
  run: DebugRunDetail;
  onSubmitted: (id: string) => Promise<void>;
}) {
  const previewRef = useState<HTMLDivElement | null>(null);
  const [previewNode, setPreviewNode] = previewRef;
  const result = asRecord(run.result_json);
  const preview = asRecord(result.target_preview);
  const candidates = asArray(preview.candidates).map(candidateFromRecord).filter((candidate): candidate is TargetCandidate => Boolean(candidate));
  const autoCandidateId = typeof preview.auto_candidate_id === "string" ? preview.auto_candidate_id : null;
  const previewFrameUrl = typeof preview.preview_frame_url === "string" ? preview.preview_frame_url : undefined;
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState<TargetSelectionMode>("candidate");
  const [manualBBox, setManualBBox] = useState<TargetBBox | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftBBox, setDraftBBox] = useState<TargetBBox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const selectedCandidate = candidates.find((candidate) => candidate.id === selectedCandidateId) ?? null;
  const activeBBox = selectionMode === "manual" ? draftBBox ?? manualBBox : selectedCandidate?.bbox ?? null;

  const selectCandidate = (candidateId: string) => {
    setSelectionMode("candidate");
    setSelectedCandidateId(candidateId);
    setManualBBox(null);
    setDraftBBox(null);
    setError(null);
  };

  const enableManualSelection = () => {
    setSelectionMode("manual");
    setSelectedCandidateId(null);
    setError(null);
  };

  const pointFromEvent = (event: PointerEvent<HTMLDivElement>) => {
    const rect = previewNode?.getBoundingClientRect();
    if (!rect) {
      return null;
    }
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (selectionMode !== "manual") {
      return;
    }
    const point = pointFromEvent(event);
    if (!point) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragStart(point);
    setDraftBBox({ x: point.x, y: point.y, width: 0, height: 0 });
    setSelectedCandidateId(null);
    setManualBBox(null);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) {
      return;
    }
    const point = pointFromEvent(event);
    if (point) {
      setDraftBBox(normalizeDragBox(dragStart, point));
    }
  };

  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) {
      return;
    }
    const point = pointFromEvent(event);
    setDragStart(null);
    setDraftBBox(null);
    if (!point) {
      return;
    }
    const bbox = normalizeDragBox(dragStart, point);
    if (bbox.width < 0.02 || bbox.height < 0.02) {
      setError("框选区域太小，请拖出完整身体范围。");
      return;
    }
    setManualBBox(bbox);
    setError(null);
  };

  const handleSubmit = async () => {
    if (!manualBBox && !selectedCandidateId) {
      setError("请先选择自动候选，或切到手动框选。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await confirmDebugTargetLock(
        run.id,
        manualBBox ? { manual_bbox: manualBBox, candidate_id: null } : { candidate_id: selectedCandidateId },
      );
      await onSubmitted(run.id);
    } catch {
      setError("主要人物确认失败，请重新选择。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-[24px] border border-amber-200 bg-amber-50 p-4 tablet:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-600">Target Selection</p>
          <h3 className="mt-2 text-lg font-semibold text-slate-900">请选择这次 debug 的主要人物</h3>
        </div>
        <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-amber-700">awaiting target</span>
      </div>

      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => {
            setSelectionMode("candidate");
            setManualBBox(null);
            setDraftBBox(null);
            setError(null);
          }}
          className={`rounded-full bg-white px-4 py-2 text-sm font-semibold transition ${
            selectionMode === "candidate" ? "text-blue-600 ring-2 ring-blue-100" : "text-slate-600"
          }`}
        >
          自动候选
        </button>
        <button
          type="button"
          onClick={enableManualSelection}
          className={`rounded-full bg-white px-4 py-2 text-sm font-semibold transition ${
            selectionMode === "manual" ? "text-emerald-700 ring-2 ring-emerald-100" : "text-slate-600"
          }`}
        >
          手动框选
        </button>
      </div>

      {selectionMode === "manual" ? (
        <p className="mt-3 rounded-[18px] bg-white px-4 py-3 text-sm text-emerald-700">
          在画面中按住并拖拽，框出主要人物完整身体范围。
        </p>
      ) : null}

      <div
        ref={setPreviewNode}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        className="relative mt-4 touch-none overflow-hidden rounded-[22px] border border-amber-200 bg-slate-950"
      >
        {previewFrameUrl ? (
          <img src={previewFrameUrl} alt="debug target preview" draggable={false} className="block w-full select-none object-contain" />
        ) : (
          <div className="flex min-h-[260px] items-center justify-center text-sm text-slate-400">Preview frame unavailable</div>
        )}
        {activeBBox ? (
          <div
            className={`pointer-events-none absolute border-2 ${
              selectionMode === "manual" ? "border-emerald-300 bg-emerald-300/15" : "border-blue-300 bg-blue-300/20"
            }`}
            style={{
              left: `${activeBBox.x * 100}%`,
              top: `${activeBBox.y * 100}%`,
              width: `${activeBBox.width * 100}%`,
              height: `${activeBBox.height * 100}%`,
            }}
          />
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {candidates.map((candidate) => (
          <button
            key={candidate.id}
            type="button"
            onClick={() => selectCandidate(candidate.id)}
            className={`rounded-[18px] border px-4 py-3 text-left text-sm transition ${
              candidate.id === selectedCandidateId && !manualBBox ? "border-blue-300 bg-white text-slate-900" : "border-amber-100 bg-white/70 text-slate-600"
            }`}
          >
            <span className="font-semibold">{candidate.id === autoCandidateId ? "自动推荐" : "候选"}</span>
            <span className="ml-2 text-slate-500">{(candidate.confidence * 100).toFixed(0)}%</span>
          </button>
        ))}
      </div>

      {manualBBox ? (
        <p className="mt-3 rounded-[18px] bg-white px-4 py-3 text-sm text-emerald-700">
          已手动框选：x {manualBBox.x.toFixed(2)} / y {manualBBox.y.toFixed(2)} / w {manualBBox.width.toFixed(2)} / h {manualBBox.height.toFixed(2)}
        </p>
      ) : null}
      {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}
      <button
        type="button"
        onClick={() => void handleSubmit()}
        disabled={submitting}
        className="mt-4 min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "提交中..." : "确认主要人物并继续 debug"}
      </button>
    </div>
  );
}

function labelFrameKey(frame: LabelFrameRow) {
  return `${frame.source}:${frame.id}`;
}

function DebugPredictionGoldenPanel({
  run,
  draft,
  keyframeSpecs,
}: {
  run: DebugRunDetail;
  draft: DebugGoldenLabelPayload;
  keyframeSpecs: Array<{ key: string; label: string }>;
}) {
  const predictedKeyframes = useMemo(() => predictionKeyframes(run), [run]);
  const predictedBboxes = useMemo(() => predictionBboxes(run), [run]);
  const bboxRows = Object.entries(draft.target_bboxes ?? {}).map(([frameIndex, golden]) => {
    const predicted = predictedBboxes.get(frameIndex);
    return {
      frameIndex,
      golden,
      predicted,
      iou: bboxIou(golden, predicted),
    };
  });

  return (
    <div className="rounded-[18px] border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-slate-900">Prediction vs Golden</p>
          <p className="mt-1 text-xs text-slate-500">Current debug output compared with this draft label.</p>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="py-2 pr-3 font-semibold">Key</th>
              <th className="py-2 pr-3 font-semibold">Pred</th>
              <th className="py-2 pr-3 font-semibold">Golden</th>
              <th className="py-2 pr-3 font-semibold">Delta</th>
              <th className="py-2 pr-3 font-semibold">Source</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {keyframeSpecs.map((spec) => {
              const predicted = predictedKeyframes[spec.key];
              const golden = draft.keyframes?.[spec.key] ?? null;
              const delta = predicted?.timestamp != null && golden != null ? predicted.timestamp - golden : null;
              const ok = delta == null || Math.abs(delta) <= 0.25;
              return (
                <tr key={spec.key}>
                  <td className="py-2 pr-3 font-semibold text-slate-900">{spec.key}</td>
                  <td className="py-2 pr-3 font-mono text-slate-700">{formatDuration(predicted?.timestamp)}</td>
                  <td className="py-2 pr-3 font-mono text-slate-700">{formatDuration(golden)}</td>
                  <td className={`py-2 pr-3 font-mono font-semibold ${ok ? "text-emerald-700" : "text-rose-600"}`}>
                    {delta == null ? "-" : `${delta >= 0 ? "+" : ""}${delta.toFixed(3)}s`}
                  </td>
                  <td className="max-w-[180px] truncate py-2 pr-3 text-slate-500" title={predicted?.source ?? ""}>
                    {predicted?.source ?? "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 space-y-2">
        <p className="text-xs font-semibold text-slate-500">Target bbox IoU</p>
        {bboxRows.length ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {bboxRows.map((row) => (
              <div key={row.frameIndex} className="rounded-[14px] border border-slate-100 bg-slate-50 px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-mono font-semibold text-slate-800">frame {row.frameIndex}</span>
                  <span className={`font-semibold ${(row.iou ?? 0) >= 0.3 ? "text-emerald-700" : "text-rose-600"}`}>
                    {row.iou == null ? "missing" : row.iou.toFixed(3)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No golden bboxes yet.</p>
        )}
      </div>
    </div>
  );
}

function DebugGoldenLabelPanel({
  run,
  sampledFrames,
  semanticFrames,
  partialSemanticFrames,
  poseFrameById,
  connections,
  onSaved,
}: {
  run: DebugRunDetail;
  sampledFrames: Record<string, unknown>[];
  semanticFrames: Record<string, unknown>[];
  partialSemanticFrames: Record<string, unknown>[];
  poseFrameById: Map<string, Record<string, unknown>>;
  connections: number[][];
  onSaved?: () => void;
}) {
  const videoRef = useRef<IceMediaPlayerHandle | null>(null);
  const [frameNode, setFrameNode] = useState<HTMLDivElement | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [saveState, setSaveState] = useState<LoadState>("idle");
  const [applyState, setApplyState] = useState<LoadState>("idle");
  const [applyResult, setApplyResult] = useState<GoldenOverrideApplyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedLabel, setSavedLabel] = useState<DebugGoldenLabel | null>(null);
  const [draft, setDraft] = useState<DebugGoldenLabelPayload>(() => defaultLabelDraft(run, null));
  const [flagsText, setFlagsText] = useState("");
  const [selectedFrameKey, setSelectedFrameKey] = useState<string | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftBBox, setDraftBBox] = useState<TargetBBox | null>(null);
  const [frameImageSizes, setFrameImageSizes] = useState<Record<string, { width: number; height: number }>>({});
  const [videoError, setVideoError] = useState(false);
  const [videoCursorTime, setVideoCursorTime] = useState<number | null>(null);
  const [catalogFrames, setCatalogFrames] = useState<LabelFrameRow[]>([]);

  const labelFrames = useMemo(() => {
    const resultFrames = buildLabelFrames(sampledFrames, semanticFrames, partialSemanticFrames, poseFrameById);
    const byKey = new Map(resultFrames.map((frame) => [labelFrameKey(frame), frame]));
    catalogFrames.forEach((frame) => {
      const key = labelFrameKey(frame);
      const existing = byKey.get(key);
      byKey.set(
        key,
        existing
          ? {
              ...frame,
              ...existing,
              url: frame.url ?? existing.url,
              timestamp: existing.timestamp ?? frame.timestamp,
            }
          : frame,
      );
    });
    return Array.from(byKey.values()).sort(
      (a, b) => (a.timestamp ?? Number.POSITIVE_INFINITY) - (b.timestamp ?? Number.POSITIVE_INFINITY),
    );
  }, [catalogFrames, partialSemanticFrames, poseFrameById, sampledFrames, semanticFrames]);
  const selectedFrame = labelFrames.find((frame) => labelFrameKey(frame) === selectedFrameKey) ?? labelFrames[0] ?? null;
  const selectedFrameStableKey = selectedFrame ? labelFrameKey(selectedFrame) : null;
  const selectedImageSize = selectedFrameStableKey ? frameImageSizes[selectedFrameStableKey] : null;
  const selectedAspectRatio = selectedImageSize && selectedImageSize.height > 0 ? selectedImageSize.width / selectedImageSize.height : 16 / 9;
  const labelStageStyle: CSSProperties = { aspectRatio: `${selectedAspectRatio}` };
  const labelProfile = profileForLabel(run, draft.analysis_profile);
  const keyframeSpecs = KEYFRAME_SPECS[labelProfile] ?? KEYFRAME_SPECS.jump;
  const savedBBox = selectedFrame ? draft.target_bboxes[selectedFrame.bboxKey] : null;
  const savedBBoxStyle = bboxStyle(savedBBox);
  const draftBBoxStyle = bboxStyle(draftBBox);
  const poseBBoxStyle = bboxStyle(selectedFrame?.poseFrame?.target_bbox);
  const videoSrc = `/api/debug/runs/${encodeURIComponent(run.id)}/video`;

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    setError(null);
    setSaveState("idle");
    setApplyState("idle");
    setApplyResult(null);
    setSavedLabel(null);
    setDraft(defaultLabelDraft(run, null));
    setFlagsText("");
    setDraftBBox(null);
    setVideoError(false);
    setVideoCursorTime(null);
    setCatalogFrames([]);
    const load = async () => {
      try {
        const [data, catalog] = await Promise.all([
          fetchDebugGoldenLabel(run.id),
          fetchDebugFrameCatalog(run.id).catch(() => null),
        ]);
        if (cancelled) {
          return;
        }
        setSavedLabel(data.exists ? data : null);
        setDraft(defaultLabelDraft(run, data));
        setFlagsText((data.expected_review_flags ?? []).join(", "));
        setCatalogFrames(
          (catalog?.frames ?? []).map((frame) => ({
            id: frame.frame_id,
            title: frame.frame_id,
            source: frame.source,
            url: frame.url,
            timestamp: frame.timestamp,
            bboxKey: `${frame.source}:${frame.frame_id}`,
            poseFrame: poseFrameById.get(frame.frame_id),
          })),
        );
        setState("ready");
      } catch {
        if (!cancelled) {
          setState("error");
          setError("Golden label failed to load.");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [run.id]);

  useEffect(() => {
    if (!labelFrames.length) {
      setSelectedFrameKey(null);
      return;
    }
    setSelectedFrameKey((current) => {
      if (current && labelFrames.some((frame) => labelFrameKey(frame) === current)) {
        return current;
      }
      return labelFrameKey(labelFrames[0]);
    });
  }, [labelFrames]);

  const updateDraft = (patch: Partial<DebugGoldenLabelPayload>) => {
    setDraft((current) => ({ ...current, ...patch }));
  };

  const seekVideoTo = (timestamp: number | null | undefined, options?: { play?: boolean }) => {
    if (timestamp == null || Number.isNaN(timestamp)) {
      setError("No timestamp available for video verification.");
      return;
    }
    const nextTime = Math.max(0, timestamp);
    videoRef.current?.seek(nextTime, { play: options?.play });
    setVideoCursorTime(nextTime);
  };

  const setKeyframeFromSelected = (key: string) => {
    if (!selectedFrame || selectedFrame.timestamp == null) {
      setError("Selected frame has no timestamp.");
      return;
    }
    setError(null);
    seekVideoTo(selectedFrame.timestamp, { play: true });
    setDraft((current) => ({
      ...current,
      keyframes: { ...current.keyframes, [key]: Number(selectedFrame.timestamp!.toFixed(3)) },
    }));
  };

  const setKeyframeValue = (key: string, value: string) => {
    setDraft((current) => ({
      ...current,
      keyframes: { ...current.keyframes, [key]: parseOptionalNumber(value) },
    }));
  };

  const clearKeyframe = (key: string) => {
    setDraft((current) => {
      const next = { ...current.keyframes };
      delete next[key];
      return { ...current, keyframes: next };
    });
  };

  const pointFromEvent = (event: PointerEvent<HTMLDivElement>) => {
    const rect = frameNode?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) {
      return null;
    }
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!selectedFrame) {
      setError("Select a frame before drawing a target bbox.");
      return;
    }
    event.preventDefault();
    const point = pointFromEvent(event);
    if (!point) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragStart(point);
    setDraftBBox({ x: point.x, y: point.y, width: 0, height: 0 });
    setError(null);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) {
      return;
    }
    const point = pointFromEvent(event);
    if (point) {
      setDraftBBox(normalizeDragBox(dragStart, point));
    }
  };

  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) {
      return;
    }
    event.preventDefault();
    const point = pointFromEvent(event);
    setDragStart(null);
    setDraftBBox(null);
    if (!point || !selectedFrame) {
      return;
    }
    const bbox = normalizeDragBox(dragStart, point);
    if (bbox.width < 0.02 || bbox.height < 0.02) {
      setError("Target bbox is too small.");
      return;
    }
    setDraft((current) => ({
      ...current,
      target_bboxes: { ...current.target_bboxes, [selectedFrame.bboxKey]: bbox },
      tracking_anchors:
        selectedFrame.timestamp == null
          ? current.tracking_anchors
          : [
              ...current.tracking_anchors.filter(
                (anchor) => Math.abs(anchor.timestamp_sec - selectedFrame.timestamp!) > 0.001,
              ),
              {
                anchor_id: `golden-${selectedFrame.source}-${selectedFrame.id}`,
                timestamp_sec: Number(selectedFrame.timestamp.toFixed(3)),
                source_frame_id: `${selectedFrame.source}:${selectedFrame.id}`,
                bbox,
              },
            ].sort((a, b) => a.timestamp_sec - b.timestamp_sec),
    }));
    setError(null);
  };

  const clearSelectedBBox = () => {
    if (!selectedFrame) {
      return;
    }
    setDraft((current) => {
      const next = { ...current.target_bboxes };
      delete next[selectedFrame.bboxKey];
      return {
        ...current,
        target_bboxes: next,
        tracking_anchors:
          selectedFrame.timestamp == null
            ? current.tracking_anchors
            : current.tracking_anchors.filter(
                (anchor) => Math.abs(anchor.timestamp_sec - selectedFrame.timestamp!) > 0.001,
              ),
      };
    });
  };

  const flagValues = useMemo(
    () =>
      flagsText
        .split(",")
        .map((flag) => flag.trim())
        .filter(Boolean),
    [flagsText],
  );

  const toggleReviewFlag = (flag: string) => {
    const current = new Set(flagValues);
    if (current.has(flag)) {
      current.delete(flag);
    } else {
      current.add(flag);
    }
    setFlagsText(Array.from(current).join(", "));
  };

  const handleSave = async () => {
    setSaveState("loading");
    setError(null);
    try {
      const payload: DebugGoldenLabelPayload = {
        ...draft,
        expected_review_flags: flagsText
          .split(",")
          .map((flag) => flag.trim())
          .filter(Boolean),
      };
      const saved = await saveDebugGoldenLabel(run.id, payload);
      setSavedLabel(saved);
      setDraft(defaultLabelDraft(run, saved));
      setFlagsText((saved.expected_review_flags ?? []).join(", "));
      setSaveState("ready");
      onSaved?.();
    } catch {
      setSaveState("error");
      setError("Golden label failed to save.");
    }
  };

  const handleApplyAndRetry = async () => {
    if (!run.analysis_id) {
      setError("只有来自正式分析的 GOLD 样本才能重新生成报告。");
      return;
    }
    setApplyState("loading");
    setError(null);
    try {
      const saved = await saveDebugGoldenLabel(run.id, {
        ...draft,
        expected_review_flags: flagsText
          .split(",")
          .map((flag) => flag.trim())
          .filter(Boolean),
      });
      setSavedLabel(saved);
      const result = await applyGoldenOverridesAndRetry(run.analysis_id, run.id, saved.revision);
      setApplyResult(result);
      setApplyState("ready");
      onSaved?.();
    } catch {
      setApplyState("error");
      setError("应用 GOLD 并重新分析失败，请检查关键帧顺序和主人物框。");
    }
  };

  if (state === "loading") {
    return <div className="rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">Loading golden label...</div>;
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(300px,0.85fr)]">
        <div className="min-w-0 space-y-4">
          <div
            ref={setFrameNode}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={finishDrag}
            onPointerCancel={finishDrag}
            style={labelStageStyle}
            className="relative mx-auto w-full cursor-crosshair touch-none select-none overflow-hidden rounded-[20px] border border-slate-200 bg-slate-950"
          >
            <DebugFrameImage
              url={selectedFrame?.url}
              alt={selectedFrame?.title ?? "label frame"}
              className="h-full w-full select-none object-fill"
              onImageSize={
                selectedFrameStableKey
                  ? (size) => {
                      setFrameImageSizes((current) => {
                        const previous = current[selectedFrameStableKey];
                        if (previous?.width === size.width && previous.height === size.height) {
                          return current;
                        }
                        return { ...current, [selectedFrameStableKey]: size };
                      });
                    }
                  : undefined
              }
            />
            {poseBBoxStyle ? <div className="pointer-events-none absolute border-2 border-dashed border-cyan-300/80" style={poseBBoxStyle} /> : null}
            {savedBBoxStyle ? <div className="pointer-events-none absolute border-2 border-emerald-300 bg-emerald-300/15" style={savedBBoxStyle} /> : null}
            {draftBBoxStyle ? <div className="pointer-events-none absolute border-2 border-amber-300 bg-amber-300/15" style={draftBBoxStyle} /> : null}
            <PoseSkeletonOverlay frame={selectedFrame?.poseFrame} connections={connections} />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[18px] border border-slate-200 bg-white px-4 py-3 text-sm">
            <div className="min-w-0">
              <p className="truncate font-mono font-semibold text-slate-900">{selectedFrame?.title ?? "No frame"}</p>
              <p className="text-xs text-slate-500">
                {selectedFrame?.source ?? "-"} · {formatDuration(selectedFrame?.timestamp)}
                {selectedFrame?.bboxKey ? ` · bbox ${selectedFrame.bboxKey}` : ""}
              </p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                onClick={clearSelectedBBox}
                disabled={!selectedFrame || !savedBBox}
                className="min-h-[36px] rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear bbox
              </button>
            </div>
          </div>

          <section className="overflow-hidden rounded-[18px] border border-slate-200 bg-white">
            <div className="flex flex-col gap-3 border-b border-slate-100 px-3 py-3 wide:flex-row wide:items-center wide:justify-between wide:px-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">视频验证</p>
                <p className="mt-1 truncate text-sm font-semibold text-slate-900">
                  {videoCursorTime == null ? "等待同步选中帧" : `已同步 ${formatDuration(videoCursorTime)}`}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 wide:flex wide:shrink-0">
                <button
                  type="button"
                  onClick={() => seekVideoTo(selectedFrame?.timestamp)}
                  disabled={!selectedFrame || selectedFrame.timestamp == null || videoError}
                  className="min-h-[36px] rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  跳转帧
                </button>
                <button
                  type="button"
                  onClick={() => seekVideoTo(selectedFrame?.timestamp, { play: true })}
                  disabled={!selectedFrame || selectedFrame.timestamp == null || videoError}
                  className="min-h-[36px] rounded-full bg-slate-900 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  播放帧
                </button>
              </div>
            </div>
            <IceMediaPlayer ref={videoRef} fallbackSrc={videoSrc} onTimeChange={setVideoCursorTime} />
          </section>

          <div className="rounded-[18px] border border-slate-200 bg-white p-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 px-1">
              <p className="text-sm font-semibold text-slate-900">完整关键帧数据</p>
              <p className="text-xs text-slate-500">
                共 {labelFrames.length} 帧 · sampled {sampledFrames.length} · semantic {semanticFrames.length} · partial {partialSemanticFrames.length}
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {labelFrames.map((frame) => {
                const key = labelFrameKey(frame);
                const active = key === labelFrameKey(selectedFrame ?? frame);
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      setSelectedFrameKey(key);
                      setDraftBBox(null);
                      seekVideoTo(frame.timestamp);
                    }}
                    className={`min-w-0 rounded-[14px] border px-3 py-2 text-left text-xs transition ${
                      active ? "border-blue-300 bg-blue-50 text-slate-900" : "border-slate-100 bg-slate-50 text-slate-600 hover:border-blue-100"
                    }`}
                  >
                    <span className="block truncate font-mono font-semibold">{frame.title}</span>
                    <span className="mt-1 block truncate">
                      {frame.source} · {formatDuration(frame.timestamp)}
                    </span>
                  </button>
                );
              })}
            </div>
            {!labelFrames.length ? (
              <div className="rounded-[14px] border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                当前样本没有可展示的关键帧数据，请确认 debug run 已完成。
              </div>
            ) : null}
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <div className="rounded-[18px] border border-slate-200 bg-white p-4">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">Skater ID</span>
                <input value={draft.skater_id ?? ""} onChange={(event) => updateDraft({ skater_id: event.target.value })} className="app-input mt-2 rounded-[14px] text-sm" />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">Profile</span>
                <select value={draft.analysis_profile ?? labelProfile} onChange={(event) => updateDraft({ analysis_profile: event.target.value })} className="app-input mt-2 rounded-[14px] text-sm">
                  {PROFILE_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">Action</span>
                <input value={draft.action_type ?? ""} onChange={(event) => updateDraft({ action_type: event.target.value })} className="app-input mt-2 rounded-[14px] text-sm" />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">Subtype</span>
                <input value={draft.action_subtype ?? ""} onChange={(event) => updateDraft({ action_subtype: event.target.value })} className="app-input mt-2 rounded-[14px] text-sm" />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">Stratum</span>
                <select value={draft.stratum ?? "unspecified"} onChange={(event) => updateDraft({ stratum: event.target.value })} className="app-input mt-2 rounded-[14px] text-sm">
                  {STRATUM_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">FPS</span>
                <input
                  type="number"
                  step="0.001"
                  value={numericInputValue(draft.fps)}
                  onChange={(event) => updateDraft({ fps: parseOptionalNumber(event.target.value) })}
                  className="app-input mt-2 rounded-[14px] text-sm"
                />
              </label>
            </div>
          </div>

          <div className="rounded-[18px] border border-slate-200 bg-white p-4">
            <div className="space-y-3">
              {keyframeSpecs.map((spec) => (
                <div key={spec.key} className="grid grid-cols-[minmax(72px,0.7fr)_minmax(0,1fr)] gap-2 sm:grid-cols-[minmax(82px,0.7fr)_minmax(0,1fr)_auto]">
                  <div className="min-w-0 py-2">
                    <p className="truncate text-sm font-semibold text-slate-900">{spec.key}</p>
                    <p className="truncate text-xs text-slate-500">{spec.label}</p>
                  </div>
                  <input
                    type="number"
                    step="0.001"
                    value={numericInputValue(draft.keyframes[spec.key])}
                    onChange={(event) => setKeyframeValue(spec.key, event.target.value)}
                    className="app-input min-w-0 rounded-[14px] text-sm"
                  />
                  <div className="col-span-2 flex gap-2 sm:col-span-1">
                    <button
                      type="button"
                      onClick={() => setKeyframeFromSelected(spec.key)}
                      disabled={!selectedFrame || selectedFrame.timestamp == null}
                      className="min-h-[40px] flex-1 rounded-full bg-blue-500 px-3 text-xs font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
                    >
                      Set
                    </button>
                    <button
                      type="button"
                      onClick={() => clearKeyframe(spec.key)}
                      className="min-h-[40px] flex-1 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 sm:flex-none"
                    >
                      Clear
                    </button>
                    <button
                      type="button"
                      onClick={() => seekVideoTo(draft.keyframes[spec.key], { play: true })}
                      disabled={draft.keyframes[spec.key] == null || videoError}
                      className="min-h-[40px] flex-1 rounded-full border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
                    >
                      Play
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <DebugPredictionGoldenPanel run={run} draft={draft} keyframeSpecs={keyframeSpecs} />

          <div className="rounded-[18px] border border-slate-200 bg-white p-4">
            <label className="block">
              <span className="text-xs font-semibold text-slate-500">Review flags</span>
              <input value={flagsText} onChange={(event) => setFlagsText(event.target.value)} className="app-input mt-2 rounded-[14px] text-sm" />
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              {REVIEW_FLAG_OPTIONS.map((flag) => {
                const selected = flagValues.includes(flag);
                return (
                  <button
                    key={flag}
                    type="button"
                    onClick={() => toggleReviewFlag(flag)}
                    className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                      selected ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                    }`}
                  >
                    {flag}
                  </button>
                );
              })}
            </div>
            <label className="mt-3 block">
              <span className="text-xs font-semibold text-slate-500">Notes</span>
              <textarea value={draft.notes ?? ""} onChange={(event) => updateDraft({ notes: event.target.value })} rows={4} className="app-input mt-2 min-h-[96px] resize-y rounded-[14px] text-sm" />
            </label>
          </div>

          {error ? <div className="rounded-[18px] border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</div> : null}
          {saveState === "ready" && savedLabel ? (
            <div className="rounded-[18px] border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              草稿已保存 · revision {savedLabel.revision} · {savedLabel.label_path ?? "golden_label.json"}
            </div>
          ) : null}
          {savedLabel?.label_quality_flags?.length ? (
            <div className="rounded-[18px] border border-amber-100 bg-amber-50 px-4 py-3 text-xs text-amber-700">
              {savedLabel.label_quality_flags.join(", ")}
            </div>
          ) : null}
          {applyResult ? (
            <div className="rounded-[18px] border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
              已应用 revision {applyResult.applied_revision}，从 {applyResult.retry_from_stage} 阶段重新分析。
              <Link to={applyResult.report_path} className="ml-2 font-semibold underline">
                查看原报告
              </Link>
            </div>
          ) : null}
          <div className="rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-600">
            将应用 {Object.values(draft.keyframes).filter((value) => value != null).length} 个关键帧和 {draft.tracking_anchors.length} 个人物追踪锚点，
            更新同一个分析报告。
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saveState === "loading" || applyState === "loading"}
              className="min-h-[46px] w-full rounded-full border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saveState === "loading" ? "保存中..." : "保存草稿"}
            </button>
            <button
              type="button"
              onClick={() => void handleApplyAndRetry()}
              disabled={applyState === "loading" || !run.analysis_id}
              className="min-h-[46px] w-full rounded-full bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {applyState === "loading" ? "正在应用并重新分析..." : "应用 GOLD 并重新分析"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DebugRunCard({
  run,
  selected,
  onSelect,
  onDelete,
  deleting,
}: {
  run: DebugRunSummary;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  const summary = asRecord(run.summary);
  const flags = asStringArray(summary.quality_flags).slice(0, 3);
  const total = metricFromSummary(run, "total_s");
  const stageLabel = stageLabelFromSummary(summary);
  const progress = progressFromSummary(summary);
  const showProgress = (run.status === "pending" || run.status === "processing") && progress != null;
  const labelStatus = typeof summary.golden_label_status === "string" ? summary.golden_label_status : "unlabeled";
  const evalStatus = typeof summary.eval_status === "string" ? summary.eval_status : labelStatus;
  const evalTone =
    evalStatus === "passes"
      ? "bg-emerald-50 text-emerald-700"
      : evalStatus === "fails"
        ? "bg-rose-50 text-rose-600"
        : evalStatus === "labeled"
          ? "bg-blue-50 text-blue-700"
          : "bg-slate-100 text-slate-500";

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      className={`w-full min-w-0 max-w-full overflow-hidden rounded-[20px] border px-4 py-4 text-left transition ${
        selected ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-100 hover:bg-slate-50"
      }`}
    >
      <div className="flex min-w-0 flex-col gap-3 phone:flex-row phone:items-start phone:justify-between">
        <div className="min-w-0 max-w-full">
          <p className="truncate text-sm font-semibold text-slate-900">{modeLabel(run.mode)}</p>
          <p className="mt-1 text-xs text-slate-500">
            {sourceLabel(run.source_type)} · {run.action_subtype || run.action_type}
          </p>
          {stageLabel && (run.status === "pending" || run.status === "processing") ? <p className="mt-2 text-xs font-semibold text-blue-600">{stageLabel}</p> : null}
          {run.note ? <p className="mt-2 max-w-full break-words text-sm leading-6 text-slate-600">{run.note}</p> : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusTone(run.status)}`}>{run.status}</span>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onDelete();
            }}
            onKeyDown={(event) => event.stopPropagation()}
            disabled={deleting || run.status === "processing"}
            className="rounded-full border border-rose-100 bg-white px-3 py-1 text-xs font-semibold text-rose-600 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
            title={run.status === "processing" ? "processing run cannot be deleted" : "delete debug run"}
          >
            {deleting ? "Deleting" : "Delete"}
          </button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">{formatDate(run.created_at)}</span>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">total {formatDuration(total)}</span>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${evalTone}`}>{evalStatus}</span>
      </div>
      {showProgress ? (
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      ) : null}
      {flags.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {flags.map((flag) => (
            <span key={flag} className="max-w-full break-words rounded-full bg-white px-2.5 py-1 text-xs text-slate-500">
              {flag}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function AnalysisLogSelector({
  analyses,
  selectedId,
  onSelect,
  listState,
}: {
  analyses: AnalysisListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  listState: LoadState;
}) {
  return (
    <section className="app-card p-6 tablet:p-7">
      <div className="mb-5">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">Official Logs</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-900">正式分析记录</h2>
      </div>
      <div className="space-y-3">
        {listState === "loading" ? <p className="text-sm text-slate-500">正在加载分析记录...</p> : null}
        {listState === "error" ? <p className="text-sm text-rose-600">分析记录加载失败。</p> : null}
        {listState === "ready" && !analyses.length ? (
          <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            暂时还没有可查看的分析记录。
          </div>
        ) : null}
        <div className="max-h-[34rem] space-y-3 overflow-y-auto pr-1">
          {analyses.map((item) => {
            const selected = item.id === selectedId;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelect(item.id)}
                className={`w-full rounded-[20px] border px-4 py-4 text-left transition ${
                  selected ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-100 hover:bg-slate-50"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-900">{buildTitle(item)}</p>
                    <p className="mt-1 text-xs text-slate-500">{formatDate(item.created_at)}</p>
                  </div>
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusTone(item.status)}`}>
                    {getAnalysisStatusLabel(item.status)}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ${scoreTone(item.force_score)}`}>
                    {item.force_score == null ? "未评分" : `${item.force_score} 分`}
                  </span>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
                    {item.pipeline_version ?? "pipeline unknown"}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function DebugRunForm({
  mode,
  analyses,
  defaultAnalysisId,
  selectedAnalysisDetail,
  onAnalysisChange,
  onCreated,
}: {
  mode: DebugRunMode;
  analyses: AnalysisListItem[];
  defaultAnalysisId: string | null;
  selectedAnalysisDetail?: AnalysisDetail | null;
  onAnalysisChange?: (id: string | null) => void;
  onCreated: (id: string) => void;
}) {
  const [source, setSource] = useState<DebugSource>("analysis");
  const [analysisId, setAnalysisId] = useState(defaultAnalysisId ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [actionType, setActionType] = useState(ACTION_TYPES[0]);
  const [actionSubtype, setActionSubtype] = useState("");
  const [analysisProfile, setAnalysisProfile] = useState(mode === "local_pose_keyframes" ? "jump" : "");
  const [note, setNote] = useState("");
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [videoDurationSec, setVideoDurationSec] = useState<number | null>(null);
  const [manualWindowStart, setManualWindowStart] = useState("");
  const [manualWindowEnd, setManualWindowEnd] = useState("");

  useEffect(() => {
    if (!analysisId && defaultAnalysisId) {
      setAnalysisId(defaultAnalysisId);
    }
  }, [analysisId, defaultAnalysisId]);

  useEffect(() => {
    if (source !== "analysis" || selectedAnalysisDetail?.id !== analysisId) {
      return;
    }
    const nextWindow = defaultManualWindowFromAnalysis(selectedAnalysisDetail);
    setManualWindowStart((current) => current || nextWindow.start);
    setManualWindowEnd((current) => current || nextWindow.end);
  }, [analysisId, selectedAnalysisDetail, source]);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    setFile(nextFile);
    setVideoDurationSec(null);
    setManualWindowStart("");
    setManualWindowEnd("");
    if (nextFile) {
      void readVideoDuration(nextFile)
        .then((duration) => setVideoDurationSec(duration))
        .catch(() => setVideoDurationSec(null));
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setState("loading");
    setError(null);
    try {
      const payload: Parameters<typeof createLocalDebugRun>[0] = {
        analysisId: source === "analysis" ? analysisId : null,
        file: source === "upload" ? file : null,
        actionType: source === "upload" ? actionType : null,
        actionSubtype: source === "upload" ? actionSubtype : null,
        analysisProfile: analysisProfile || null,
        note: note.trim() || null,
      };
      if (source === "analysis" && !payload.analysisId) {
        throw new Error("请选择一条正式分析记录。");
      }
      if (source === "upload" && !payload.file) {
        throw new Error("请选择要调试的视频文件。");
      }
      const windowError = validateManualWindow(
        manualWindowStart,
        manualWindowEnd,
        source === "upload" ? videoDurationSec : selectedAnalysisDetail?.source_duration_sec ?? null,
      );
      if (windowError) {
        throw new Error(windowError);
      }
      if (manualWindowStart.trim() && manualWindowEnd.trim()) {
        payload.manualActionWindowStartSec = manualWindowStart.trim();
        payload.manualActionWindowEndSec = manualWindowEnd.trim();
      }
      const response = mode === "local_pose_keyframes" ? await createLocalDebugRun(payload) : await createVideoAiDebugRun(payload);
      setState("ready");
      onCreated(response.id);
    } catch (requestError) {
      setState("error");
      setError(requestError instanceof Error ? requestError.message : "创建 debug run 失败。");
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="rounded-[24px] border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-500">
            {mode === "local_pose_keyframes" ? "Local Pipeline" : "Single Video AI"}
          </p>
          <h3 className="mt-2 text-lg font-semibold text-slate-900">{modeLabel(mode)}</h3>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">{mode === "local_pose_keyframes" ? "No cloud AI" : "Keyframes only"}</span>
      </div>

      <div className="mt-4 grid grid-cols-2 rounded-[18px] bg-slate-100 p-1 text-sm font-semibold text-slate-500">
        <button
          type="button"
          onClick={() => setSource("analysis")}
          className={`min-h-[38px] rounded-[14px] transition ${source === "analysis" ? "bg-white text-slate-900 shadow-sm" : ""}`}
        >
          历史记录
        </button>
        <button
          type="button"
          onClick={() => setSource("upload")}
          className={`min-h-[38px] rounded-[14px] transition ${source === "upload" ? "bg-white text-slate-900 shadow-sm" : ""}`}
        >
          上传视频
        </button>
      </div>

      <div className="mt-4 space-y-3">
        {source === "analysis" ? (
          <>
            <label className="block">
              <span className="text-xs font-semibold text-slate-500">正式分析记录</span>
              <select
                value={analysisId}
                onChange={(event) => {
                  const nextId = event.target.value;
                  setAnalysisId(nextId);
                  onAnalysisChange?.(nextId || null);
                  setManualWindowStart("");
                  setManualWindowEnd("");
                }}
                className="app-select mt-2 rounded-[18px] text-sm"
              >
                <option value="">{selectedAnalysisLabel(null, analyses)}</option>
                {analyses.map((analysis) => (
                  <option key={analysis.id} value={analysis.id}>
                    {buildTitle(analysis)}
                  </option>
                ))}
              </select>
            </label>
            <div className="rounded-[18px] border border-amber-100 bg-amber-50 p-3">
              <p className="text-xs font-semibold text-slate-600">AI 输入片段</p>
              <p className="mt-1 text-xs leading-5 text-slate-500">默认复用这条分析的动作窗口，也可以手动改成要标注的关键帧区间。</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <label className="block">
                  <span className="text-xs font-semibold text-slate-500">开始秒数</span>
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={manualWindowStart}
                    onChange={(event) => setManualWindowStart(event.target.value)}
                    className="app-input mt-1 rounded-[14px] text-sm"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-500">结束秒数</span>
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={manualWindowEnd}
                    onChange={(event) => setManualWindowEnd(event.target.value)}
                    className="app-input mt-1 rounded-[14px] text-sm"
                  />
                </label>
              </div>
            </div>
          </>
        ) : (
          <>
            <label className="block">
              <span className="text-xs font-semibold text-slate-500">视频文件</span>
              <input type="file" accept="video/mp4,video/quicktime,video/x-msvideo,.mp4,.mov,.avi" onChange={handleFileChange} className="app-input mt-2 rounded-[18px] text-sm" />
            </label>
            {videoDurationSec != null ? <p className="text-xs text-slate-500">视频时长：{videoDurationSec.toFixed(2)}s</p> : null}
            {shouldShowManualWindow(videoDurationSec) ? (
              <div className="rounded-[18px] border border-amber-100 bg-amber-50 p-3">
                <p className="text-xs font-semibold text-slate-600">AI 输入片段</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <label className="block">
                    <span className="text-xs font-semibold text-slate-500">开始秒数</span>
                    <input
                      type="number"
                      min="0"
                      step="0.1"
                      value={manualWindowStart}
                      onChange={(event) => setManualWindowStart(event.target.value)}
                      className="app-input mt-1 rounded-[14px] text-sm"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs font-semibold text-slate-500">结束秒数</span>
                    <input
                      type="number"
                      min="0"
                      step="0.1"
                      value={manualWindowEnd}
                      onChange={(event) => setManualWindowEnd(event.target.value)}
                      className="app-input mt-1 rounded-[14px] text-sm"
                    />
                  </label>
                </div>
              </div>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">动作类型</span>
                <select value={actionType} onChange={(event) => setActionType(event.target.value)} className="app-select mt-2 rounded-[18px] text-sm">
                  {ACTION_TYPES.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-500">动作小项</span>
                <input value={actionSubtype} onChange={(event) => setActionSubtype(event.target.value)} placeholder="Axel / 2A / spin..." className="app-input mt-2 rounded-[18px] text-sm" />
              </label>
            </div>
          </>
        )}
        <label className="block">
          <span className="text-xs font-semibold text-slate-500">Profile hint</span>
          <select value={analysisProfile} onChange={(event) => setAnalysisProfile(event.target.value)} className="app-select mt-2 rounded-[18px] text-sm">
            <option value="">自动推断</option>
            {PROFILE_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-500">Note</span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            placeholder="记录这次 debug 的假设、样本来源或要验证的问题"
            className="app-input mt-2 min-h-[84px] resize-y rounded-[18px] text-sm"
          />
        </label>
      </div>

      {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}
      <button
        type="submit"
        disabled={state === "loading"}
        className="mt-5 min-h-[44px] w-full rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {state === "loading" ? "创建中..." : "运行调试入口"}
      </button>
    </form>
  );
}

function DebugRunDetailPanel({
  run,
  activeTab,
  onTabChange,
  onRunRefresh,
  focusMode = "debug",
}: {
  run: DebugRunDetail | null;
  activeTab: DebugTab;
  onTabChange: (tab: DebugTab) => void;
  onRunRefresh: (id: string) => Promise<void>;
  focusMode?: DebugWorkspace;
}) {
  const effectiveActiveTab: DebugTab = focusMode === "golden" ? "label" : activeTab;

  if (!run) {
    return (
      <section className="app-card flex min-h-[32rem] items-center justify-center p-7 text-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">{focusMode === "golden" ? "Golden Label" : "Debug Result"}</p>
          <h2 className="mt-3 text-2xl font-semibold text-slate-900">{focusMode === "golden" ? "选择一个样本继续标注" : "选择或创建一个 debug run"}</h2>
          <p className="mt-3 max-w-md text-sm leading-6 text-slate-500">
            {focusMode === "golden" ? "历史样本会保留已保存的关键帧、bbox、标签和备注。" : "运行结果会保存在独立记录里，不会改写正式分析报告。"}
          </p>
        </div>
      </section>
    );
  }

  const result = asRecord(run.result_json);
  const summary = asRecord(run.summary);
  const sampledFrames = asArray(result.sampled_frames).filter(isRecord);
  const semanticFrames = asArray(result.semantic_frames).filter(isRecord);
  const partialSemanticFrames = asArray(result.partial_semantic_frames).filter(isRecord);
  const poseData = asRecord(result.pose_data);
  const poseFrames = asArray(poseData.frames).filter(isRecord);
  const poseConnections = asArray(poseData.connections)
    .filter(Array.isArray)
    .map((connection) => connection.map((value) => Number(value)).filter((value) => Number.isFinite(value)))
    .filter((connection) => connection.length >= 2);
  const poseFrameById = new Map<string, Record<string, unknown>>();
  poseFrames.forEach((frame) => {
    poseFrameById.set(frameIdFromName(frame.frame), frame);
  });
  const sampledUrlById = new Map<string, string>();
  sampledFrames.forEach((frame) => {
    const frameId = String(frame.frame_id ?? frameIdFromName(frame.filename));
    if (typeof frame.url === "string") {
      sampledUrlById.set(frameId, frame.url);
    }
  });
  const debugPose = poseFrames.length
    ? {
        connections: poseConnections,
        frames: poseFrames.map((frame) => ({
          frame: typeof frame.frame === "string" ? frame.frame : `${frameIdFromName(frame.frame_id)}.jpg`,
          keypoints: asArray(frame.keypoints).filter(isRecord).map((point) => ({
            id: asNumber(point.id) ?? 0,
            name: typeof point.name === "string" ? point.name : String(point.id ?? ""),
            x: asNumber(point.x) ?? 0,
            y: asNumber(point.y) ?? 0,
            z: asNumber(point.z) ?? 0,
            visibility: asNumber(point.visibility) ?? 0,
            interpolated: Boolean(point.interpolated),
          })),
          target_bbox: isRecord(frame.target_bbox)
            ? {
                x: asNumber(asRecord(frame.target_bbox).x) ?? 0,
                y: asNumber(asRecord(frame.target_bbox).y) ?? 0,
                width: asNumber(asRecord(frame.target_bbox).width) ?? 0,
                height: asNumber(asRecord(frame.target_bbox).height) ?? 0,
              }
            : null,
          tracking_confidence: asNumber(frame.tracking_confidence),
          tracking_state: typeof frame.tracking_state === "string" ? frame.tracking_state : null,
          pose_candidates: asArray(frame.pose_candidates).filter(isRecord),
        })),
        frame_urls: Object.fromEntries(
          poseFrames.map((frame) => {
            const frameName = typeof frame.frame === "string" ? frame.frame : `${frameIdFromName(frame.frame_id)}.jpg`;
            const frameId = frameIdFromName(frameName);
            return [frameName, sampledUrlById.get(frameId) ?? ""];
          }),
        ),
      }
    : null;
  const targetLock = asRecord(result.target_lock);
  const trackerSummary = asRecord(result.tracker_summary);
  const poseSummary = asRecord(result.pose_summary);
  const trackerDiagnostics = asArray(targetLock.person_tracker_diagnostics).filter(isRecord);
  const trackerDiagnosticsByFrame = Object.fromEntries(
    trackerDiagnostics.map((item) => {
      const frameId = frameIdFromName(item.frame ?? item.frame_id ?? `frame_${String((asNumber(item.frame_index) ?? 0) + 1).padStart(4, "0")}`);
      const rejectedCandidates = asArray(item.rejected_candidates)
        .filter(isRecord)
        .map((candidate) => ({
          bbox: normalizedBBox(candidate.bbox),
          reasons: asStringArray(candidate.reasons),
          source: typeof candidate.source === "string" ? candidate.source : null,
          trackerId: asNumber(candidate.tracker_id),
          confidence: asNumber(candidate.candidate_confidence),
        }))
        .filter((candidate) => candidate.bbox);
      return [
        frameId,
        {
          state: typeof item.state === "string" ? item.state : null,
          rejectedCandidates,
          predictionBBox: normalizedBBox(item.prediction_bbox),
          localCropBBox: cropBoundsToBBox(item.local_crop_bounds),
        },
      ];
    }),
  );
  const videoTemporal = asRecord(result.video_temporal);
  const resolved = asRecord(result.resolved_keyframes);
  const motionScores = asRecord(result.motion_scores);
  const samplingMetadata = asRecord(result.sampling_metadata);
  const inputWindow = result.input_window ?? summary.input_window ?? motionScores.input_window;
  const effectiveTimestampSource =
    typeof result.effective_timestamp_source === "string"
      ? result.effective_timestamp_source
      : summary.used_semantic_frames === false
        ? "sampled_frames"
        : typeof summary.resolved_source === "string"
          ? summary.resolved_source
          : typeof resolved.source === "string"
            ? resolved.source
            : "-";
  const resolverSource = typeof summary.resolver_source === "string" ? summary.resolver_source : typeof resolved.source === "string" ? resolved.source : "-";
  const rawResponseExcerpt = typeof videoTemporal.raw_response_excerpt === "string" ? videoTemporal.raw_response_excerpt : "";
  const parseErrorDetail = typeof videoTemporal.parse_error_detail === "string" ? videoTemporal.parse_error_detail : "";
  const keyframes = keyframeRows(result.key_frame_candidates ?? asRecord(result.bio_data).key_frame_candidates, poseFrameById);
  const qualityFlags = asStringArray(result.quality_flags ?? summary.quality_flags);
  const retryRejectionFlags = asStringArray(resolved.video_temporal_quality_retry_rejection_flags);
  const stageLabel = stageLabelFromSummary(summary);
  const progress = progressFromSummary(summary);
  const showProgress = (run.status === "pending" || run.status === "processing") && progress != null;

  const tabs: Array<{ id: DebugTab; label: string }> =
    focusMode === "golden"
      ? [{ id: "label", label: "Golden Label" }]
      : [
          { id: "overview", label: "Overview" },
          { id: "frames", label: "Frames" },
          { id: "tracking", label: "Tracking/Pose" },
          { id: "video", label: "Video AI" },
          { id: "label", label: "Golden Label" },
          { id: "raw", label: "Raw JSON" },
        ];

  return (
    <section className="app-card min-w-0 overflow-hidden p-6 tablet:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Debug Result</p>
          <h2 className="mt-2 truncate text-2xl font-semibold text-slate-900">{modeLabel(run.mode)}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {sourceLabel(run.source_type)} · {run.action_subtype || run.action_type} · {run.analysis_profile ?? "auto"}
          </p>
          {run.note ? <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">{run.note}</p> : null}
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusTone(run.status)}`}>{run.status}</span>
      </div>

      {run.error_detail ? <div className="mt-4 rounded-[18px] border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">{run.error_detail}</div> : null}
      {stageLabel && (run.status === "pending" || run.status === "processing") ? (
        <div className="mt-4 rounded-[18px] border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="font-semibold">{stageLabel}</span>
            {progress != null ? <span>{Math.round(progress * 100)}%</span> : null}
          </div>
          {showProgress ? (
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white">
              <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
          ) : null}
        </div>
      ) : null}
      {run.status === "awaiting_target_selection" ? <div className="mt-5"><DebugTargetSelectionPanel run={run} onSubmitted={onRunRefresh} /></div> : null}

      {focusMode === "debug" ? (
        <div className="mt-5 flex gap-2 overflow-x-auto rounded-[18px] bg-slate-100 p-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={`min-h-[38px] shrink-0 rounded-[14px] px-4 text-sm font-semibold transition ${
                effectiveActiveTab === tab.id ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-900"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-5 min-w-0">
        {effectiveActiveTab === "overview" ? (
          <div className="space-y-4">
            <InputWindowPanel value={inputWindow} />
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[18px] border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs font-semibold text-slate-500">总耗时</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{formatDuration(metricFromSummary(run, "total_s"))}</p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs font-semibold text-slate-500">抽帧数</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{String(summary.frame_count ?? sampledFrames.length)}</p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs font-semibold text-slate-500">语义帧</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{String(summary.semantic_frame_count ?? semanticFrames.length)}</p>
                {partialSemanticFrames.length ? (
                  <p className="mt-1 text-xs text-amber-600">partial {String(summary.partial_semantic_frame_count ?? partialSemanticFrames.length)}</p>
                ) : null}
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs font-semibold text-slate-500">Video AI confidence</p>
                <p className="mt-2 text-xl font-semibold text-slate-900">{String(summary.video_ai_confidence ?? "-")}</p>
              </div>
            </div>
            {qualityFlags.length ? (
              <div className="flex flex-wrap gap-2">
                {qualityFlags.map((flag) => (
                  <span key={flag} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
                    {flag}
                  </span>
                ))}
              </div>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Sampling source</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">{samplingSourceLabel(result.sampling_source ?? summary.sampling_source)}</p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Action window</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">
                  {formatDuration(samplingMetadata.action_window_start)} - {formatDuration(samplingMetadata.action_window_end)}
                </p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Effective FPS</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">{String(samplingMetadata.effective_fps ?? "-")}</p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Source FPS</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">{String(samplingMetadata.source_fps ?? "-")}</p>
              </div>
            </div>
            <div className="overflow-hidden rounded-[18px] border border-slate-200 bg-white">
              <div className="grid grid-cols-[64px_1fr_1fr_1fr] gap-2 border-b border-slate-100 px-4 py-2 text-xs font-semibold text-slate-500">
                <span>Key</span>
                <span>Frame</span>
                <span>Pose</span>
                <span>Warnings</span>
              </div>
              {keyframes.map((item) => (
                <div key={item.label} className="grid grid-cols-[64px_1fr_1fr_1fr] gap-2 border-b border-slate-100 px-4 py-2 text-xs text-slate-600 last:border-b-0">
                  <span className="font-semibold text-slate-900">{item.label}</span>
                  <span>{item.frameId ?? "-"} · {formatDuration(item.timestamp)} · {item.confidence == null ? "-" : item.confidence.toFixed(3)}</span>
                  <span>{item.poseState ?? "-"} {item.poseConfidence == null ? "" : `${Math.round(item.poseConfidence * 100)}%`}</span>
                  <span className="truncate">{item.warnings.join(", ") || "-"}</span>
                </div>
              ))}
            </div>
            <JsonBlock value={run.summary} />
          </div>
        ) : null}

        {effectiveActiveTab === "frames" ? (
          <div className="space-y-5">
            {debugPose ? (
              <IceMediaPlayer fallbackSrc={`/api/debug/runs/${encodeURIComponent(run.id)}/video`} pose={debugPose} mode="overlay" />
            ) : (
              <PoseFrameStage
                title="primary sampled frame"
                frame={sampledFrames[0]}
                poseFrame={poseFrameById.get(String(sampledFrames[0]?.frame_id ?? ""))}
                connections={poseConnections}
              />
            )}
            <FrameGrid title="Sampled frames" frames={sampledFrames} poseFrameById={poseFrameById} connections={poseConnections} />
            <FrameGrid title="Semantic frames" frames={semanticFrames} />
            <FrameGrid title="Partial semantic candidates" frames={partialSemanticFrames} />
          </div>
        ) : null}

        {effectiveActiveTab === "tracking" ? (
          <div className="space-y-4">
            {debugPose ? <IceMediaPlayer fallbackSrc={`/api/debug/runs/${encodeURIComponent(run.id)}/video`} pose={debugPose} mode="overlay" /> : null}
            <div className="grid gap-3 lg:grid-cols-3">
              <JsonBlock value={{ selection_strategy: motionScores.selection_strategy, top_motion_peaks: motionScores.top_motion_peaks }} />
              <JsonBlock value={{ coverage_gaps: motionScores.coverage_gaps, sampling_metadata: result.sampling_metadata }} />
              <JsonBlock value={{ current_tracker_diagnostics: trackerDiagnostics.slice(0, 16) }} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <JsonBlock value={trackerSummary} />
              <JsonBlock value={poseSummary} />
            </div>
            <JsonBlock value={{ target_lock: targetLock, pose_data: result.pose_data, bio_data: result.bio_data }} />
          </div>
        ) : null}

        {effectiveActiveTab === "video" ? (
          <div className="space-y-4">
            <InputWindowPanel value={inputWindow} />
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Provider</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">
                  {String(videoTemporal.provider ?? "-")} · {String(videoTemporal.model ?? "-")}
                </p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Confidence</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">{String(videoTemporal.confidence ?? "-")}</p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Effective source</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">{effectiveTimestampSource}</p>
                {resolverSource !== effectiveTimestampSource ? <p className="mt-1 text-xs text-slate-500">resolver: {resolverSource}</p> : null}
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Fallback</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">
                  {String(videoTemporal.fallback_reason ?? videoTemporal.fallback_recommendation ?? "-")}
                </p>
              </div>
              <div className="rounded-[18px] border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold text-slate-500">Partial candidates</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">{String(summary.partial_semantic_frame_count ?? partialSemanticFrames.length)}</p>
              </div>
            </div>
            {parseErrorDetail || rawResponseExcerpt ? (
              <div className="rounded-[18px] border border-amber-100 bg-amber-50 p-4 text-sm text-slate-700">
                {parseErrorDetail ? <p className="font-semibold text-slate-900">Parse: {parseErrorDetail}</p> : null}
                {rawResponseExcerpt ? (
                  <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-[14px] bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100">
                    {rawResponseExcerpt}
                  </pre>
                ) : null}
                {typeof videoTemporal.raw_response_length === "number" ? (
                  <p className="mt-2 text-xs text-slate-500">
                    raw length: {String(videoTemporal.raw_response_length)}
                    {videoTemporal.raw_response_truncated ? " (truncated)" : ""}
                  </p>
                ) : null}
              </div>
            ) : null}
            {retryRejectionFlags.length ? (
              <div className="rounded-[18px] border border-amber-100 bg-white p-4">
                <p className="text-xs font-semibold text-amber-700">Rejected retry diagnostics</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {retryRejectionFlags.map((flag) => (
                    <span key={flag} className="rounded-full bg-amber-50 px-3 py-1 text-xs text-amber-700">
                      {flag}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            <JsonBlock value={{ window_diagnostics: motionScores.window_diagnostics }} />
            <JsonBlock value={{ ai_clip: result.ai_clip, video_temporal: videoTemporal, resolved_keyframes: resolved, refinement_flags: result.refinement_flags }} />
          </div>
        ) : null}

        {effectiveActiveTab === "label" ? (
          <DebugGoldenLabelPanel
            run={run}
            sampledFrames={sampledFrames}
            semanticFrames={semanticFrames}
            partialSemanticFrames={partialSemanticFrames}
            poseFrameById={poseFrameById}
            connections={poseConnections}
            onSaved={() => void onRunRefresh(run.id)}
          />
        ) : null}

        {effectiveActiveTab === "raw" ? <JsonBlock value={run.result_json ?? run} /> : null}
      </div>
    </section>
  );
}

function FrameGrid({
  title,
  frames,
  poseFrameById,
  connections = [],
}: {
  title: string;
  frames: Record<string, unknown>[];
  poseFrameById?: Map<string, Record<string, unknown>>;
  connections?: number[][];
}) {
  if (!frames.length) {
    return (
      <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {title}: 暂无帧结果。
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-2 2xl:grid-cols-3">
        {frames.map((frame, index) => {
          const url = typeof frame.url === "string" ? frame.url : undefined;
          const frameId = String(frame.frame_id ?? frame.filename ?? index);
          const poseFrame = poseFrameById?.get(frameId);
          const targetStyle = bboxStyle(poseFrame?.target_bbox);
          return (
            <article key={`${frameId}-${index}`} className="overflow-hidden rounded-[20px] border border-slate-200 bg-white shadow-sm">
              <div className="relative aspect-video min-h-[190px] bg-slate-950">
                <DebugFrameImage url={url} alt={frameId} />
                {targetStyle ? <div className="pointer-events-none absolute border-2 border-cyan-300" style={targetStyle} /> : null}
                <PoseSkeletonOverlay frame={poseFrame} connections={connections} />
              </div>
              <div className="min-w-0 space-y-1 px-3 py-2 text-xs text-slate-500">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-mono text-slate-700">{frameId}</span>
                  <span>{formatDuration(frame.timestamp)}</span>
                </div>
                <p className="truncate">
                  {poseFrame
                    ? `pose ${String(poseFrame.tracking_state ?? "tracked")} ${asNumber(poseFrame.tracking_confidence) == null ? "" : `${Math.round((asNumber(poseFrame.tracking_confidence) ?? 0) * 100)}%`}`
                    : String(frame.phase_label ?? frame.phase_code ?? frame.selection_reason ?? "")}
                </p>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

export default function DebugPage({ workspace = "debug" }: { workspace?: DebugWorkspace }) {
  const location = useLocation();
  const { isParentMode, enterParentMode } = useAppMode();
  const isGoldenWorkspace = workspace === "golden";
  const requestedAnalysisId = useMemo(() => {
    const raw = new URLSearchParams(location.search).get("analysis_id");
    return raw?.trim() || null;
  }, [location.search]);
  const [analyses, setAnalyses] = useState<AnalysisListItem[]>([]);
  const [debugRuns, setDebugRuns] = useState<DebugRunSummary[]>([]);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState<string | null>(null);
  const [selectedAnalysisDetail, setSelectedAnalysisDetail] = useState<AnalysisDetail | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<DebugRunDetail | null>(null);
  const [activeTab, setActiveTab] = useState<DebugTab>(isGoldenWorkspace ? "label" : "frames");
  const [listState, setListState] = useState<LoadState>("idle");
  const [runState, setRunState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [autoGoldenState, setAutoGoldenState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);

  useEffect(() => {
    if (!isParentMode) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      setListState("loading");
      setError(null);
      try {
        const [analysisData, runData] = await Promise.all([fetchAnalyses(), fetchDebugRuns({ limit: 50 })]);
        if (cancelled) {
          return;
        }
        setAnalyses(analysisData);
        setDebugRuns(runData);
        setSelectedAnalysisId((current) => {
          if (requestedAnalysisId && analysisData.some((analysis) => analysis.id === requestedAnalysisId)) {
            return requestedAnalysisId;
          }
          return current ?? analysisData[0]?.id ?? null;
        });
        setSelectedRunId((current) => {
          const matchingRun = requestedAnalysisId ? runData.find((run) => run.analysis_id === requestedAnalysisId) : null;
          if (requestedAnalysisId) {
            return matchingRun?.id ?? null;
          }
          return current ?? runData[0]?.id ?? null;
        });
        setListState("ready");
      } catch {
        if (!cancelled) {
          setListState("error");
          setError("调试数据加载失败，请稍后刷新。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [isParentMode, requestedAnalysisId]);

  useEffect(() => {
    if (!isParentMode || !selectedAnalysisId) {
      setSelectedAnalysisDetail(null);
      return;
    }

    let cancelled = false;
    const load = async () => {
      setDetailState("loading");
      try {
        const data = await fetchAnalysis(selectedAnalysisId, { isParentRequest: true });
        if (!cancelled) {
          setSelectedAnalysisDetail(data);
          setDetailState("ready");
        }
      } catch {
        if (!cancelled) {
          setDetailState("error");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [isParentMode, selectedAnalysisId]);

  useEffect(() => {
    if (!isParentMode || !selectedRunId) {
      setSelectedRun(null);
      return;
    }

    let cancelled = false;
    const load = async () => {
      setRunState("loading");
      try {
        const data = await fetchDebugRun(selectedRunId);
        if (!cancelled) {
          setSelectedRun(data);
          setRunState("ready");
        }
      } catch {
        if (!cancelled) {
          setRunState("error");
          setError("Debug run 详情加载失败。");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [isParentMode, selectedRunId]);

  useEffect(() => {
    if (!isParentMode) {
      return;
    }

    let cancelled = false;
    const refresh = async () => {
      if (deletingRunId) {
        return;
      }
      try {
        const runs = await fetchDebugRuns({ limit: 50 });
        if (cancelled) {
          return;
        }
        setDebugRuns(runs);
        const requestedRunId = requestedAnalysisId ? runs.find((run) => run.analysis_id === requestedAnalysisId)?.id ?? null : null;
        const activeId =
          requestedAnalysisId
            ? requestedRunId
            : selectedRunId && runs.some((run) => run.id === selectedRunId)
              ? selectedRunId
              : runs[0]?.id ?? null;
        if (activeId !== selectedRunId) {
          setSelectedRunId(activeId);
        }
        if (activeId) {
          const detail = await fetchDebugRun(activeId);
          if (!cancelled) {
            setSelectedRun(detail);
            setRunState("ready");
          }
        } else if (!cancelled) {
          setSelectedRun(null);
          setRunState("idle");
        }
      } catch {
        if (!cancelled) {
          setError("Debug run 刷新失败，请稍后再试。");
        }
      }
    };
    const timer = window.setInterval(() => void refresh(), 3500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [isParentMode, selectedRunId, deletingRunId, requestedAnalysisId]);

  useEffect(() => {
    if (isGoldenWorkspace) {
      setActiveTab("label");
    }
  }, [isGoldenWorkspace]);

  useEffect(() => {
    if (!isParentMode || !isGoldenWorkspace || !requestedAnalysisId) {
      setAutoGoldenState("idle");
      return;
    }
    if (listState !== "ready") {
      return;
    }
    if (!analyses.some((analysis) => analysis.id === requestedAnalysisId)) {
      return;
    }
    const existingRun = debugRuns.find((run) => run.analysis_id === requestedAnalysisId && run.mode === "local_pose_keyframes");
    if (existingRun) {
      if (selectedRunId !== existingRun.id) {
        setSelectedRunId(existingRun.id);
      }
      setAutoGoldenState("ready");
      return;
    }

    let cancelled = false;
    const createRun = async () => {
      setAutoGoldenState("loading");
      setError(null);
      try {
        const response = await ensureGoldenAnalysisDebugRun(requestedAnalysisId);
        if (cancelled) {
          return;
        }
        setSelectedRunId(response.id);
        setActiveTab("label");
        const [runs, detail] = await Promise.all([fetchDebugRuns({ limit: 50 }), fetchDebugRun(response.id)]);
        if (!cancelled) {
          setDebugRuns(runs);
          setSelectedRun(detail);
          setRunState("ready");
          setAutoGoldenState("ready");
        }
      } catch {
        if (!cancelled) {
          setAutoGoldenState("error");
          setError("Golden 标注样本准备失败，请稍后重试。");
        }
      }
    };
    void createRun();
    return () => {
      cancelled = true;
    };
  }, [analyses, debugRuns, isGoldenWorkspace, isParentMode, listState, requestedAnalysisId, selectedRunId]);

  const selectedAnalysisItem = useMemo(
    () => analyses.find((item) => item.id === selectedAnalysisId) ?? null,
    [analyses, selectedAnalysisId],
  );

  const counts = useMemo(() => {
    return debugRuns.reduce<Record<string, number>>((acc, run) => {
      acc[run.status] = (acc[run.status] ?? 0) + 1;
      return acc;
    }, {});
  }, [debugRuns]);

  const goldenCounts = useMemo(() => {
    return debugRuns.reduce(
      (acc, run) => {
        const status = goldenStatusFromRun(run);
        if (status === "unlabeled") {
          acc.unlabeled += 1;
        } else {
          acc.labeled += 1;
        }
        const evalStatus = evalStatusFromRun(run);
        if (evalStatus === "passes") {
          acc.passes += 1;
        }
        if (evalStatus === "fails") {
          acc.fails += 1;
        }
        return acc;
      },
      { labeled: 0, unlabeled: 0, passes: 0, fails: 0 },
    );
  }, [debugRuns]);

  const handleCreated = async (id: string, mode?: DebugRunMode) => {
    setSelectedRunId(id);
    setActiveTab(isGoldenWorkspace ? "label" : mode === "video_ai_keyframes" ? "video" : "frames");
    const runs = await fetchDebugRuns({ limit: 50 });
    setDebugRuns(runs);
    const detail = await fetchDebugRun(id);
    setSelectedRun(detail);
  };

  const refreshRunDetail = async (id: string) => {
    setSelectedRunId(id);
    const [runs, detail] = await Promise.all([fetchDebugRuns({ limit: 50 }), fetchDebugRun(id)]);
    setDebugRuns(runs);
    setSelectedRun(detail);
    setRunState("ready");
  };

  const handleDeleteRun = async (run: DebugRunSummary) => {
    const confirmed = window.confirm(`Delete debug run ${modeLabel(run.mode)} from ${formatDate(run.created_at)}? This removes its debug frames and JSON result.`);
    if (!confirmed) {
      return;
    }
    setDeletingRunId(run.id);
    setError(null);
    try {
      await deleteDebugRun(run.id);
      if (selectedRunId === run.id) {
        setSelectedRun(null);
        setSelectedRunId(null);
        setRunState("idle");
      }
      setDebugRuns((current) => current.filter((item) => item.id !== run.id));
      const runs = await fetchDebugRuns({ limit: 50 });
      setDebugRuns(runs);
      if (selectedRunId === run.id || selectedRunId == null) {
        const nextId = runs[0]?.id ?? null;
        setSelectedRunId(nextId);
        if (nextId) {
          try {
            const detail = await fetchDebugRun(nextId);
            setSelectedRun(detail);
            setRunState("ready");
          } catch {
            setSelectedRun(null);
            setRunState("idle");
          }
        } else {
          setSelectedRun(null);
          setRunState("idle");
        }
      }
    } catch {
      setError("Debug run 删除失败，请稍后重试。");
    } finally {
      setDeletingRunId(null);
    }
  };

  if (!isParentMode) {
    return (
      <section className="app-card mx-auto max-w-3xl p-8 text-center tablet:p-10">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">{isGoldenWorkspace ? "Golden" : "Debug"}</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">{isGoldenWorkspace ? "Golden 标注工作台" : "调试工作台"}</h1>
        <p className="mt-4 text-base leading-8 text-slate-500">
          {isGoldenWorkspace ? "进入家长模式后，可以继续标注 golden 样本和查看标注历史。" : "进入家长模式后，可以运行测试入口、查看模型评测和每个视频的分析日志。"}
        </p>
        <button
          type="button"
          onClick={() => void enterParentMode()}
          className="mt-8 min-h-[48px] rounded-full bg-blue-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
        >
          进入家长模式
        </button>
      </section>
    );
  }

  if (isGoldenWorkspace) {
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Golden</p>
            <h1 className="mt-2 text-3xl font-semibold text-slate-900 tablet:text-4xl">Golden 标注工作台</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">从历史样本继续标注关键帧、主人物 bbox、场景分层和错误标签。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/debug" className="app-pill text-sm font-semibold">
              调试工作台
            </Link>
            <Link to="/settings/api" className="app-pill text-sm font-semibold">
              API 设置
            </Link>
          </div>
        </div>

        {error ? <div className="rounded-[20px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}
        {autoGoldenState === "loading" ? (
          <div className="rounded-[20px] border border-amber-100 bg-amber-50 px-5 py-4 text-sm font-semibold text-amber-700">
            正在准备这条分析的 Golden 标注样本，完成后会自动打开标注面板。
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-[20px] border border-slate-200 bg-white p-4">
            <p className="text-xs font-semibold text-slate-500">Golden Samples</p>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{debugRuns.length}</p>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white p-4">
            <p className="text-xs font-semibold text-slate-500">Labeled</p>
            <p className="mt-2 text-2xl font-semibold text-blue-600">{goldenCounts.labeled}</p>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white p-4">
            <p className="text-xs font-semibold text-slate-500">Unlabeled</p>
            <p className="mt-2 text-2xl font-semibold text-amber-600">{goldenCounts.unlabeled}</p>
          </div>
          <div className="rounded-[20px] border border-slate-200 bg-white p-4">
            <p className="text-xs font-semibold text-slate-500">Eval Fails</p>
            <p className="mt-2 text-2xl font-semibold text-rose-600">{goldenCounts.fails}</p>
          </div>
        </div>

        <div className="grid min-w-0 gap-5 web:grid-cols-[minmax(300px,440px)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-5 overflow-x-hidden">
            <section className="app-card min-w-0 self-start overflow-hidden p-5 tablet:p-6 web:sticky web:top-[112px]">
              <div className="mb-5">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">History</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-900">标注历史</h2>
              </div>
              {listState === "loading" ? <p className="text-sm text-slate-500">正在加载 debug runs...</p> : null}
              {!debugRuns.length && listState !== "loading" ? (
                <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                  暂时没有可标注样本。
                </div>
              ) : null}
              <div className="max-h-[44rem] min-w-0 space-y-3 overflow-y-auto overflow-x-hidden pr-1">
                {debugRuns.map((run) => (
                  <DebugRunCard
                    key={run.id}
                    run={run}
                    selected={run.id === selectedRunId}
                    onSelect={() => {
                      setSelectedRunId(run.id);
                      setActiveTab("label");
                    }}
                    onDelete={() => void handleDeleteRun(run)}
                    deleting={deletingRunId === run.id}
                  />
                ))}
              </div>
            </section>

            <section className="app-card min-w-0 self-start overflow-hidden p-5 tablet:p-6">
              <div className="mb-5">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">New Sample</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-900">新建标注样本</h2>
              </div>
              <div className="space-y-4">
                <DebugRunForm
                  mode="local_pose_keyframes"
                  analyses={analyses}
                  defaultAnalysisId={selectedAnalysisId}
                  selectedAnalysisDetail={selectedAnalysisDetail}
                  onAnalysisChange={setSelectedAnalysisId}
                  onCreated={(id) => void handleCreated(id, "local_pose_keyframes")}
                />
                <DebugRunForm
                  mode="video_ai_keyframes"
                  analyses={analyses}
                  defaultAnalysisId={selectedAnalysisId}
                  selectedAnalysisDetail={selectedAnalysisDetail}
                  onAnalysisChange={setSelectedAnalysisId}
                  onCreated={(id) => void handleCreated(id, "video_ai_keyframes")}
                />
              </div>
            </section>
          </div>

          <div className="min-w-0">
            {runState === "loading" ? <div className="mb-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">正在加载 debug run...</div> : null}
            {runState === "error" ? <div className="mb-3 rounded-[18px] border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">Debug run 加载失败。</div> : null}
            <DebugRunDetailPanel run={selectedRun} activeTab="label" onTabChange={setActiveTab} onRunRefresh={refreshRunDetail} focusMode="golden" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Debug</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-900 tablet:text-4xl">调试工作台</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">独立运行测试管线，结果写入 debug runs，不影响正式分析记录。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/golden" className="app-pill text-sm font-semibold">
            Golden 标注
          </Link>
          <Link to="/settings/api" className="app-pill text-sm font-semibold">
            API 设置
          </Link>
        </div>
      </div>

      {error ? <div className="rounded-[20px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-[20px] border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-500">Debug Runs</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">{debugRuns.length}</p>
        </div>
        <div className="rounded-[20px] border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-500">Processing</p>
          <p className="mt-2 text-2xl font-semibold text-blue-600">{(counts.pending ?? 0) + (counts.processing ?? 0)}</p>
        </div>
        <div className="rounded-[20px] border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-500">Completed</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-600">{counts.completed ?? 0}</p>
        </div>
        <div className="rounded-[20px] border border-slate-200 bg-white p-4">
          <p className="text-xs font-semibold text-slate-500">Failed</p>
          <p className="mt-2 text-2xl font-semibold text-rose-600">{counts.failed ?? 0}</p>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(360px,1fr)_minmax(320px,480px)]">
        <section className="app-card self-start p-5 tablet:p-6">
          <div className="mb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">New Debug Run</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">新建调试</h2>
          </div>
          <div className="space-y-4">
            <DebugRunForm
              mode="local_pose_keyframes"
              analyses={analyses}
              defaultAnalysisId={selectedAnalysisId}
              selectedAnalysisDetail={selectedAnalysisDetail}
              onAnalysisChange={setSelectedAnalysisId}
              onCreated={(id) => void handleCreated(id, "local_pose_keyframes")}
            />
            <DebugRunForm
              mode="video_ai_keyframes"
              analyses={analyses}
              defaultAnalysisId={selectedAnalysisId}
              selectedAnalysisDetail={selectedAnalysisDetail}
              onAnalysisChange={setSelectedAnalysisId}
              onCreated={(id) => void handleCreated(id, "video_ai_keyframes")}
            />
          </div>
        </section>

        <section className="app-card self-start p-5 tablet:p-6">
          <div className="mb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">Debug Runs</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">运行记录</h2>
          </div>
          {listState === "loading" ? <p className="text-sm text-slate-500">正在加载 debug runs...</p> : null}
          {!debugRuns.length && listState !== "loading" ? (
            <div className="rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              暂时没有 debug run。
            </div>
          ) : null}
          <div className="max-h-[42rem] space-y-3 overflow-y-auto pr-1">
            {debugRuns.map((run) => (
              <DebugRunCard
                key={run.id}
                run={run}
                selected={run.id === selectedRunId}
                onSelect={() => setSelectedRunId(run.id)}
                onDelete={() => void handleDeleteRun(run)}
                deleting={deletingRunId === run.id}
              />
            ))}
          </div>
        </section>
      </div>

      <div className="min-w-0">
          {runState === "loading" ? <div className="mb-3 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">正在加载 debug run...</div> : null}
          {runState === "error" ? <div className="mb-3 rounded-[18px] border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">Debug run 加载失败。</div> : null}
          <DebugRunDetailPanel run={selectedRun} activeTab={activeTab} onTabChange={setActiveTab} onRunRefresh={refreshRunDetail} />
      </div>

      <section className="space-y-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Monitoring</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">系统监控 / 正式分析日志</h2>
        </div>
        <ProviderMetricsPanel />
        <div className="grid gap-5 web:grid-cols-[minmax(280px,420px)_minmax(0,1fr)]">
          <AnalysisLogSelector analyses={analyses} selectedId={selectedAnalysisId} onSelect={setSelectedAnalysisId} listState={listState} />
          <div className="min-w-0">
            {detailState === "loading" ? <div className="rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">正在加载日志...</div> : null}
            {detailState === "error" ? <div className="rounded-[18px] border border-rose-100 bg-rose-50 px-4 py-6 text-sm text-rose-600">日志加载失败。</div> : null}
            {detailState !== "loading" && selectedAnalysisDetail ? (
              <div className="space-y-4">
                <div className="rounded-[20px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <p className="font-semibold text-slate-900">{selectedAnalysisItem ? buildTitle(selectedAnalysisItem) : selectedAnalysisDetail.id}</p>
                    <Link to={`/report/${selectedAnalysisDetail.id}/pose-debug`} className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-blue-600 transition hover:bg-blue-50">
                      Pose Debug
                    </Link>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {selectedAnalysisDetail.action_type}
                    {selectedAnalysisDetail.action_subtype ? ` · ${selectedAnalysisDetail.action_subtype}` : ""}
                    {selectedAnalysisDetail.analysis_profile ? ` · ${selectedAnalysisDetail.analysis_profile}` : ""}
                  </p>
                </div>
                <AnalysisDebugLogPanel
                  logs={selectedAnalysisDetail.processing_logs}
                  timings={selectedAnalysisDetail.processing_timings}
                  pipelineVersion={selectedAnalysisDetail.pipeline_version}
                  videoTemporalDiagnostics={selectedAnalysisDetail.video_temporal_diagnostics}
                  analysisId={selectedAnalysisDetail.id}
                  targetLock={selectedAnalysisDetail.target_lock}
                  poseData={selectedAnalysisDetail.pose_data}
                />
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
