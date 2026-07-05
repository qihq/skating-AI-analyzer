import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  AnalysisComparisonSummary,
  AnalysisListItem,
  createAnalysisComparison,
  deleteAnalysis,
  fetchAnalyses,
  fetchAnalysisComparisons,
  fetchSkaters,
  retryAnalysis,
  Skater,
} from "../api/client";
import DeleteAnalysisModal from "../components/DeleteAnalysisModal";
import { useAppMode } from "../components/AppModeContext";
import ParentPinVerifyModal from "../components/ParentPinVerifyModal";
import RetryAnalysisConfirmSheet from "../components/RetryAnalysisConfirmSheet";
import ZodiacAvatar from "../components/ZodiacAvatar";
import { isAnalysisInProgress } from "../constants/analysisStatus";
import { childViewAvatarType, childViewLabel, findSkaterForChildView, pickSkaterIdForChildView } from "../utils/childView";
import { parseApiDate } from "../utils/datetime";

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;
const HISTORY_PAGE_SIZE = 24;
type HistoryTab = "records" | "comparisons";

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(dateString));
}

function scoreColor(score: number | null) {
  if (score === null) {
    return "bg-slate-100 text-slate-500";
  }
  if (score < 60) {
    return "bg-rose-50 text-rose-500";
  }
  if (score <= 80) {
    return "bg-amber-50 text-amber-600";
  }
  return "bg-emerald-50 text-emerald-600";
}

function statusLabel(status: AnalysisListItem["status"]) {
  if (status === "completed") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "processing") {
    return "分析中";
  }
  return "待处理";
}

function statusTone(status: AnalysisListItem["status"]) {
  if (status === "completed") {
    return "bg-emerald-50 text-emerald-600";
  }
  if (status === "failed") {
    return "bg-rose-50 text-rose-500";
  }
  return "bg-blue-50 text-blue-500";
}

function comparisonStatusLabel(status: AnalysisComparisonSummary["status"]) {
  if (status === "completed") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "processing") {
    return "生成中";
  }
  return "排队中";
}

function comparisonStatusTone(status: AnalysisComparisonSummary["status"]) {
  if (status === "completed") {
    return "bg-emerald-50 text-emerald-600";
  }
  if (status === "failed") {
    return "bg-rose-50 text-rose-500";
  }
  return "bg-blue-50 text-blue-600";
}

const actionIconClassName =
  "list-row-action inline-flex shrink-0 rounded-full border text-[20px] leading-none transition disabled:cursor-not-allowed disabled:opacity-50";

