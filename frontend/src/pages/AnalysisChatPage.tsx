import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { AnalysisDetail, AnalysisListItem, fetchAnalyses, fetchAnalysis } from "../api/client";
import AnalysisFollowUpPanel from "../components/AnalysisFollowUpPanel";
import { useAppMode } from "../components/AppModeContext";
import { apiDateTimeFormatter, parseApiDate } from "../utils/datetime";

function formatDate(value: string) {
  return apiDateTimeFormatter({
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(value));
}

function recordLabel(record: AnalysisListItem) {
  const skater = record.skater_name ? `${record.skater_name} · ` : "";
  const subtype = record.action_subtype ? ` · ${record.action_subtype}` : "";
  return `${skater}${record.action_type}${subtype}`;
}

function keyFrameChips(analysis: AnalysisDetail) {
  return analysis.bio_data?.key_frames ? Object.entries(analysis.bio_data.key_frames).filter(([, value]) => value) : [];
}

export default function AnalysisChatPage() {
  const { isParentMode, enterParentMode } = useAppMode();
  const [searchParams, setSearchParams] = useSearchParams();
  const [records, setRecords] = useState<AnalysisListItem[]>([]);
  const [selectedAnalysis, setSelectedAnalysis] = useState<AnalysisDetail | null>(null);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isListLoading, setIsListLoading] = useState(true);
  const [isAnalysisLoading, setIsAnalysisLoading] = useState(false);
  const [isSelectorOpen, setIsSelectorOpen] = useState(false);

  const selectedId = searchParams.get("analysis") || "";

  const completedRecords = useMemo(() => records.filter((record) => record.status === "completed"), [records]);
  const filteredRecords = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) {
      return completedRecords;
    }
    return completedRecords.filter((record) =>
      [
        recordLabel(record),
        record.id,
        record.note ?? "",
        record.skill_category ?? "",
        record.created_at,
      ]
        .join(" ")
        .toLowerCase()
        .includes(keyword),
    );
  }, [completedRecords, query]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setIsListLoading(true);
      setError(null);
      try {
        const data = await fetchAnalyses({ limit: 80 });
        if (cancelled) {
          return;
        }
        setRecords(data);
        const firstCompleted = data.find((record) => record.status === "completed");
        if (!selectedId && firstCompleted) {
          setSearchParams({ analysis: firstCompleted.id }, { replace: true });
        }
      } catch {
        if (!cancelled) {
          setError("分析列表加载失败，请稍后刷新。");
        }
      } finally {
        if (!cancelled) {
          setIsListLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadSelectedAnalysis = async (id: string) => {
    if (!id) {
      setSelectedAnalysis(null);
      return;
    }
    setIsAnalysisLoading(true);
    setError(null);
    try {
      const data = await fetchAnalysis(id, { isParentRequest: true });
      setSelectedAnalysis(data);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "分析详情加载失败。"));
      } else {
        setError("分析详情加载失败。");
      }
      setSelectedAnalysis(null);
    } finally {
      setIsAnalysisLoading(false);
    }
  };

  useEffect(() => {
    void loadSelectedAnalysis(selectedId);
  }, [selectedId]);

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const handleSelectAnalysis = (analysisId: string) => {
    if (analysisId) {
      setSearchParams({ analysis: analysisId });
      setIsSelectorOpen(false);
    }
  };

  const selectedKeyFrames = selectedAnalysis ? keyFrameChips(selectedAnalysis) : [];

  const selectorContent = (
    <>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-900">选择视频</h2>
        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-500">{completedRecords.length}</span>
      </div>
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="搜索动作、孩子、备注"
        className="mt-4 w-full rounded-[20px] border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-teal-300 focus:ring-4 focus:ring-teal-100"
      />
      <select
        value={selectedId}
        onChange={(event) => handleSelectAnalysis(event.target.value)}
        className="mt-3 w-full rounded-[20px] border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 outline-none transition focus:border-teal-300 focus:ring-4 focus:ring-teal-100 tablet:hidden"
      >
        <option value="">{isListLoading ? "正在加载..." : "请选择一条已完成分析"}</option>
        {completedRecords.map((record) => (
          <option key={record.id} value={record.id}>
            {recordLabel(record)} · {formatDate(record.created_at)}
          </option>
        ))}
      </select>

      <div className="mt-4 max-h-[min(58dvh,520px)] space-y-2 overflow-y-auto pr-1">
        {isListLoading ? (
          <p className="py-8 text-center text-sm text-slate-500">正在加载...</p>
        ) : filteredRecords.length ? (
          filteredRecords.map((record) => {
            const selected = record.id === selectedId;
            return (
              <button
                key={record.id}
                type="button"
                onClick={() => handleSelectAnalysis(record.id)}
                className={`w-full rounded-[22px] border px-4 py-3 text-left transition ${
                  selected ? "border-teal-200 bg-teal-50" : "border-slate-200 bg-white hover:bg-slate-50"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-900">{recordLabel(record)}</p>
                    <p className="mt-1 text-xs text-slate-500">{formatDate(record.created_at)}</p>
                  </div>
                  <span className="shrink-0 rounded-full bg-white px-2 py-1 text-xs font-semibold text-slate-500">{record.force_score ?? "--"}</span>
                </div>
                {record.note ? <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{record.note}</p> : null}
              </button>
            );
          })
        ) : (
          <p className="py-8 text-center text-sm leading-6 text-slate-500">没有匹配的已完成分析。</p>
        )}
      </div>
    </>
  );

  const selectedRecord = completedRecords.find((record) => record.id === selectedId);
  const selectedSummary = selectedAnalysis ? recordLabel(selectedAnalysis) : selectedRecord ? recordLabel(selectedRecord) : "请选择一条分析";

  return (
    <div className="min-w-0 space-y-4">
      {notice ? <div className="rounded-[24px] border border-teal-100 bg-teal-50 px-5 py-4 text-sm text-teal-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      {!isParentMode ? (
        <section className="app-card p-6 text-center tablet:p-8">
          <h2 className="text-xl font-semibold text-slate-900">需要家长模式</h2>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-7 text-slate-500">AI 追问工作台可以提出并应用动作/关键帧修正，所以只在家长或教练确认后开放。</p>
          <button
            type="button"
            onClick={() => void enterParentMode()}
            className="mt-5 min-h-[44px] rounded-full bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            进入家长模式
          </button>
        </section>
      ) : (
        <main className="min-w-0 space-y-4">
          {isAnalysisLoading ? (
            <section className="app-card p-8 text-center text-sm text-slate-500">正在加载分析详情...</section>
          ) : null}
          {selectedAnalysis ? (
            <>
              <section className="rounded-[24px] border border-slate-200 bg-white px-4 py-3 tablet:px-5">
                <div className="grid gap-3 tablet:grid-cols-[minmax(0,1fr)_auto] tablet:items-center">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-teal-600">AI 追问</p>
                    <h1 className="mt-1 truncate text-lg font-semibold text-slate-900 tablet:text-xl">{recordLabel(selectedAnalysis)}</h1>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>{formatDate(selectedAnalysis.created_at)}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-1 font-semibold">Force {selectedAnalysis.force_score ?? "--"}</span>
                      {selectedAnalysis.report?.action_confirmation?.confirmed_action ? (
                        <span className="rounded-full bg-blue-50 px-2 py-1 font-semibold text-blue-600">{String(selectedAnalysis.report.action_confirmation.confirmed_action)}</span>
                      ) : null}
                      {selectedKeyFrames.map(([key, value]) => (
                        <span key={key} className="rounded-full bg-slate-100 px-2 py-1">{key}: {String(value)}</span>
                      ))}
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 phone:flex-row tablet:justify-end">
                    <button
                      type="button"
                      onClick={() => setIsSelectorOpen(true)}
                      className="inline-flex min-h-[40px] items-center justify-center rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
                    >
                      切换视频
                    </button>
                    <Link to={`/report/${selectedAnalysis.id}`} className="inline-flex min-h-[40px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white">
                      打开报告
                    </Link>
                  </div>
                </div>
              </section>
              <AnalysisFollowUpPanel
                analysis={selectedAnalysis}
                variant="workspace"
                onAnalysisRefresh={() => void loadSelectedAnalysis(selectedAnalysis.id)}
                onAnalysisRetryQueued={() => void loadSelectedAnalysis(selectedAnalysis.id)}
                onNotice={showNotice}
              />
            </>
          ) : (
            <AnalysisFollowUpPanel analysis={null} variant="workspace" />
          )}
        </main>
      )}
      {isSelectorOpen ? (
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-slate-950/36 p-0 backdrop-blur-sm tablet:items-center tablet:p-6">
          <section className="max-h-[84dvh] w-full overflow-hidden rounded-t-[28px] border border-slate-200 bg-white p-4 shadow-[0_24px_80px_rgba(15,23,42,0.28)] tablet:max-w-2xl tablet:rounded-[28px] tablet:p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-teal-600">切换视频</p>
                <p className="mt-1 truncate text-sm font-semibold text-slate-900">{selectedSummary}</p>
              </div>
              <button
                type="button"
                onClick={() => setIsSelectorOpen(false)}
                className="min-h-[38px] rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-semibold text-slate-600 transition hover:bg-white"
              >
                关闭
              </button>
            </div>
            <div className="mt-4">
              {selectorContent}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
