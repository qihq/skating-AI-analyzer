import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { AnalysisListItem, deleteAnalysis, fetchAnalyses } from "../api/client";
import DeleteAnalysisModal from "../components/DeleteAnalysisModal";
import { useAppMode } from "../components/AppModeContext";
import TopNav from "../components/TopNav";

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateString));
}

function scoreColor(score: number | null) {
  if (score === null) {
    return "bg-slate-500/20 text-slate-200";
  }
  if (score < 60) {
    return "bg-rose-500/15 text-rose-100";
  }
  if (score <= 80) {
    return "bg-amber-400/15 text-amber-50";
  }
  return "bg-emerald-400/15 text-emerald-50";
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
    return "border-emerald-400/25 bg-emerald-400/10 text-emerald-100";
  }
  if (status === "failed") {
    return "border-rose-400/25 bg-rose-500/10 text-rose-100";
  }
  return "border-cyan-300/25 bg-cyan-400/10 text-cyan-100";
}

export default function HistoryPage() {
  const navigate = useNavigate();
  const { isParentMode, pinLength } = useAppMode();
  const [activeFilter, setActiveFilter] = useState<(typeof FILTER_OPTIONS)[number]>("全部");
  const [records, setRecords] = useState<AnalysisListItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [deletingRecordId, setDeletingRecordId] = useState<string | null>(null);
  const [deleteStep, setDeleteStep] = useState<"confirm" | "pin">("confirm");
  const [deletePin, setDeletePin] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setIsLoading(true);
      try {
        const data = await fetchAnalyses(activeFilter === "全部" ? undefined : { action_type: activeFilter });
        if (!cancelled) {
          setRecords(data);
          setError(null);
          setSelectedIds((current) => current.filter((id) => data.some((record) => record.id === id)));
        }
      } catch {
        if (!cancelled) {
          setError("历史记录加载失败，请稍后刷新。");
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
  }, [activeFilter]);

  const selectedRecords = useMemo(
    () => records.filter((record) => selectedIds.includes(record.id)),
    [records, selectedIds],
  );

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

  return (
    <main className="page-shell min-h-screen">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="ice-orb left-[10%] top-[8%]" />
        <div className="ice-orb bottom-[10%] right-[6%]" />
        <div className="grid-ice h-full w-full" />
      </div>

      <section className="mx-auto min-h-screen w-full max-w-6xl px-6 py-6 lg:px-10">
        <TopNav />

        <header className="frost-panel">
          <p className="text-sm uppercase tracking-[0.3em] text-cyan-200/80">History</p>
          <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h2 className="text-3xl font-semibold text-white">训练历史与复盘对比</h2>
              <p className="mt-2 max-w-3xl text-slate-300">
                按动作类型查看历史复盘记录，选择两条同动作类型的 completed 记录做进步对比。
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link to="/progress" className="pill-link">
                查看进步趋势
              </Link>
            </div>
          </div>
        </header>

        <div className="mt-6 flex flex-wrap gap-3">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setActiveFilter(option)}
              className={`rounded-full px-4 py-2 text-sm transition ${
                activeFilter === option ? "bg-cyan-300 text-slate-950" : "bg-white/6 text-slate-200 hover:bg-white/12"
              }`}
            >
              {option}
            </button>
          ))}
        </div>

        {notice ? <div className="mt-4 rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
        {error ? <div className="mt-4 text-sm text-rose-200">{error}</div> : null}

        <div className="mt-6 space-y-4">
          {isLoading ? (
            <div className="frost-panel text-slate-300">正在加载历史记录…</div>
          ) : records.length ? (
            records.map((record) => {
              const isSelected = selectedIds.includes(record.id);
              return (
                <article
                  key={record.id}
                  className={`frost-panel transition ${isSelected ? "ring-1 ring-cyan-300/70" : "hover:bg-white/6"}`}
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="rounded-full bg-white/8 px-3 py-1 text-sm text-white">{record.action_type}</span>
                        <span className={`rounded-full px-3 py-1 text-sm ${scoreColor(record.force_score)}`}>
                          评分 {record.force_score ?? "--"}
                        </span>
                        <span className={`rounded-full border px-3 py-1 text-sm ${statusTone(record.status)}`}>
                          {statusLabel(record.status)}
                        </span>
                        {record.skill_category ? (
                          <span className="rounded-full bg-sky-400/10 px-3 py-1 text-sm text-sky-100">{record.skill_category}</span>
                        ) : null}
                      </div>

                      <div className="text-sm text-slate-300">
                        <span>{formatDate(record.created_at)}</span>
                        {record.skater_name ? <span className="ml-3">练习档案：{record.skater_name}</span> : null}
                      </div>

                      <p className="max-w-3xl text-slate-100/90">{record.note || "本次记录未填写训练备注。"}</p>
                    </div>

                    <div className="flex flex-wrap gap-3">
                      {isParentMode ? (
                        <button
                          type="button"
                          onClick={() => openDeleteModal(record.id)}
                          disabled={record.status === "processing"}
                          title={record.status === "processing" ? "分析进行中，无法删除" : "删除这条分析记录"}
                          className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-rose-300/25 bg-rose-500/10 text-lg text-rose-100 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          🗑️
                        </button>
                      ) : null}
                      <button type="button" onClick={() => toggleSelect(record)} className="pill-link">
                        {isSelected ? "取消对比" : "加入对比"}
                      </button>
                      <Link to={`/report/${record.id}`} className="rounded-full bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950">
                        查看报告
                      </Link>
                    </div>
                  </div>
                </article>
              );
            })
          ) : (
            <div className="frost-panel text-slate-300">当前筛选下还没有复盘记录，先去上传一段训练视频吧。</div>
          )}
        </div>

        {selectedIds.length ? (
          <div className="fixed inset-x-0 bottom-4 z-30 px-4">
            <div className="mx-auto flex max-w-3xl flex-col gap-3 rounded-[1.75rem] border border-cyan-300/25 bg-slate-950/88 p-4 shadow-[0_20px_70px_rgba(2,8,23,0.42)] backdrop-blur md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-sm font-medium text-white">已选择 {selectedIds.length}/2 条记录</p>
                <p className="mt-1 text-sm text-slate-400">只能选择同动作类型的 completed 记录进行对比。</p>
              </div>
              <button
                type="button"
                disabled={selectedRecords.length !== 2}
                onClick={() => navigate(`/compare/${selectedRecords[0].id}/${selectedRecords[1].id}`)}
                className="rounded-full bg-cyan-300 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                开始对比
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
      </section>
    </main>
  );
}
