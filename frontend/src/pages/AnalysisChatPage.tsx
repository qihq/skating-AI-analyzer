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
    }
  };

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
        className="mt-4 hidden w-full rounded-[20px] border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-teal-300 focus:ring-4 focus:ring-teal-100 tablet:block"
      />
      <select
        value={selectedId}
        onChange={(event) => handleSelectAnalysis(event.target.value)}
        className="mt-4 w-full rounded-[20px] border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 outline-none transition focus:border-teal-300 focus:ring-4 focus:ring-teal-100 tablet:hidden"
      >
        <option value="">{isListLoading ? "正在加载..." : "请选择一条已完成分析"}</option>
        {completedRecords.map((record) => (
          <option key={record.id} value={record.id}>
            {recordLabel(record)} · {formatDate(record.created_at)}
          </option>
        ))}
      </select>

      <div className="mt-4 hidden max-h-[32dvh] space-y-2 overflow-y-auto pr-1 tablet:block web:max-h-[calc(100dvh-260px)]">
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

  return (
    <div className="min-w-0 space-y-5">
      {notice ? <div className="rounded-[24px] border border-teal-100 bg-teal-50 px-5 py-4 text-sm text-teal-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      <section className="app-card overflow-hidden p-5 tablet:p-6">
        <div className="flex flex-col gap-4 tablet:flex-row tablet:items-end tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-600">AI Follow-up</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-900 tablet:text-3xl">AI 追问工作台</h1>
            <p className="mt-2 max-w-2xl text-sm leading-7 text-slate-500">手动选择任意已完成视频，继续追问、生成修正卡、确认应用并分享复盘内容。</p>
          </div>
          {selectedAnalysis ? (
            <Link to={`/report/${selectedAnalysis.id}`} className="min-h-[42px] rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50">
              打开报告
            </Link>
          ) : null}
        </div>
      </section>

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
      <div className="grid min-w-0 gap-5 web:grid-cols-[minmax(280px,340px)_minmax(0,1fr)]">
        <aside className="app-card min-w-0 p-4 tablet:p-5 web:sticky web:top-[112px] web:max-h-[calc(100dvh-140px)] web:overflow-hidden">
          {selectorContent}
        </aside>

        <main className="min-w-0 space-y-5">
          {isAnalysisLoading ? (
            <section className="app-card p-8 text-center text-sm text-slate-500">正在加载分析详情...</section>
          ) : null}
          {selectedAnalysis ? (
            <>
              <section className="app-card grid gap-4 p-5 tablet:grid-cols-[minmax(0,1fr)_auto] tablet:items-center">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.26em] text-slate-400">Selected Analysis</p>
                  <h2 className="mt-2 truncate text-xl font-semibold text-slate-900">{recordLabel(selectedAnalysis)}</h2>
                  <p className="mt-2 text-sm text-slate-500">{formatDate(selectedAnalysis.created_at)} · Force Score {selectedAnalysis.force_score ?? "--"}</p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                  {selectedAnalysis.report?.action_confirmation?.confirmed_action ? (
                    <span className="rounded-full bg-blue-50 px-3 py-1 font-semibold text-blue-600">{String(selectedAnalysis.report.action_confirmation.confirmed_action)}</span>
                  ) : null}
                  {selectedAnalysis.bio_data?.key_frames ? (
                    Object.entries(selectedAnalysis.bio_data.key_frames).map(([key, value]) => (
                      <span key={key} className="rounded-full bg-slate-100 px-3 py-1">{key}: {String(value)}</span>
                    ))
                  ) : null}
                </div>
              </section>
              <AnalysisFollowUpPanel
                analysis={selectedAnalysis}
                onAnalysisRefresh={() => void loadSelectedAnalysis(selectedAnalysis.id)}
                onNotice={showNotice}
              />
            </>
          ) : (
            <AnalysisFollowUpPanel analysis={null} />
          )}
        </main>
      </div>
      )}
    </div>
  );
}
