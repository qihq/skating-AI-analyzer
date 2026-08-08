import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { AnalysisDetail, AnalysisListItem, fetchAnalyses, fetchAnalysis } from "../api/client";
import { fetchAnalysisExperienceV2 } from "../analysis-v2/api";
import type { AnalysisExperienceV2 } from "../analysis-v2/contracts";
import { presentAnalysisExperience } from "../analysis-v2/presenter";
import { useAnalysisExperiences } from "../analysis-v2/useAnalysisExperiences";
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

function authorityRecordLabel(record: AnalysisListItem | null | undefined, experience: AnalysisExperienceV2 | null | undefined, selectedEventId?: string | null) {
  const skater = record?.skater_name ? `${record.skater_name} · ` : "";
  if (!experience) return `${skater}复盘摘要加载中`;
  const view = presentAnalysisExperience(experience, selectedEventId);
  const event = view.selectedEvent;
  return `${skater}${event?.label || "本次复盘"}`;
}

function authorityRecordScore(experience: AnalysisExperienceV2 | null | undefined): number | null {
  if (!experience) return null;
  return presentAnalysisExperience(experience).forceScore;
}

function authorityRecordSearchText(record: AnalysisListItem, experience: AnalysisExperienceV2 | null | undefined): string {
  if (!experience) return `${record.id} ${record.created_at}`;
  const view = presentAnalysisExperience(experience);
  const notes = experience.claims
    .filter((claim) => claim.claimType === "user_note" && claim.status === "confirmed" && claim.value != null)
    .map((claim) => String(claim.value));
  return [authorityRecordLabel(record, experience), view.summary, ...notes, record.id, record.created_at].join(" ");
}

function keyFrameChips(experience: AnalysisExperienceV2 | null) {
  const claims = experience?.claims.filter((claim) => claim.claimType === "key_moment" && claim.status !== "unobservable") ?? [];
  return claims.map((claim) => {
    const value = claim.value && typeof claim.value === "object" ? claim.value as Record<string, unknown> : {};
    return [String(value.phase ?? value.semantic_key ?? "moment"), value.frame ?? value.timestamp ?? claim.value] as [string, unknown];
  }).filter(([, value]) => value != null && value !== "");
}

export default function AnalysisChatPage({
  autoSelectFirst = true,
  showSelectorWhenEmpty = false,
}: {
  autoSelectFirst?: boolean;
  showSelectorWhenEmpty?: boolean;
}) {
  const { isParentMode, enterParentMode } = useAppMode();
  const [searchParams, setSearchParams] = useSearchParams();
  const [records, setRecords] = useState<AnalysisListItem[]>([]);
  const [selectedAnalysis, setSelectedAnalysis] = useState<AnalysisDetail | null>(null);
  const [selectedExperience, setSelectedExperience] = useState<AnalysisExperienceV2 | null>(null);
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isListLoading, setIsListLoading] = useState(true);
  const [isAnalysisLoading, setIsAnalysisLoading] = useState(false);
  const [isSelectorOpen, setIsSelectorOpen] = useState(false);

  const selectedId = searchParams.get("analysis") || "";
  const selectedEventId = searchParams.get("event");

  const completedRecords = useMemo(() => records.filter((record) => record.status === "completed"), [records]);
  const experienceIds = useMemo(() => completedRecords.map((record) => record.id), [completedRecords]);
  const { experiences } = useAnalysisExperiences(experienceIds);
  const filteredRecords = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) {
      return completedRecords;
    }
      return completedRecords.filter((record) =>
      [authorityRecordSearchText(record, experiences[record.id]), record.skill_category ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(keyword),
    );
  }, [completedRecords, experiences, query]);

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
        if (autoSelectFirst && !selectedId && firstCompleted) {
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
  }, [autoSelectFirst]);

  const loadSelectedAnalysis = async (id: string) => {
    if (!id) {
      setSelectedAnalysis(null);
      setSelectedExperience(null);
      return null;
    }
    setIsAnalysisLoading(true);
    setError(null);
    try {
      // The family-facing chat is anchored to the same authority contract as
      // report/history. Legacy detail is retained only for parent correction
      // tooling and is never used for the ordinary header or chat context.
      const experience = await fetchAnalysisExperienceV2(id);
      setSelectedExperience(experience);
      if (!selectedEventId && experience.events[0]?.eventId) {
        const next = new URLSearchParams(searchParams);
        next.set("event", experience.events[0].eventId);
        setSearchParams(next, { replace: true });
      }
      const data = await fetchAnalysis(id, { isParentRequest: true });
      setSelectedAnalysis(data);
      return data;
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "分析详情加载失败。"));
      } else {
        setError("分析详情加载失败。");
      }
      setSelectedAnalysis(null);
      setSelectedExperience(null);
      return null;
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

  const refreshSelectedAnalysis = async (id: string) => {
    const next = await loadSelectedAnalysis(id);
    if (!next) {
      return;
    }
    setRecords((current) =>
      current.map((record) =>
        record.id === id
          ? {
              ...record,
              updated_at: next.updated_at,
            }
          : record,
      ),
    );
  };

  const selectedKeyFrames = keyFrameChips(selectedExperience);
  const presented = selectedExperience ? presentAnalysisExperience(selectedExperience, selectedEventId) : null;

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
            {authorityRecordLabel(record, experiences[record.id])} · {formatDate(record.created_at)}
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
                    <p className="truncate text-sm font-semibold text-slate-900">{authorityRecordLabel(record, experiences[record.id])}</p>
                    <p className="mt-1 text-xs text-slate-500">{formatDate(record.created_at)}</p>
                  </div>
                  <span className="shrink-0 rounded-full bg-white px-2 py-1 text-xs font-semibold text-slate-500">{authorityRecordScore(experiences[record.id]) ?? "--"}</span>
                </div>
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
  const selectedSummary = selectedExperience
    ? authorityRecordLabel(selectedAnalysis ?? selectedRecord, selectedExperience, selectedEventId)
    : selectedRecord
      ? authorityRecordLabel(selectedRecord, experiences[selectedRecord.id])
      : "请选择一条分析";

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
                    <h1 className="mt-1 truncate text-lg font-semibold text-slate-900 tablet:text-xl">{authorityRecordLabel(selectedAnalysis, selectedExperience, selectedEventId)}</h1>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>{formatDate(selectedAnalysis.created_at)}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-1 font-semibold">{presented?.stateLabel ?? "当前证据状态未知"}</span>
                      {presented?.selectedEvent?.label ? <span className="rounded-full bg-blue-50 px-2 py-1 font-semibold text-blue-600">{presented.selectedEvent.label}</span> : null}
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
                experience={selectedExperience}
                selectedEventId={selectedEventId}
                variant="workspace"
                onAnalysisRefresh={() => refreshSelectedAnalysis(selectedAnalysis.id)}
                onAnalysisRetryQueued={() => void loadSelectedAnalysis(selectedAnalysis.id)}
                onNotice={showNotice}
              />
            </>
          ) : showSelectorWhenEmpty ? (
            <section className="app-card p-4 tablet:p-6">{selectorContent}</section>
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
