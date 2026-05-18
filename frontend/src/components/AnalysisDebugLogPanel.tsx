import { useState } from "react";

import { AnalysisLogEntry, VideoTemporalDiagnostics } from "../api/client";
import ReportCard from "./ReportCard";

function formatDuration(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }
  return `${value.toFixed(2)}s`;
}

function formatLogTimestamp(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
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

export default function AnalysisDebugLogPanel({
  logs,
  timings,
  pipelineVersion,
  videoTemporalDiagnostics,
  analysisId,
}: {
  logs: AnalysisLogEntry[];
  timings: Record<string, number> | null | undefined;
  pipelineVersion: string | null | undefined;
  videoTemporalDiagnostics?: VideoTemporalDiagnostics | null;
  analysisId?: string | null;
}) {
  const timingEntries = Object.entries(timings ?? {});
  const selectedSemanticFrames = videoTemporalDiagnostics?.selected_semantic_frames ?? [];
  const qualityFlags = videoTemporalDiagnostics?.quality_flags ?? [];

  return (
    <ReportCard title="分析日志" eyebrow="Debug Log">
      <div className="space-y-4">
        <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <p>Pipeline Version: {pipelineVersion ?? "v1.0.0"}</p>
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
          <div className="rounded-[22px] border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-slate-700">
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
            ) : null}            {selectedSemanticFrames.length ? (
              <div className="mt-3 space-y-3">
                {analysisId ? (
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {selectedSemanticFrames.map((frame, index) => {
                      const frameId = frame.frame_id ?? null;
                      return (
                        <article key={`${frameId ?? "semantic"}-${index}`} className="overflow-hidden rounded-[18px] border border-blue-100 bg-white">
                          <div className="aspect-video bg-slate-950">
                            {frameId ? (
                              <SemanticFrameImage analysisId={analysisId} frameId={frameId} alt={`${frame.phase_label ?? frame.phase_code ?? "关键帧"} ${frameId}`} />
                            ) : (
                              <div className="flex h-full items-center justify-center px-3 text-center text-xs text-slate-400">无帧 ID</div>
                            )}
                          </div>
                          <div className="space-y-1 px-3 py-2 text-xs text-slate-500">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono text-slate-700">{frameId ?? "-"}</span>
                              <span>{formatDuration(frame.timestamp) ?? "-"}</span>
                            </div>
                            <p className="font-semibold text-slate-700">{frame.phase_label ?? frame.phase_code ?? "-"}</p>
                            <p className="line-clamp-2">{frame.selection_reason ?? "-"}</p>
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
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left text-xs">
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
                      {selectedSemanticFrames.map((frame, index) => (
                        <tr key={`${frame.frame_id ?? "semantic"}-row-${index}`} className="border-t border-blue-100">
                          <td className="py-1.5 pr-3 font-mono text-slate-700">{frame.frame_id ?? "-"}</td>
                          <td className="py-1.5 pr-3">{formatDuration(frame.timestamp)}</td>
                          <td className="py-1.5 pr-3">{frame.phase_label ?? frame.phase_code ?? "-"}</td>
                          <td className="py-1.5 pr-3">{frame.selection_reason ?? "-"}</td>
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
            ) : (
              <p className="mt-3 text-xs text-slate-500">没有可显示的语义关键帧。</p>
            )}
            {qualityFlags.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {qualityFlags.map((flag) => (
                  <span key={flag} className="rounded-full bg-white px-2.5 py-1 text-xs text-slate-500">
                    {flag}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

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