export default function HistoryPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isParentMode, pinLength, childView } = useAppMode();
  const [activeTab, setActiveTab] = useState<HistoryTab>("records");
  const [activeFilter, setActiveFilter] = useState<(typeof FILTER_OPTIONS)[number]>("全部");
  const [records, setRecords] = useState<AnalysisListItem[]>([]);
  const [comparisons, setComparisons] = useState<AnalysisComparisonSummary[]>([]);
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [deleteStep, setDeleteStep] = useState<"confirm" | "pin">("confirm");
  const [deletePin, setDeletePin] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [retryingRecordId, setRetryingRecordId] = useState<string | null>(null);
  const [missingVideoRetryIds, setMissingVideoRetryIds] = useState<string[]>([]);
  const [confirmRetryRecordId, setConfirmRetryRecordId] = useState<string | null>(null);
  const [pinRetryRecordId, setPinRetryRecordId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMoreRecords, setHasMoreRecords] = useState(false);
  const [isLoadingComparisons, setIsLoadingComparisons] = useState(false);
  const [isCreatingComparison, setIsCreatingComparison] = useState(false);
  const [isSkaterContextReady, setIsSkaterContextReady] = useState(false);
  const focusedSkaterId = (location.state as { skaterId?: string } | null)?.skaterId ?? "";

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (!cancelled) {
          setSkaters(data);
        }
      } catch {
        if (!cancelled) {
          setError((current) => current ?? "练习档案加载失败，请稍后刷新。");
        }
      } finally {
        if (!cancelled) {
          setIsSkaterContextReady(true);
        }
      }
    };

    void loadSkaters();
    return () => {
      cancelled = true;
    };
  }, []);

  const currentSkaterId = useMemo(() => {
    if (focusedSkaterId) {
      return focusedSkaterId;
    }
    if (!isParentMode) {
      return pickSkaterIdForChildView(skaters, childView);
    }
    return "";
  }, [childView, focusedSkaterId, isParentMode, skaters]);

  const currentSkater = useMemo(() => {
    if (currentSkaterId) {
      return skaters.find((skater) => skater.id === currentSkaterId) ?? null;
    }
    if (!isParentMode) {
      return findSkaterForChildView(skaters, childView);
    }
    return null;
  }, [childView, currentSkaterId, isParentMode, skaters]);

  const emptyStateName = currentSkater?.display_name || currentSkater?.name || childViewLabel(childView);
  const emptyStateSkaterId = currentSkaterId || focusedSkaterId || "";

  const analysisQueryParams = useMemo(
    () => ({
      ...(activeFilter === "全部" ? {} : { action_type: activeFilter }),
      ...(currentSkaterId ? { skater_id: currentSkaterId } : {}),
    }),
    [activeFilter, currentSkaterId],
  );

  useEffect(() => {
    if (!isParentMode && !currentSkaterId && !isSkaterContextReady) {
      return;
    }

    let cancelled = false;

    const load = async () => {
      setIsLoading(true);
      try {
        const data = await fetchAnalyses({
          ...analysisQueryParams,
          limit: HISTORY_PAGE_SIZE + 1,
          offset: 0,
        });
        if (!cancelled) {
          const visibleRecords = data.slice(0, HISTORY_PAGE_SIZE);
          setRecords(visibleRecords);
          setHasMoreRecords(data.length > HISTORY_PAGE_SIZE);
          setError((current) => (current === "练习档案加载失败，请稍后刷新。" ? current : null));
          setSelectedIds((current) => current.filter((id) => visibleRecords.some((record) => record.id === id)));
        }
      } catch {
        if (!cancelled) {
          setError("历史记录加载失败，请稍后刷新。");
          setHasMoreRecords(false);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [analysisQueryParams, currentSkaterId, isParentMode, isSkaterContextReady]);

  useEffect(() => {
    if (!isParentMode && !currentSkaterId && !isSkaterContextReady) {
      return;
    }

    let cancelled = false;
    const loadComparisons = async () => {
      setIsLoadingComparisons(true);
      try {
        const data = await fetchAnalysisComparisons({
          ...(activeFilter === "全部" ? {} : { action_type: activeFilter }),
          ...(currentSkaterId ? { skater_id: currentSkaterId } : {}),
          limit: HISTORY_PAGE_SIZE,
          offset: 0,
        });
        if (!cancelled) {
          setComparisons(data);
          setError((current) => (current === "对比结果加载失败，请稍后刷新。" ? null : current));
        }
      } catch {
        if (!cancelled) {
          setError("对比结果加载失败，请稍后刷新。");
        }
      } finally {
        if (!cancelled) {
          setIsLoadingComparisons(false);
        }
      }
    };

    void loadComparisons();
    return () => {
      cancelled = true;
    };
  }, [activeFilter, currentSkaterId, isParentMode, isSkaterContextReady]);

  const selectedRecords = useMemo(
    () => records.filter((record) => selectedIds.includes(record.id)),
    [records, selectedIds],
  );

  const confirmRetryRecord = records.find((record) => record.id === confirmRetryRecordId) ?? null;
  const pinRetryRecord = records.find((record) => record.id === pinRetryRecordId) ?? null;

  const toggleSelect = (record: AnalysisListItem) => {
    setError(null);
    setSelectedIds((current) => {
      if (current.includes(record.id)) {
        return current.filter((id) => id !== record.id);
      }

      if (record.status !== "completed") {
        setError("只有已完成的记录才能加入对比。");
        return current;
      }

      const existing = records.filter((item) => current.includes(item.id));
      if (existing.length > 0 && existing[0].action_type !== record.action_type) {
        setError("对比记录必须属于同一种动作类型。");
        return current;
      }

      if (current.length >= 2) {
        return [current[1], record.id];
      }
      return [...current, record.id];
    });
  };

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const markRecordAsProcessing = (recordId: string) => {
    setRecords((current) =>
      current.map((item) =>
        item.id === recordId
          ? {
              ...item,
              status: "processing",
              updated_at: new Date().toISOString(),
            }
          : item,
      ),
    );
  };

  const closeDeleteModal = () => {
    setDeletingRecordId(null);
    setDeleteStep("confirm");
    setDeletePin("");
    setDeleteError(null);
    setIsDeleting(false);
  };

  const openDeleteModal = (recordId: string) => {
    setDeletingRecordId(recordId);
    setDeleteStep("confirm");
    setDeletePin("");
    setDeleteError(null);
  };

  const handleDeleteRecord = async () => {
    if (!deletingRecordId) {
      return;
    }

    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteAnalysis(deletingRecordId, deletePin);
      setRecords((current) => current.filter((record) => record.id !== deletingRecordId));
      setSelectedIds((current) => current.filter((id) => id !== deletingRecordId));
      closeDeleteModal();
      showNotice("已删除这条分析记录");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setDeleteError(String(requestError.response?.data?.detail ?? "删除失败，请稍后重试。"));
      } else {
        setDeleteError("删除失败，请稍后重试。");
      }
      setIsDeleting(false);
    }
  };

  const handleRetryRecord = async (record: AnalysisListItem) => {
    setRetryingRecordId(record.id);
    setError(null);
    try {
      await retryAnalysis(record.id, { resetTargetLock: true });
      markRecordAsProcessing(record.id);
      setMissingVideoRetryIds((current) => current.filter((id) => id !== record.id));
      showNotice("已重新提交，请稍候");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        if (requestError.response?.status === 404) {
          setMissingVideoRetryIds((current) => (current.includes(record.id) ? current : [...current, record.id]));
          showNotice('原始视频已清理，请点击"重新上传"');
          return;
        }
        setError(String(requestError.response?.data?.detail ?? "重新分析失败，请稍后重试。"));
      } else {
        setError("重新分析失败，请稍后重试。");
      }
    } finally {
      setRetryingRecordId(null);
    }
  };

  const requestReanalysis = (record: AnalysisListItem) => {
    if (record.status !== "completed" || retryingRecordId === record.id) {
      return;
    }

    if (isParentMode) {
      setConfirmRetryRecordId(record.id);
      return;
    }

    setPinRetryRecordId(record.id);
  };

  const handleVerifiedRetry = () => {
    if (!pinRetryRecord) {
      return;
    }
    setPinRetryRecordId(null);
    setConfirmRetryRecordId(pinRetryRecord.id);
  };

  const handleUploadFirstVideo = () => {
    navigate("/review", {
      state: emptyStateSkaterId ? { skaterId: emptyStateSkaterId } : undefined,
    });
  };

  const handleLoadMore = async () => {
    if (isLoading || isLoadingMore || !hasMoreRecords) {
      return;
    }

    setIsLoadingMore(true);
    setError(null);
    try {
      const data = await fetchAnalyses({
        ...analysisQueryParams,
        limit: HISTORY_PAGE_SIZE + 1,
        offset: records.length,
      });
      const nextRecords = data.slice(0, HISTORY_PAGE_SIZE);
      setRecords((current) => {
        const existingIds = new Set(current.map((record) => record.id));
        return [...current, ...nextRecords.filter((record) => !existingIds.has(record.id))];
      });
      setHasMoreRecords(data.length > HISTORY_PAGE_SIZE);
    } catch {
      setError("更多历史记录加载失败，请稍后重试。");
    } finally {
      setIsLoadingMore(false);
    }
  };

  const handleStartComparison = async () => {
    if (selectedRecords.length !== 2 || isCreatingComparison) {
      return;
    }
    setIsCreatingComparison(true);
    setError(null);
    try {
      const comparison = await createAnalysisComparison(selectedRecords[0].id, selectedRecords[1].id);
      setSelectedIds([]);
      navigate(`/compare/results/${comparison.id}`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "对比任务创建失败，请稍后重试。"));
      } else {
        setError("对比任务创建失败，请稍后重试。");
      }
    } finally {
      setIsCreatingComparison(false);
    }
  };

  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-8">
        <div className="flex flex-col gap-5 tablet:flex-row tablet:items-end tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">History</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">训练历史与复盘对比</h1>
            <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">
              按动作类型查看历史复盘记录，选择两条同动作类型的 completed 记录做进步对比。
            </p>
          </div>

          <div className="flex flex-wrap gap-3">
            <Link to="/progress" className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
              查看进步趋势
            </Link>
          </div>
        </div>
      </section>

      <section className="app-card p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">动作筛选</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setActiveFilter(option)}
              className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
                activeFilter === option ? "bg-blue-500 text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </section>

      <section className="app-card p-2">
        <div className="flex rounded-[24px] bg-slate-100 p-1">
          {[
            { id: "records" as const, label: "分析记录" },
            { id: "comparisons" as const, label: "对比结果" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`min-h-[44px] flex-1 rounded-[20px] px-4 text-sm font-semibold transition ${
                activeTab === tab.id ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-7">
        <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Records</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">{activeTab === "records" ? "历史记录" : "对比结果"}</h2>
          </div>
          <span className="w-fit rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">
            已加载 {activeTab === "records" ? records.length : comparisons.length} 条
          </span>
        </div>

        {activeTab === "comparisons" ? (
          isLoadingComparisons ? (
            <div className="mt-6 rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">正在加载对比结果…</div>
          ) : comparisons.length ? (
            <div className="mt-6 space-y-4">
              {comparisons.map((comparison) => (
                <article
                  key={comparison.id}
                  className="list-row min-w-0 max-w-full rounded-[24px] border border-slate-200 bg-white p-3 transition hover:bg-slate-50 phone:rounded-[28px] phone:p-5"
                >
                  <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
                    <div className="min-w-0 space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="max-w-full break-words rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{comparison.action_type}</span>
                        <span className={`max-w-full break-words rounded-full px-3 py-1 text-sm ${comparisonStatusTone(comparison.status)}`}>
                          {comparisonStatusLabel(comparison.status)}
                        </span>
                        {comparison.score_delta != null ? (
                          <span className={`max-w-full break-words rounded-full px-3 py-1 text-sm ${comparison.score_delta >= 0 ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-500"}`}>
                            评分 {comparison.score_delta >= 0 ? "+" : ""}
                            {comparison.score_delta}
                          </span>
                        ) : null}
                        {comparison.video_ai_status ? (
                          <span className="max-w-full break-words rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-600">Video AI {comparison.video_ai_status}</span>
                        ) : null}
                      </div>

                      <div className="text-sm text-slate-400">
                        <span>{formatDate(comparison.created_at)}</span>
                        {comparison.skater_name ? <span className="ml-3">练习档案：{comparison.skater_name}</span> : null}
                      </div>

                      <p className="max-w-3xl whitespace-normal break-words leading-7 text-slate-600">
                        {comparison.ai_narrative || comparison.error_message || "对比任务已保存，结果生成后会显示完整复盘。"}
                      </p>
                    </div>

                    <div className="flex flex-wrap gap-3 tablet:justify-end">
                      <Link
                        to={`/compare/results/${comparison.id}`}
                        className="rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
                      >
                        {comparison.status === "completed" ? "查看对比" : comparison.status === "failed" ? "查看/重试" : "查看进度"}
                      </Link>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="mt-6 rounded-[28px] bg-slate-50 px-5 py-6 text-sm leading-7 text-slate-500">
              当前筛选下还没有对比结果。回到分析记录，选择两条 completed 记录即可创建后台对比。
            </div>
          )
        ) : isLoading ? (
          <div className="mt-6 rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">正在加载历史记录…</div>
        ) : records.length ? (
          <div className="mt-6 space-y-4">
            {records.map((record) => {
              const isSelected = selectedIds.includes(record.id);
              const isRetrying = retryingRecordId === record.id;
              const hideRetry = missingVideoRetryIds.includes(record.id);

              return (
                <article
                  key={record.id}
                  className={`list-row min-w-0 max-w-full rounded-[24px] border p-3 phone:rounded-[28px] phone:p-5 transition ${isSelected ? "border-blue-300 bg-blue-50/40" : "border-slate-200 bg-white hover:bg-slate-50"}`}
                >
                  <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
                    <div className="min-w-0 space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="max-w-full break-words rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{record.action_type}</span>
                        <span className={`max-w-full break-words rounded-full px-3 py-1 text-sm ${scoreColor(record.force_score)}`}>
                          评分 {record.force_score ?? "--"}
                        </span>
                        <span className={`max-w-full break-words rounded-full px-3 py-1 text-sm ${statusTone(record.status)}`}>
                          {statusLabel(record.status)}
                        </span>
                        {record.skill_category ? (
                          <span className="max-w-full break-words rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-600">{record.skill_category}</span>
                        ) : null}
                      </div>

                      <div className="text-sm text-slate-400">
                        <span>{formatDate(record.created_at)}</span>
                        {record.skater_name ? <span className="ml-3">练习档案：{record.skater_name}</span> : null}
                      </div>

                      <p className="max-w-3xl whitespace-normal break-words leading-7 text-slate-600">{record.note || "本次记录未填写训练备注。"}</p>
                    </div>

                    <div className="flex min-w-0 flex-col gap-3 tablet:items-end">
                      <div className="flex flex-wrap items-center gap-2 pr-0 tablet:justify-end tablet:pr-2">
                        {record.status === "completed" || record.status === "failed" ? (
                          <Link
                            to={`/report/${record.id}`}
                            title="查看分析报告"
                            aria-label="查看分析报告"
                            className={`${actionIconClassName} border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100`}
                          >
                            📄
                          </Link>
                        ) : null}

                        {record.status === "completed" ? (
                          <button
                            type="button"
                            onClick={() => requestReanalysis(record)}
                            disabled={isRetrying}
                            title="再次分析"
                            aria-label="再次分析"
                            className={`${actionIconClassName} border-orange-200 bg-orange-50 text-orange-600 hover:bg-orange-100`}
                          >
                            {isRetrying ? "…" : "🔄"}
                          </button>
                        ) : null}

                        {isAnalysisInProgress(record.status) ? (
                          <Link
                            to={`/report/${record.id}`}
                            title="分析进行中"
                            aria-label="分析进行中"
                            className={`${actionIconClassName} border-blue-100 bg-blue-50 text-blue-500 hover:bg-blue-100`}
                          >
                            ⏳
                          </Link>
                        ) : null}

                        {record.status === "failed" && !hideRetry ? (
                          <button
                            type="button"
                            onClick={() => void handleRetryRecord(record)}
                            disabled={isRetrying}
                            title="分析失败，点击重试"
                            aria-label="分析失败，点击重试"
                            className={`${actionIconClassName} border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100`}
                          >
                            {isRetrying ? "…" : "❌"}
                          </button>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap gap-3 tablet:justify-end">
                        {record.status === "failed" && hideRetry ? (
                          <button
                            type="button"
                            onClick={() =>
                              navigate("/review", {
                                state: record.skater_id ? { skaterId: record.skater_id } : undefined,
                              })
                            }
                            className="list-row-action inline-flex min-w-[44px] rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
                          >
                            📤 重新上传
                          </button>
                        ) : null}

                        {isParentMode ? (
                          <button
                            type="button"
                            onClick={() => openDeleteModal(record.id)}
                            disabled={isAnalysisInProgress(record.status)}
                            title={
                              isAnalysisInProgress(record.status)
                                ? "分析进行中，无法删除"
                                : "删除这条分析记录"
                            }
                            className="list-row-action inline-flex shrink-0 rounded-full border border-rose-200 bg-rose-50 text-lg text-rose-600 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            🗑️
                          </button>
                        ) : null}

                        <button type="button" onClick={() => toggleSelect(record)} className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
                          {isSelected ? "取消对比" : "加入对比"}
                        </button>
                      </div>
                    </div>
                  </div>
                </article>
              );
            })}
            {hasMoreRecords ? (
              <button
                type="button"
                onClick={() => void handleLoadMore()}
                disabled={isLoadingMore}
                className="min-h-[44px] w-full rounded-full border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 transition hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isLoadingMore ? "正在加载更多..." : "加载更多历史记录"}
              </button>
            ) : null}
          </div>
        ) : (
          <div className="mt-6 flex flex-col items-center rounded-[28px] bg-slate-50 px-6 py-10 text-center">
            <ZodiacAvatar
              avatarType={currentSkater?.avatar_type ?? childViewAvatarType(childView)}
              avatarEmoji={currentSkater?.avatar_emoji}
              size="lg"
              animate
            />
            <h3 className="mt-5 text-2xl font-semibold text-slate-900">{emptyStateName}还没有训练记录</h3>
            <p className="mt-3 max-w-md text-base leading-7 text-slate-500">拍一段练习视频，让冰宝来分析 🎬</p>
            <button
              type="button"
              onClick={handleUploadFirstVideo}
              className="mt-6 inline-flex min-h-[48px] items-center justify-center rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
            >
              + 上传第一个视频
            </button>
          </div>
        )}
      </section>

      {selectedIds.length ? (
        <div className="fixed inset-x-0 bottom-4 z-30 px-4">
          <div className="mx-auto flex max-w-3xl flex-col gap-3 rounded-[1.75rem] border border-slate-200 bg-white p-4 shadow-lg md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-900">已选择 {selectedIds.length}/2 条记录</p>
              <p className="mt-1 text-sm text-slate-500">只能选择同动作类型的 completed 记录进行对比。</p>
            </div>
            <button
              type="button"
              disabled={selectedRecords.length !== 2}
              onClick={() => void handleStartComparison()}
              className="rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isCreatingComparison ? "正在创建…" : "开始对比"}
            </button>
          </div>
        </div>
      ) : null}

        {deletingRecordId ? (
          <DeleteAnalysisModal
            step={deleteStep}
            pin={deletePin}
            pinLength={pinLength}
            error={deleteError}
            isSubmitting={isDeleting}
            onChangePin={setDeletePin}
            onClose={closeDeleteModal}
            onConfirmDelete={() => setDeleteStep("pin")}
            onSubmitPin={() => void handleDeleteRecord()}
          />
        ) : null}

        {pinRetryRecord ? (
          <ParentPinVerifyModal
            pinLength={pinLength}
            title="输入家长 PIN"
            description="验证通过后才能重新分析这个视频。"
            confirmLabel="继续"
            onClose={() => setPinRetryRecordId(null)}
            onVerified={handleVerifiedRetry}
          />
        ) : null}

        {confirmRetryRecord ? (
          <RetryAnalysisConfirmSheet
            isSubmitting={retryingRecordId === confirmRetryRecord.id}
            resetTargetLock
            onClose={() => {
              if (retryingRecordId !== confirmRetryRecord.id) {
                setConfirmRetryRecordId(null);
              }
            }}
            onConfirm={() =>
              void (async () => {
                await handleRetryRecord(confirmRetryRecord);
                setConfirmRetryRecordId(null);
              })()
            }
          />
        ) : null}
    </div>
  );
}
