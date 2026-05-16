import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { AnalysisDetail, AnalysisListItem, fetchAnalyses, fetchAnalysis } from "../api/client";
import AnalysisDebugLogPanel from "../components/AnalysisDebugLogPanel";
import { useAppMode } from "../components/AppModeContext";
import ProviderMetricsPanel from "../components/ProviderMetricsPanel";
import { getAnalysisStatusLabel } from "../constants/analysisStatus";

type LoadState = "idle" | "loading" | "ready" | "error";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
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

function statusTone(status: AnalysisListItem["status"]) {
  if (status === "completed") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (status === "failed") {
    return "bg-rose-100 text-rose-600";
  }
  if (status === "awaiting_target_selection") {
    return "bg-amber-100 text-amber-700";
  }
  return "bg-blue-100 text-blue-700";
}

function buildTitle(item: AnalysisListItem) {
  const parts = [item.skater_name, item.action_type, item.action_subtype].filter(Boolean);
  return parts.join(" · ") || item.id;
}

export default function DebugPage() {
  const { isParentMode, enterParentMode } = useAppMode();
  const [analyses, setAnalyses] = useState<AnalysisListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<AnalysisDetail | null>(null);
  const [listState, setListState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isParentMode) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      setListState("loading");
      setError(null);
      try {
        const data = await fetchAnalyses();
        if (cancelled) {
          return;
        }
        setAnalyses(data);
        setSelectedId((current) => current ?? data[0]?.id ?? null);
        setListState("ready");
      } catch {
        if (!cancelled) {
          setListState("error");
          setError("分析记录加载失败，请稍后刷新。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [isParentMode]);

  useEffect(() => {
    if (!isParentMode || !selectedId) {
      setSelectedDetail(null);
      return;
    }

    let cancelled = false;
    const load = async () => {
      setDetailState("loading");
      setError(null);
      try {
        const data = await fetchAnalysis(selectedId, { isParentRequest: true });
        if (cancelled) {
          return;
        }
        setSelectedDetail(data);
        setDetailState("ready");
      } catch {
        if (!cancelled) {
          setDetailState("error");
          setError("该视频的分析日志加载失败。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [isParentMode, selectedId]);

  const selectedItem = useMemo(
    () => analyses.find((item) => item.id === selectedId) ?? null,
    [analyses, selectedId],
  );

  if (!isParentMode) {
    return (
      <section className="app-card mx-auto max-w-3xl p-8 text-center tablet:p-10">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Debug</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">调试日志</h1>
        <p className="mt-4 text-base leading-8 text-slate-500">进入家长模式后，才能查看模型评测和每个视频的分析日志。</p>
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Debug</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-900 tablet:text-4xl">调试日志</h1>
        </div>
        <Link to="/settings/api" className="app-pill text-sm font-semibold">
          API 设置
        </Link>
      </div>

      {error ? <div className="rounded-[24px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}

      <ProviderMetricsPanel />

      <div className="grid gap-5 web:grid-cols-[minmax(280px,420px)_minmax(0,1fr)]">
        <section className="app-card p-6 tablet:p-7">
          <div className="mb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Analysis Logs</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">视频分析日志</h2>
          </div>
          <div className="space-y-3">
            {listState === "loading" ? <p className="text-sm text-slate-500">正在加载分析记录...</p> : null}
            {listState === "error" ? <p className="text-sm text-rose-600">分析记录加载失败。</p> : null}
            {listState === "ready" && !analyses.length ? (
              <div className="rounded-[22px] border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                暂时还没有可查看的分析记录。
              </div>
            ) : null}

            <div className="max-h-[36rem] space-y-3 overflow-y-auto pr-1">
              {analyses.map((item) => {
                const selected = item.id === selectedId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedId(item.id)}
                    className={`w-full rounded-[22px] border px-4 py-4 text-left transition ${
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
                    {item.note ? <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500">{item.note}</p> : null}
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        <div className="min-w-0">
          {detailState === "loading" ? (
            <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">正在加载日志...</div>
          ) : null}
          {detailState === "error" ? (
            <div className="rounded-[22px] border border-rose-100 bg-rose-50 px-4 py-6 text-sm text-rose-600">日志加载失败。</div>
          ) : null}
          {detailState !== "loading" && selectedDetail ? (
            <div className="space-y-4">
              <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <p className="font-semibold text-slate-900">{selectedItem ? buildTitle(selectedItem) : selectedDetail.id}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {selectedDetail.action_type}
                  {selectedDetail.action_subtype ? ` · ${selectedDetail.action_subtype}` : ""}
                  {selectedDetail.analysis_profile ? ` · ${selectedDetail.analysis_profile}` : ""}
                </p>
              </div>
              <AnalysisDebugLogPanel
                logs={selectedDetail.processing_logs}
                timings={selectedDetail.processing_timings}
                pipelineVersion={selectedDetail.pipeline_version}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
