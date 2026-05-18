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

export default function AnalysisDebugLogPanel({
  logs,
  timings,
  pipelineVersion,
  videoTemporalDiagnostics,
}: {
  logs: AnalysisLogEntry[];
  timings: Record<string, number> | null | undefined;
  pipelineVersion: string | null | undefined;
  videoTemporalDiagnostics?: VideoTemporalDiagnostics | null;
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
            {selectedSemanticFrames.length ? (
              <div className="mt-3 overflow-x-auto">
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
                      <tr key={`${frame.frame_id ?? "semantic"}-${index}`} className="border-t border-blue-100">
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
