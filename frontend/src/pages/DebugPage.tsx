import { ChangeEvent, FormEvent, PointerEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  AnalysisDetail,
  AnalysisListItem,
  DebugRunDetail,
  DebugRunMode,
  DebugRunSummary,
  TargetBBox,
  TargetCandidate,
  createLocalDebugRun,
  createVideoAiDebugRun,
  deleteDebugRun,
  confirmDebugTargetLock,
  fetchAnalyses,
  fetchAnalysis,
  fetchDebugRun,
  fetchDebugRuns,
} from "../api/client";
import AnalysisDebugLogPanel from "../components/AnalysisDebugLogPanel";
import { useAppMode } from "../components/AppModeContext";
import PoseViewer from "../components/PoseViewer";
import ProviderMetricsPanel from "../components/ProviderMetricsPanel";
import { getAnalysisStatusLabel } from "../constants/analysisStatus";
import { apiDateTimeFormatter, parseApiDate } from "../utils/datetime";

type LoadState = "idle" | "loading" | "ready" | "error";
type DebugSource = "analysis" | "upload";
type DebugTab = "overview" | "frames" | "tracking" | "video" | "raw";

const ACTION_TYPES = ["跳跃", "旋转", "步法", "自由滑"];
const PROFILE_OPTIONS = ["jump", "spin", "step", "spiral"];

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

