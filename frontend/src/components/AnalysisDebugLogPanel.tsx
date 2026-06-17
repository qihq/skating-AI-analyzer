import { useState } from "react";

import { AnalysisLogEntry, PoseResponse, SelectedSemanticFrame, VideoTemporalDiagnostics } from "../api/client";
import { apiDateTimeFormatter, parseApiDate } from "../utils/datetime";
import ReportCard from "./ReportCard";

type NormalizedBBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type TrackerDiagnosticFrame = {
  frame?: string | null;
  frame_index?: number | null;
  state?: string | null;
  bbox?: NormalizedBBox | null;
  tracker_id?: number | string | null;
  candidate_tracker_id?: number | string | null;
  lost_frames?: number | null;
  rejected_reasons?: string[];
};

type PoseDiagnosticFrame = {
  frame?: string | null;
  tracking_state?: string | null;
  tracking_confidence?: number | null;
  candidate_count?: number | null;
  rejected_candidate_count?: number | null;
  selected_source?: string | null;
  pose_reference_source?: string | null;
  reason?: string | null;
  rejected_reasons?: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asBBox(value: unknown): NormalizedBBox | null {
  if (!isRecord(value)) {
    return null;
  }
  const x = Number(value.x);
  const y = Number(value.y);
  const width = Number(value.width);
  const height = Number(value.height);
  if ([x, y, width, height].some((item) => Number.isNaN(item))) {
    return null;
  }
  return { x, y, width, height };
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function rejectedReasonsFromDiagnostics(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const reasons = new Set<string>();
  value.filter(isRecord).forEach((item) => {
    asStringArray(item.reasons).forEach((reason) => reasons.add(reason));
  });
  return Array.from(reasons);
}

function normalizeTrackerDiagnostics(targetLock?: Record<string, unknown> | null): TrackerDiagnosticFrame[] {
  const rawDiagnostics = Array.isArray(targetLock?.person_tracker_diagnostics) ? targetLock.person_tracker_diagnostics : [];
  return rawDiagnostics
    .filter(isRecord)
    .map((item) => ({
      frame: typeof item.frame === "string" ? item.frame : null,
      frame_index: typeof item.frame_index === "number" ? item.frame_index : null,
      state: typeof item.state === "string" ? item.state : null,
      bbox: asBBox(item.bbox),
      tracker_id: typeof item.tracker_id === "number" || typeof item.tracker_id === "string" ? item.tracker_id : null,
      candidate_tracker_id:
        typeof item.candidate_tracker_id === "number" || typeof item.candidate_tracker_id === "string" ? item.candidate_tracker_id : null,
      lost_frames: typeof item.lost_frames === "number" ? item.lost_frames : null,
      rejected_reasons: asStringArray(item.rejected_reasons),
    }));
}

function normalizeFallbackTrackerFrames(targetLock?: Record<string, unknown> | null): TrackerDiagnosticFrame[] {
  const rawBboxes = Array.isArray(targetLock?.bbox_per_frame) ? targetLock.bbox_per_frame : [];
  const frames: TrackerDiagnosticFrame[] = [];
  rawBboxes.forEach((item, index) => {
    const bbox = asBBox(item);
    if (!bbox) {
      return;
    }
    frames.push({
      frame: `frame_${String(index + 1).padStart(4, "0")}.jpg`,
      frame_index: index,
      state: "fallback_bbox",
      bbox,
    });
  });
  return frames;
}

export function normalizePoseDiagnosticFrames(poseData?: PoseResponse | null): PoseDiagnosticFrame[] {
  const rawDiagnostics = isRecord(poseData?.pose_diagnostics) && Array.isArray(poseData.pose_diagnostics.frames) ? poseData.pose_diagnostics.frames : [];
  if (rawDiagnostics.length) {
    return rawDiagnostics.filter(isRecord).map((item) => ({
      frame: typeof item.frame === "string" ? item.frame : null,
      tracking_state: typeof item.tracking_state === "string" ? item.tracking_state : null,
      tracking_confidence: typeof item.tracking_confidence === "number" ? item.tracking_confidence : null,
      candidate_count: typeof item.candidate_count === "number" ? item.candidate_count : null,
      rejected_candidate_count: typeof item.rejected_candidate_count === "number" ? item.rejected_candidate_count : null,
      selected_source: typeof item.selected_source === "string" ? item.selected_source : null,
      pose_reference_source: typeof item.pose_reference_source === "string" ? item.pose_reference_source : null,
      reason: typeof item.reason === "string" ? item.reason : null,
      rejected_reasons: rejectedReasonsFromDiagnostics(item.rejected_candidates),
    }));
  }
  return (poseData?.frames ?? []).map((frame) => ({
    frame: frame.frame,
    tracking_state: frame.tracking_state ?? null,
    tracking_confidence: frame.tracking_confidence ?? null,
    candidate_count: frame.pose_candidates?.length ?? null,
    rejected_candidate_count: null,
    selected_source: null,
    pose_reference_source: null,
    reason: null,
    rejected_reasons: [],
  }));
}

function countStates(frames: TrackerDiagnosticFrame[]) {
  return frames.reduce<Record<string, number>>((acc, frame) => {
    const state = frame.state ?? "unknown";
    acc[state] = (acc[state] ?? 0) + 1;
    return acc;
  }, {});
}

function formatPercent(value: number) {
  return `${Math.max(0, Math.min(100, value * 100)).toFixed(2)}%`;
}

function trackerStateClasses(state?: string | null) {
  if (state === "tracked") {
    return "border-emerald-400 bg-emerald-400/15 text-emerald-700";
  }
  if (state === "relocked") {
    return "border-violet-400 bg-violet-400/15 text-violet-700";
  }
  if (state === "relock_pending") {
    return "border-blue-400 bg-blue-400/15 text-blue-700";
  }
  if (state === "continuity_rejected" || state === "relock_rejected") {
    return "border-rose-400 bg-rose-400/15 text-rose-700";
  }
  if (state === "lost_reused") {
    return "border-amber-400 bg-amber-400/15 text-amber-700";
  }
  if (state === "interpolated") {
    return "border-slate-400 bg-slate-400/15 text-slate-600";
  }
  return "border-slate-400 bg-slate-400/15 text-slate-600";
}

function formatDuration(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return `${value.toFixed(2)}s`;
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

function formatConfidence(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "未提供";
  }
  return `${Math.round(value * 100)}%`;
}

function SemanticFrameImage({ analysisId, frameId, alt }: { analysisId: string; frameId: string; alt: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div className="flex h-full items-center justify-center px-3 text-center text-xs leading-5 text-slate-400">
        {"\u5173\u952e\u5e27\u56fe\u7247\u672a\u627e\u5230"}
      </div>
    );
  }

  return (
    <img
      src={`/api/frames/${analysisId}/${frameId}.jpg`}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-full w-full object-contain"
    />
  );
}

function DebugFrameImage({ analysisId, frameName, alt }: { analysisId: string; frameName: string; alt: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <div className="flex h-full items-center justify-center px-3 text-center text-xs text-slate-400">Frame unavailable</div>;
  }

  return (
    <img
      src={`/api/frames/${analysisId}/${frameName}`}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-full w-full object-contain"
    />
  );
}

function SemanticFrameGallery({
  frames,
  analysisId,
  title,
  emptyLabel,
  tone = "blue",
}: {
  frames: SelectedSemanticFrame[];
  analysisId?: string | null;
  title: string;
  emptyLabel: string;
  tone?: "blue" | "amber";
}) {
  const borderClass = tone === "amber" ? "border-amber-100" : "border-blue-100";
  const badgeClass = tone === "amber" ? "text-amber-700" : "text-blue-700";

  if (!frames.length) {
    if (!emptyLabel) {
      return null;
    }
    return <p className="mt-3 text-xs text-slate-500">{emptyLabel}</p>;
  }

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={`text-xs font-semibold ${badgeClass}`}>{title}</p>
        <span className="rounded-full bg-white px-2.5 py-1 text-xs text-slate-500">{frames.length}</span>
      </div>
      {analysisId ? (
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {frames.map((frame, index) => {
            const frameId = frame.frame_id ?? null;
            return (
              <article key={`${frameId ?? title}-${index}`} className={`overflow-hidden rounded-[18px] border ${borderClass} bg-white`}>
                <div className="aspect-video bg-slate-950">
                  {frameId ? (
                    <SemanticFrameImage analysisId={analysisId} frameId={frameId} alt={`${frame.phase_label ?? frame.phase_code ?? "key frame"} ${frameId}`} />
                  ) : (
                    <div className="flex h-full items-center justify-center px-3 text-center text-xs text-slate-400">No frame ID</div>
                  )}
                </div>
                <div className="min-w-0 space-y-1 px-3 py-2 text-xs text-slate-500">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-slate-700">{frameId ?? "-"}</span>
                    <span>{formatDuration(frame.timestamp) ?? "-"}</span>
                  </div>
                  <p className="font-semibold text-slate-700">{frame.phase_label ?? frame.phase_code ?? "-"}</p>
                  <p className="line-clamp-2">{frame.selection_reason ?? frame.selection_status ?? "-"}</p>
                  <p>
                    {frame.refinement_method ?? "-"}
                    {typeof frame.refinement_delta_sec === "number" ? ` (${frame.refinement_delta_sec.toFixed(3)}s)` : ""}
                  </p>
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
      <div className="max-w-full overflow-x-auto">
        <table className="min-w-[640px] text-left text-xs">
          <thead className="text-slate-400">
            <tr>
              <th className="py-1 pr-3 font-medium">Frame</th>
              <th className="py-1 pr-3 font-medium">Time</th>
              <th className="py-1 pr-3 font-medium">Phase</th>
              <th className="py-1 pr-3 font-medium">Reason</th>
              <th className="py-1 pr-3 font-medium">Refine</th>
            </tr>
          </thead>
          <tbody>
            {frames.map((frame, index) => (
              <tr key={`${frame.frame_id ?? title}-row-${index}`} className={`border-t ${borderClass}`}>
                <td className="py-1.5 pr-3 font-mono text-slate-700">{frame.frame_id ?? "-"}</td>
                <td className="py-1.5 pr-3">{formatDuration(frame.timestamp)}</td>
                <td className="py-1.5 pr-3">{frame.phase_label ?? frame.phase_code ?? "-"}</td>
                <td className="py-1.5 pr-3">{frame.selection_reason ?? frame.selection_status ?? "-"}</td>
                <td className="py-1.5 pr-3">
                  {frame.refinement_method ?? "-"}
                  {typeof frame.refinement_delta_sec === "number" ? ` (${frame.refinement_delta_sec.toFixed(3)}s)` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function TargetPoseDebugPanel({
  analysisId,
  targetLock,
  poseData,
}: {
  analysisId?: string | null;
  targetLock?: Record<string, unknown> | null;
  poseData?: PoseResponse | null;
}) {
  const trackerDiagnostics = normalizeTrackerDiagnostics(targetLock);
  const fallbackTrackerFrames = trackerDiagnostics.length ? [] : normalizeFallbackTrackerFrames(targetLock);
  const trackerFrames = trackerDiagnostics.length ? trackerDiagnostics : fallbackTrackerFrames;
  const trackerFlags = asStringArray(targetLock?.quality_flags);
  const trackerType = typeof targetLock?.tracker_type === "string" ? targetLock.tracker_type : trackerDiagnostics.length ? "yolo_bytetrack" : "legacy";
  const trackerStateCounts = countStates(trackerFrames);
  const poseDiagnostics = isRecord(poseData?.pose_diagnostics) ? poseData.pose_diagnostics : null;
  const poseFrames = normalizePoseDiagnosticFrames(poseData);
  const displayFrames = trackerFrames.slice(0, 18);
  const hasDebugData = Boolean(targetLock || poseData);

  if (!hasDebugData) {
    return null;
  }

  return (
    <div className="min-w-0 max-w-full overflow-hidden rounded-[22px] border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-slate-700">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-600">Target Tracking / Pose Debug</p>
          <p className="mt-1 font-semibold text-slate-900">{trackerType}</p>
        </div>
        <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-emerald-700">
          {trackerDiagnostics.length ? "diagnostics" : "fallback view"}
        </span>
      </div>

      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2 xl:grid-cols-4">
        <p>Tracker frames: {trackerFrames.length}</p>
        <p>Tracked: {(trackerStateCounts.tracked ?? 0) + (trackerStateCounts.relocked ?? 0)}</p>
        <p>Lost/reused: {trackerStateCounts.lost_reused ?? 0}</p>
        <p>Rejected: {(trackerStateCounts.continuity_rejected ?? 0) + (trackerStateCounts.relock_rejected ?? 0)}</p>
        <p>Pose frames: {poseDiagnostics ? String(poseDiagnostics.total_frames ?? poseFrames.length) : poseFrames.length}</p>
        <p>Pose tracked: {poseDiagnostics ? String(poseDiagnostics.tracked_frames ?? "-") : poseFrames.filter((frame) => frame.tracking_state === "tracked").length}</p>
        <p>Pose lost: {poseDiagnostics ? String(poseDiagnostics.lost_frames ?? "-") : poseFrames.filter((frame) => frame.tracking_state !== "tracked").length}</p>
        <p>Interpolated: {poseDiagnostics ? String(poseDiagnostics.interpolated_frames ?? "0") : poseFrames.filter((frame) => frame.tracking_state === "interpolated").length}</p>
        <p>Low confidence: {poseDiagnostics ? String(poseDiagnostics.low_confidence_frames ?? "-") : "-"}</p>
      </div>

      {trackerFlags.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {trackerFlags.map((flag) => (
            <span key={flag} className="rounded-full bg-white px-2.5 py-1 text-xs text-slate-500">
              {flag}
            </span>
          ))}
        </div>
      ) : null}

      {!trackerDiagnostics.length && fallbackTrackerFrames.length ? (
        <p className="mt-3 text-xs leading-5 text-slate-500">旧分析没有逐帧 diagnostics，下面使用已有 bbox_per_frame 和 pose_candidates 做降级展示。</p>
      ) : null}

      {analysisId && displayFrames.length ? (
        <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {displayFrames.map((frame, index) => {
            const frameName = frame.frame ?? `frame_${String((frame.frame_index ?? index) + 1).padStart(4, "0")}.jpg`;
            const bbox = frame.bbox;
            const stateClasses = trackerStateClasses(frame.state);
            return (
              <article key={`${frameName}-${index}`} className="overflow-hidden rounded-[18px] border border-emerald-100 bg-white">
                <div className="relative aspect-video bg-slate-950">
                  <DebugFrameImage analysisId={analysisId} frameName={frameName} alt={`tracking ${frameName}`} />
                  {bbox ? (
                    <div
                      className={`pointer-events-none absolute border-2 ${stateClasses}`}
                      style={{
                        left: formatPercent(bbox.x),
                        top: formatPercent(bbox.y),
                        width: formatPercent(bbox.width),
                        height: formatPercent(bbox.height),
                      }}
                    />
                  ) : null}
                </div>
                <div className="min-w-0 space-y-1 px-3 py-2 text-xs text-slate-500">
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-slate-700">{frameName}</span>
                    <span className={`rounded-full border px-2 py-0.5 ${stateClasses}`}>{frame.state ?? "unknown"}</span>
                  </div>
                  <p>
                    tracker {frame.tracker_id ?? "-"}
                    {frame.candidate_tracker_id != null ? ` · candidate ${frame.candidate_tracker_id}` : ""}
                    {frame.lost_frames != null ? ` · lost ${frame.lost_frames}` : ""}
                  </p>
                  {frame.rejected_reasons?.length ? <p className="line-clamp-2">reject: {frame.rejected_reasons.join(", ")}</p> : null}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}

      {poseFrames.length ? (
        <details className="mt-3 text-xs text-slate-500">
          <summary className="cursor-pointer">展开 pose 逐帧摘要</summary>
          <div className="mt-2 max-w-full overflow-x-auto">
            <table className="min-w-[640px] text-left">
              <thead className="text-slate-400">
                <tr>
                  <th className="py-1 pr-3 font-medium">Frame</th>
                  <th className="py-1 pr-3 font-medium">State</th>
                  <th className="py-1 pr-3 font-medium">Conf</th>
                  <th className="py-1 pr-3 font-medium">Candidates</th>
                  <th className="py-1 pr-3 font-medium">Source</th>
                  <th className="py-1 pr-3 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {poseFrames.slice(0, 80).map((frame, index) => (
                  <tr key={`${frame.frame ?? "pose"}-${index}`} className="border-t border-emerald-100">
                    <td className="py-1.5 pr-3 font-mono text-slate-700">{frame.frame ?? "-"}</td>
                    <td className="py-1.5 pr-3">{frame.tracking_state ?? "-"}</td>
                    <td className="py-1.5 pr-3">{typeof frame.tracking_confidence === "number" ? frame.tracking_confidence.toFixed(3) : "-"}</td>
                    <td className="py-1.5 pr-3">
                      {frame.candidate_count ?? "-"}
                      {frame.rejected_candidate_count != null ? ` / rejected ${frame.rejected_candidate_count}` : ""}
                    </td>
                    <td className="py-1.5 pr-3">{frame.selected_source ?? frame.pose_reference_source ?? "-"}</td>
                    <td className="max-w-56 py-1.5 pr-3">
                      <span className="line-clamp-2">
                        {frame.reason ?? (frame.rejected_reasons?.length ? frame.rejected_reasons.join(", ") : "-")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  );
}

export default function AnalysisDebugLogPanel({
  logs,
  timings,
  pipelineVersion,
  videoTemporalDiagnostics,
  analysisId,
  targetLock,
  poseData,
}: {
  logs: AnalysisLogEntry[];
  timings: Record<string, number> | null | undefined;
  pipelineVersion: string | null | undefined;
  videoTemporalDiagnostics?: VideoTemporalDiagnostics | null;
  analysisId?: string | null;
  targetLock?: Record<string, unknown> | null;
  poseData?: PoseResponse | null;
}) {
  const timingEntries = Object.entries(timings ?? {});
  const selectedSemanticFrames = videoTemporalDiagnostics?.selected_semantic_frames ?? [];
  const partialSemanticFrames = videoTemporalDiagnostics?.partial_semantic_frames ?? [];
  const qualityFlags = videoTemporalDiagnostics?.quality_flags ?? [];
  const retryRejectionFlags = videoTemporalDiagnostics?.retry_rejection_flags ?? [];

  return (
    <ReportCard title="分析日志" eyebrow="Debug Log">
      <div className="min-w-0 space-y-4">
        <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <p>Pipeline Version: {pipelineVersion ?? "v5.2.1"}</p>
          <p className="mt-2 text-xs text-slate-500">
            日志为后端最新持久化处理日志，当前最多保留最近 {logs.length >= 200 ? "200" : logs.length || "0"} 条。
          </p>
          {timingEntries.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {timingEntries.map(([key, value]) => (
                <span key={key} className="rounded-full bg-white px-3 py-1 text-xs text-slate-600">
                  {key}: {formatDuration(value)}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-500">当前还没有阶段耗时数据。</p>
          )}
        </div>

        {videoTemporalDiagnostics ? (
          <div className="min-w-0 max-w-full overflow-hidden rounded-[22px] border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-slate-700">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-500">Video Temporal</p>
                <p className="mt-1 font-semibold text-slate-900">
                  {videoTemporalDiagnostics.video_ai_model ?? "unknown model"}
                  {videoTemporalDiagnostics.video_ai_provider ? ` · ${videoTemporalDiagnostics.video_ai_provider}` : ""}
                </p>
              </div>
              <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-blue-600">
                {videoTemporalDiagnostics.used_semantic_frames ? "语义帧" : "旧抽帧"}
              </span>
            </div>
            <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
              <p>视频置信度：{formatConfidence(videoTemporalDiagnostics.video_ai_confidence)}</p>
              <p>仲裁置信度：{formatConfidence(videoTemporalDiagnostics.resolved_confidence)}</p>
              <p>时间戳来源：{videoTemporalDiagnostics.timestamp_source ?? "未提供"}</p>
              <p>Fallback：{videoTemporalDiagnostics.fallback_reason ?? "无"}</p>
            </div>
            {videoTemporalDiagnostics.resolver_source && videoTemporalDiagnostics.resolver_source !== videoTemporalDiagnostics.timestamp_source ? (
              <p className="mt-2 text-xs text-slate-500">Resolver source: {videoTemporalDiagnostics.resolver_source}</p>
            ) : null}
            {videoTemporalDiagnostics.parse_error_detail || videoTemporalDiagnostics.raw_response_excerpt ? (
              <div className="mt-3 rounded-[18px] border border-blue-100 bg-white px-3 py-2 text-xs text-slate-600">
                {videoTemporalDiagnostics.parse_error_detail ? (
                  <p className="font-semibold text-slate-800">Parse: {videoTemporalDiagnostics.parse_error_detail}</p>
                ) : null}
                {videoTemporalDiagnostics.raw_response_excerpt ? (
                  <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-[14px] bg-slate-950 p-3 font-mono text-[11px] leading-5 text-slate-100">
                    {videoTemporalDiagnostics.raw_response_excerpt}
                  </pre>
                ) : null}
                {typeof videoTemporalDiagnostics.raw_response_length === "number" ? (
                  <p className="mt-2 text-slate-400">
                    raw length: {videoTemporalDiagnostics.raw_response_length}
                    {videoTemporalDiagnostics.raw_response_truncated ? " (truncated)" : ""}
                  </p>
                ) : null}
              </div>
            ) : null}
            {videoTemporalDiagnostics.video_ai_video_url ? (
              <div className="mt-3 overflow-hidden rounded-[18px] border border-blue-100 bg-slate-950">
                <video
                  src={videoTemporalDiagnostics.video_ai_video_url}
                  controls
                  preload="metadata"
                  playsInline
                  className="aspect-video w-full object-contain"
                />
                <div className="flex flex-wrap items-center justify-between gap-2 bg-white px-3 py-2 text-xs text-slate-500">
                  <span>Video AI source</span>
                  <span>{videoTemporalDiagnostics.video_ai_ran ? "ran" : "not run"}</span>
                </div>
              </div>
            ) : null}
            <SemanticFrameGallery
              frames={selectedSemanticFrames}
              analysisId={analysisId}
              title="Used semantic frames"
              emptyLabel="No used semantic keyframes to display."
            />
            <SemanticFrameGallery
              frames={partialSemanticFrames}
              analysisId={analysisId}
              title="Partial semantic candidates"
              emptyLabel=""
              tone="amber"
            />
            {qualityFlags.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {qualityFlags.map((flag) => (
                  <span key={flag} className="rounded-full bg-white px-2.5 py-1 text-xs text-slate-500">
                    {flag}
                  </span>
                ))}
              </div>
            ) : null}
            {retryRejectionFlags.length ? (
              <div className="mt-3 rounded-[18px] border border-amber-100 bg-white px-3 py-2">
                <p className="text-xs font-semibold text-amber-700">Retry rejected</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {retryRejectionFlags.map((flag) => (
                    <span key={flag} className="rounded-full bg-amber-50 px-2.5 py-1 text-xs text-amber-700">
                      {flag}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        <TargetPoseDebugPanel analysisId={analysisId} targetLock={targetLock} poseData={poseData} />

        <div className="max-h-[26rem] space-y-3 overflow-y-auto pr-1">
          {logs.length ? (
            logs
              .slice()
              .reverse()
              .map((entry, index) => (
                <article key={`${entry.timestamp}-${index}`} className="rounded-[22px] border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-600">
                        {entry.stage}
                      </span>
                      <span className="text-xs text-slate-400">{entry.level}</span>
                    </div>
                    <span className="text-xs text-slate-400">{formatLogTimestamp(entry.timestamp)}</span>
                  </div>
                  <p className="mt-2 leading-7 text-slate-700">{entry.message}</p>
                  {entry.elapsed_s != null ? <p className="mt-2 text-xs text-slate-500">耗时：{formatDuration(entry.elapsed_s)}</p> : null}
                  {entry.error_code ? <p className="mt-2 text-xs text-rose-500">错误码：{entry.error_code}</p> : null}
                  {entry.detail ? (
                    <details className="mt-2 text-xs text-slate-500">
                      <summary className="cursor-pointer">展开详情</summary>
                      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words leading-6">{entry.detail}</pre>
                    </details>
                  ) : null}
                </article>
              ))
          ) : (
            <div className="rounded-[22px] border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              当前还没有可显示的分析日志。
            </div>
          )}
        </div>
      </div>
    </ReportCard>
  );
}
