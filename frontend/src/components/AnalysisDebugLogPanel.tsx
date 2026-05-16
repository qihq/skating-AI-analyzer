import { AnalysisLogEntry } from "../api/client";
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

export default function AnalysisDebugLogPanel({
  logs,
  timings,
  pipelineVersion,
}: {
  logs: AnalysisLogEntry[];
  timings: Record<string, number> | null | undefined;
  pipelineVersion: string | null | undefined;
}) {
  const timingEntries = Object.entries(timings ?? {});

  return (
    <ReportCard title="分析日志" eyebrow="Debug Log">
      <div className="space-y-4">
        <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <p>Pipeline Version: {pipelineVersion ?? "v1.0.0"}</p>
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