function selectedAnalysisLabel(analysisId: string | null, analyses: AnalysisListItem[]) {
  const item = analyses.find((analysis) => analysis.id === analysisId);
  return item ? buildTitle(item) : "选择正式分析记录";
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[34rem] overflow-auto rounded-[18px] bg-slate-950 p-4 text-xs leading-6 text-slate-100">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function DebugFrameImage({ url, alt, className = "h-full w-full object-contain" }: { url?: string; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false);

  if (!url || failed) {
    return <div className="flex h-full items-center justify-center px-3 text-center text-xs text-slate-400">Frame unavailable</div>;
  }

  return <img src={url} alt={alt} loading="lazy" onError={() => setFailed(true)} className={className} />;
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
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(autoCandidateId);
  const [manualBBox, setManualBBox] = useState<TargetBBox | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftBBox, setDraftBBox] = useState<TargetBBox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const selectedCandidate = candidates.find((candidate) => candidate.id === selectedCandidateId) ?? null;
  const activeBBox = draftBBox ?? manualBBox ?? selectedCandidate?.bbox ?? null;

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
      setError("请先选择候选框，或直接在画面里拖拽框出主要人物。");
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
        {candidates.map((candidate) => {
          const selected = candidate.id === selectedCandidateId && !manualBBox;
          return (
            <button
              key={candidate.id}
              type="button"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => {
                setSelectedCandidateId(candidate.id);
                setManualBBox(null);
                setError(null);
              }}
              className={`absolute border-2 transition ${selected ? "border-blue-300 bg-blue-300/20" : "border-white/80 bg-slate-950/10"}`}
              style={{
                left: `${candidate.bbox.x * 100}%`,
                top: `${candidate.bbox.y * 100}%`,
                width: `${candidate.bbox.width * 100}%`,
                height: `${candidate.bbox.height * 100}%`,
              }}
              aria-label={`candidate ${candidate.id}`}
            />
          );
        })}
        {activeBBox ? (
          <div
            className="pointer-events-none absolute border-2 border-emerald-300 bg-emerald-300/15"
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
            onClick={() => {
              setSelectedCandidateId(candidate.id);
              setManualBBox(null);
              setError(null);
            }}
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
      className={`w-full rounded-[20px] border px-4 py-4 text-left transition ${
        selected ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-white hover:border-blue-100 hover:bg-slate-50"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{modeLabel(run.mode)}</p>
          <p className="mt-1 text-xs text-slate-500">
            {sourceLabel(run.source_type)} · {run.action_subtype || run.action_type}
          </p>
          {stageLabel && (run.status === "pending" || run.status === "processing") ? <p className="mt-2 text-xs font-semibold text-blue-600">{stageLabel}</p> : null}
          {run.note ? <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">{run.note}</p> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
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
      </div>
      {showProgress ? (
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      ) : null}
      {flags.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {flags.map((flag) => (
            <span key={flag} className="rounded-full bg-white px-2.5 py-1 text-xs text-slate-500">
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
  onCreated,
}: {
  mode: DebugRunMode;
  analyses: AnalysisListItem[];
  defaultAnalysisId: string | null;
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

  useEffect(() => {
    if (!analysisId && defaultAnalysisId) {
      setAnalysisId(defaultAnalysisId);
    }
  }, [analysisId, defaultAnalysisId]);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setState("loading");
    setError(null);
    try {
      const payload = {
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
          <label className="block">
            <span className="text-xs font-semibold text-slate-500">正式分析记录</span>
            <select value={analysisId} onChange={(event) => setAnalysisId(event.target.value)} className="app-select mt-2 rounded-[18px] text-sm">
              <option value="">{selectedAnalysisLabel(null, analyses)}</option>
              {analyses.map((analysis) => (
                <option key={analysis.id} value={analysis.id}>
                  {buildTitle(analysis)}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <>
            <label className="block">
              <span className="text-xs font-semibold text-slate-500">视频文件</span>
              <input type="file" accept="video/mp4,video/quicktime,video/x-msvideo,.mp4,.mov,.avi" onChange={handleFileChange} className="app-input mt-2 rounded-[18px] text-sm" />
            </label>
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
}: {
  run: DebugRunDetail | null;
  activeTab: DebugTab;
  onTabChange: (tab: DebugTab) => void;
  onRunRefresh: (id: string) => Promise<void>;
}) {
  if (!run) {
    return (
      <section className="app-card flex min-h-[32rem] items-center justify-center p-7 text-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Debug Result</p>
          <h2 className="mt-3 text-2xl font-semibold text-slate-900">选择或创建一个 debug run</h2>
          <p className="mt-3 max-w-md text-sm leading-6 text-slate-500">运行结果会保存在独立记录里，不会改写正式分析报告。</p>
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

  const tabs: Array<{ id: DebugTab; label: string }> = [
    { id: "overview", label: "Overview" },
    { id: "frames", label: "Frames" },
    { id: "tracking", label: "Tracking/Pose" },
    { id: "video", label: "Video AI" },
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

      <div className="mt-5 flex gap-2 overflow-x-auto rounded-[18px] bg-slate-100 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => onTabChange(tab.id)}
            className={`min-h-[38px] shrink-0 rounded-[14px] px-4 text-sm font-semibold transition ${
              activeTab === tab.id ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-900"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mt-5 min-w-0">
        {activeTab === "overview" ? (
          <div className="space-y-4">
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

        {activeTab === "frames" ? (
          <div className="space-y-5">
            {debugPose ? (
              <PoseViewer pose={debugPose} variant="debug" diagnosticsByFrame={trackerDiagnosticsByFrame} />
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

        {activeTab === "tracking" ? (
          <div className="space-y-4">
            {debugPose ? <PoseViewer pose={debugPose} variant="debug" diagnosticsByFrame={trackerDiagnosticsByFrame} /> : null}
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

        {activeTab === "video" ? (
          <div className="space-y-4">
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

        {activeTab === "raw" ? <JsonBlock value={run.result_json ?? run} /> : null}
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

export default function DebugPage() {
  const { isParentMode, enterParentMode } = useAppMode();
  const [analyses, setAnalyses] = useState<AnalysisListItem[]>([]);
  const [debugRuns, setDebugRuns] = useState<DebugRunSummary[]>([]);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState<string | null>(null);
  const [selectedAnalysisDetail, setSelectedAnalysisDetail] = useState<AnalysisDetail | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<DebugRunDetail | null>(null);
  const [activeTab, setActiveTab] = useState<DebugTab>("frames");
  const [listState, setListState] = useState<LoadState>("idle");
  const [runState, setRunState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
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
        setSelectedAnalysisId((current) => current ?? analysisData[0]?.id ?? null);
        setSelectedRunId((current) => current ?? runData[0]?.id ?? null);
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
  }, [isParentMode]);

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
        const activeId = selectedRunId && runs.some((run) => run.id === selectedRunId) ? selectedRunId : runs[0]?.id ?? null;
        if (activeId && activeId !== selectedRunId) {
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
  }, [isParentMode, selectedRunId, deletingRunId]);

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

  const handleCreated = async (id: string, mode?: DebugRunMode) => {
    setSelectedRunId(id);
    setActiveTab(mode === "video_ai_keyframes" ? "video" : "frames");
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
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Debug</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">调试工作台</h1>
        <p className="mt-4 text-base leading-8 text-slate-500">进入家长模式后，可以运行测试入口、查看模型评测和每个视频的分析日志。</p>
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

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Debug</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-900 tablet:text-4xl">调试工作台</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">独立运行测试管线，结果写入 debug runs，不影响正式分析记录。</p>
        </div>
        <Link to="/settings/api" className="app-pill text-sm font-semibold">
          API 设置
        </Link>
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
            <DebugRunForm mode="local_pose_keyframes" analyses={analyses} defaultAnalysisId={selectedAnalysisId} onCreated={(id) => void handleCreated(id, "local_pose_keyframes")} />
            <DebugRunForm mode="video_ai_keyframes" analyses={analyses} defaultAnalysisId={selectedAnalysisId} onCreated={(id) => void handleCreated(id, "video_ai_keyframes")} />
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
