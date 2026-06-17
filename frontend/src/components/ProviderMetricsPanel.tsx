import { useEffect, useMemo, useState } from "react";

import {
  AutoEvalSnapshotSummary,
  fetchAutoEvalSnapshots,
  fetchProviderMetrics,
  ProviderMetricPublic,
} from "../api/client";
import ReportCard from "./ReportCard";
import { apiDateTimeFormatter, parseApiDate } from "../utils/datetime";

type LoadState = "idle" | "loading" | "ready" | "error";

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatRate(value: number) {
  return value.toFixed(2);
}

function formatSnapshotTime(value: string) {
  return apiDateTimeFormatter({
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(value));
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-[18px] border border-slate-200 bg-white px-4 py-3">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-sm font-semibold text-slate-900">{value}</span>
    </div>
  );
}

function SnapshotRow({ item }: { item: AutoEvalSnapshotSummary }) {
  const flags = item.auto_eval?.data_quality_flags?.slice(0, 3) ?? [];
  const conflictCount = item.auto_eval?.high_confidence_conflicts;
  return (
    <div className="rounded-[20px] border border-slate-200 bg-white px-4 py-4">
      <div className="flex flex-col gap-2 tablet:flex-row tablet:items-start tablet:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-900">{item.analysis_id}</p>
          <p className="mt-1 text-xs text-slate-500">
            {item.action_type}
            {item.analysis_profile ? ` · ${item.analysis_profile}` : ""}
            {item.pipeline_version ? ` · ${item.pipeline_version}` : ""}
          </p>
        </div>
        <p className="text-xs text-slate-400">{formatSnapshotTime(item.created_at)}</p>
      </div>

      <div className="mt-3 grid gap-2 tablet:grid-cols-3">
        <MetricRow
          label="Key frame"
          value={
            item.auto_eval?.key_frame_order_valid == null
              ? "未标注"
              : item.auto_eval.key_frame_order_valid
                ? "有效"
                : "无效"
          }
        />
        <MetricRow
          label="Phase sequence"
          value={
            item.auto_eval?.phase_sequence_valid == null
              ? "未标注"
              : item.auto_eval.phase_sequence_valid
                ? "有效"
                : "无效"
          }
        />
        <MetricRow
          label="High-conflict"
          value={typeof conflictCount === "number" ? String(conflictCount) : "未标注"}
        />
      </div>

      {flags.length ? <p className="mt-3 text-xs leading-6 text-slate-500">Flags: {flags.join(" · ")}</p> : null}
      {item.fusion_diagnostics.length ? (
        <p className="mt-2 text-xs leading-6 text-slate-500">Diagnostics: {item.fusion_diagnostics.slice(0, 4).join(" · ")}</p>
      ) : null}
      <p className="mt-3 text-xs text-slate-400">Candidates: {item.key_frame_candidates ? "available" : "none"}</p>
    </div>
  );
}

export default function ProviderMetricsPanel({
  analysisProfile,
  actionType,
}: {
  analysisProfile?: string | null;
  actionType?: string | null;
}) {
  const [metrics, setMetrics] = useState<ProviderMetricPublic[]>([]);
  const [snapshots, setSnapshots] = useState<AutoEvalSnapshotSummary[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setState("loading");
      setError(null);
      try {
        const [metricData, snapshotData] = await Promise.all([
          fetchProviderMetrics({ analysis_profile: analysisProfile }),
          fetchAutoEvalSnapshots({ analysis_profile: analysisProfile, action_type: actionType, limit: 12 }),
        ]);
        if (cancelled) {
          return;
        }
        setMetrics(metricData);
        setSnapshots(snapshotData);
        setState("ready");
      } catch {
        if (!cancelled) {
          setState("error");
          setError("自动评测数据加载失败。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [analysisProfile, actionType]);

  const hasContent = metrics.length > 0 || snapshots.length > 0;
  const sortedMetrics = useMemo(() => [...metrics].sort((a, b) => a.provider.localeCompare(b.provider)), [metrics]);

  return (
    <div id="replay-metrics" className="scroll-mt-28">
      <ReportCard title="自动评测与回放" eyebrow="Replay Metrics">
      {state === "loading" ? <p className="text-sm text-slate-500">加载自动评测摘要中...</p> : null}
      {state === "error" ? <div className="rounded-[18px] border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</div> : null}

      <div className="grid gap-6 tablet:grid-cols-2">
        <div>
          <p className="text-sm font-semibold text-slate-900">Provider 指标</p>
          <div className="mt-3 space-y-3">
            {sortedMetrics.length ? (
              sortedMetrics.map((item) => (
                <div key={item.provider} className="rounded-[20px] border border-slate-200 bg-slate-50 px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-semibold text-slate-900">{item.provider}</p>
                      <p className="mt-1 text-xs text-slate-500">{item.sample_count} samples</p>
                    </div>
                    <p className="text-xs text-slate-500">{item.recommendation ?? "暂无调权建议"}</p>
                  </div>
                  <div className="mt-3 grid gap-2">
                    <MetricRow label="JSON 合法率" value={formatPercent(item.json_valid_rate)} />
                    <MetricRow label="平均权重" value={formatRate(item.avg_effective_weight)} />
                    <MetricRow label="冲突率" value={formatPercent(item.conflict_rate)} />
                    <MetricRow label="失败率" value={formatPercent(item.failure_rate)} />
                  </div>
                </div>
              ))
            ) : state === "ready" ? (
              <div className="rounded-[18px] border border-dashed border-slate-300 px-4 py-4 text-sm text-slate-500">暂无 provider 指标。</div>
            ) : null}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-slate-900">自动评测快照</p>
            <span className="text-xs text-slate-400">{snapshots.length} 条</span>
          </div>
          <div className="mt-3 space-y-3">
            {snapshots.length ? (
              snapshots.map((item) => <SnapshotRow key={item.analysis_id} item={item} />)
            ) : state === "ready" ? (
              <div className="rounded-[18px] border border-dashed border-slate-300 px-4 py-4 text-sm text-slate-500">暂无自动评测快照。</div>
            ) : null}
          </div>
        </div>
      </div>

      {!hasContent && state === "ready" ? <p className="mt-4 text-sm text-slate-500">当前没有可展示的历史分析数据。</p> : null}
      </ReportCard>
    </div>
  );
}
