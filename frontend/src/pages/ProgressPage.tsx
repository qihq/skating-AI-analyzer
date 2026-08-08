import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fetchProgress, type ProgressPoint, type ProgressResponse } from "../api/client";
import { useAnalysisExperiences } from "../analysis-v2/useAnalysisExperiences";
import { presentAnalysisExperience } from "../analysis-v2/presenter";
import type { AnalysisExperienceV2 } from "../analysis-v2/contracts";
import TopNav from "../components/TopNav";
import { parseApiDate } from "../utils/datetime";
import { createShareImagePreview, normalizeShareText, type ShareImagePreview } from "../utils/shareCanvas";
import { exportShareDocument } from "../utils/shareExport";
import IslandShareDialog from "../modern/IslandShareDialog";

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;
type FilterOption = (typeof FILTER_OPTIONS)[number];

type ProgressProjection = {
  point: ProgressPoint;
  experience: AnalysisExperienceV2 | null;
  label: string;
  score: number | null;
  summary: string;
  included: boolean;
};

type ChartPoint = ProgressProjection & { dateLabel: string };

function formatDateShort(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(parseApiDate(value));
}

function formatDateLong(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(parseApiDate(value));
}

function projectPoint(point: ProgressPoint, experience: AnalysisExperienceV2 | null | undefined): ProgressProjection {
  if (!experience) {
    return { point, experience: null, label: "复盘摘要", score: null, summary: "复盘摘要暂不可用，未使用旧记录补齐。", included: false };
  }
  try {
    const view = presentAnalysisExperience(experience);
    const score = view.forceScore;
    const included = experience.familyUsable !== false && view.state === "confirmed" && score != null;
    return {
      point,
      experience,
      label: view.selectedEvent?.label ?? "复盘摘要",
      score: included ? score : null,
      summary: view.summary,
      included,
    };
  } catch {
    return { point, experience: null, label: "复盘摘要", score: null, summary: "复盘来源不一致，暂不显示技术结论。", included: false };
  }
}

function createProgressShareDocument(data: ProgressResponse, selected: ProgressProjection | null, projections: ProgressProjection[], activeFilter: FilterOption) {
  const ordered = [...projections].sort((left, right) => parseApiDate(left.point.created_at).getTime() - parseApiDate(right.point.created_at).getTime());
  const scored = ordered.filter((item) => item.score != null);
  const latest = ordered[ordered.length - 1] ?? null;
  const best = scored.reduce<ProgressProjection | null>((current, item) => (!current || (item.score as number) > (current.score as number) ? item : current), null);
  const recent = ordered.slice(-8).reverse();
  const firstScored = scored[0] ?? null;
  const lastScored = scored[scored.length - 1] ?? null;
  const trend = firstScored && lastScored ? (lastScored.score as number) - (firstScored.score as number) : null;
  const excluded = ordered.filter((item) => !item.included).length;
  const selectedItem = selected ?? latest;
  const sections = [
    {
      label: "趋势概览",
      title: `共 ${data.stats.total_count} 次复盘，最近可用评分 ${lastScored?.score ?? "--"}，历史最高 ${best?.score ?? "--"}，近 5 次均值 ${scored.length ? (scored.slice(-5).reduce((sum, item) => sum + (item.score as number), 0) / Math.min(5, scored.length)).toFixed(1) : "--"}`,
      body: trend != null ? `可用区间变化 ${trend >= 0 ? "+" : ""}${trend} 分。最佳记录：${best ? `${formatDateShort(best.point.created_at)} ${best.score}分` : "暂无"}。${excluded ? `另有 ${excluded} 条记录因证据不足未纳入技术趋势。` : ""}` : "当前没有足够的同一 authority 确认事实形成技术趋势。",
      color: "#0891B2",
      bg: "#ECFEFF",
    },
    ...(selectedItem ? [{
      label: "选中记录",
      title: `${selectedItem.label} · 评分 ${selectedItem.score ?? "--"}`,
      body: normalizeShareText(selectedItem.summary, "本次没有可展示的复盘摘要。"),
      meta: formatDateLong(selectedItem.point.created_at),
      color: "#2563EB",
      bg: "#EFF6FF",
    }] : []),
    {
      label: "最近记录",
      title: recent.map((item) => `${formatDateShort(item.point.created_at)} ${item.label} ${item.score ?? "--"}分`).join("；"),
      body: recent.map((item) => {
        const summary = normalizeShareText(item.summary, "");
        return summary ? `${formatDateShort(item.point.created_at)}：${summary}` : "";
      }).filter(Boolean).join("\n"),
      color: "#059669",
      bg: "#ECFDF5",
    },
  ];
  return {
    eyebrow: "IceBuddy Progress",
    title: `${activeFilter} 进步趋势`,
    subtitle: `${latest?.point.skater_name ?? selectedItem?.point.skater_name ?? "小运动员"} · ${latest ? formatDateShort(latest.point.created_at) : "暂无日期"}`,
    intro: "趋势只纳入同一 authority 下已确认且可比较的事实；其余记录会保留并标注排除原因。",
    sections,
    footer: "进展图由 IceBuddy 生成，趋势仅供训练复盘参考。",
    filename: `icebuddy-progress-${activeFilter}-${Date.now()}.jpg`,
  };
}

export default function ProgressPage() {
  const [activeFilter, setActiveFilter] = useState<FilterOption>("全部");
  const [data, setData] = useState<ProgressResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSharing, setIsSharing] = useState(false);
  const [sharePreview, setSharePreview] = useState<ShareImagePreview[]>([]);

  useEffect(() => {
    let cancelled = false;
    void fetchProgress(activeFilter === "全部" ? undefined : { action_type: activeFilter })
      .then((response) => {
        if (cancelled) return;
        setData(response);
        setSelectedId(response.points.length ? response.points[response.points.length - 1].id : null);
        setError(null);
      })
      .catch(() => { if (!cancelled) setError("趋势数据加载失败，请稍后重试。"); });
    return () => { cancelled = true; };
  }, [activeFilter]);

  const experienceIds = useMemo(() => (data?.points ?? []).map((point) => point.id), [data]);
  const { experiences, loading: experiencesLoading } = useAnalysisExperiences(experienceIds);
  const projections = useMemo(() => (data?.points ?? []).map((point) => projectPoint(point, experiences[point.id])), [data, experiences]);
  const selected = projections.find((item) => item.point.id === selectedId) ?? (projections.length ? projections[projections.length - 1] : null);
  const chartData = useMemo(() => projections.map((item) => ({ ...item, dateLabel: formatDateShort(item.point.created_at) })), [projections]);
  const includedCount = projections.filter((item) => item.included).length;
  const excludedCount = projections.length - includedCount;
  const showNotice = (message: string) => { setNotice(message); window.setTimeout(() => setNotice(null), 2400); };

  const handleShareProgress = async () => {
    if (!data || isSharing) return;
    setIsSharing(true);
    try {
      const result = await exportShareDocument(createProgressShareDocument(data, selected, projections, activeFilter));
      setSharePreview(result.pages.map((page) => createShareImagePreview(page, false)));
      showNotice("进展分享图已生成");
    } catch { setError("进展分享图生成失败，请稍后重试。"); } finally { setIsSharing(false); }
  };

  return (
    <main className="page-shell page-scroll-container min-h-screen">
      <div className="absolute inset-0 -z-10 overflow-hidden"><div className="ice-orb left-[8%] top-[8%]" /><div className="ice-orb bottom-[10%] right-[10%]" /><div className="grid-ice h-full w-full" /></div>
      <section className="mx-auto min-h-screen w-full max-w-6xl px-4 py-4 sm:px-6 sm:py-6 lg:px-10">
        <TopNav />
        <header className="frost-panel"><div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between"><div><p className="text-sm uppercase tracking-[0.3em] text-cyan-200/80">Progress</p><h2 className="mt-3 text-2xl font-semibold text-white sm:text-3xl">进步趋势折线图</h2><p className="mt-2 max-w-3xl text-sm leading-7 text-slate-300 sm:text-base">跟踪已确认复盘事实的评分变化，快速看到近期上升趋势、波动区间和需要复核的记录。</p></div><div className="flex flex-wrap gap-3"><button type="button" onClick={() => void handleShareProgress()} disabled={!data?.points.length || isSharing} className="pill-link w-fit disabled:cursor-not-allowed disabled:opacity-50">{isSharing ? "生成中..." : "分享进展图"}</button><Link to="/history" className="pill-link w-fit">返回历史记录</Link></div></div></header>
        <div className="mt-6 flex flex-wrap gap-3">{FILTER_OPTIONS.map((option) => <button key={option} type="button" onClick={() => setActiveFilter(option)} className={`rounded-full px-4 py-2 text-sm transition ${activeFilter === option ? "bg-cyan-300 text-slate-950" : "bg-white/6 text-slate-200 hover:bg-white/12"}`}>{option}</button>)}</div>
        {notice ? <div className="mt-5 rounded-[24px] border border-cyan-300/20 bg-cyan-300/12 px-5 py-4 text-sm text-cyan-50">{notice}</div> : null}
        {error ? <div className="mt-5 text-sm text-rose-200">{error}</div> : null}
        <div className="mt-6 grid gap-4 lg:grid-cols-[1.1fr_0.9fr] lg:gap-6">
          <div className="frost-panel min-h-[300px] overflow-hidden px-2 py-3 sm:min-h-[420px] sm:px-6 sm:py-5">{chartData.length ? <div className="h-[280px] sm:h-[320px]"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 8, left: -16 }} onClick={(state: { activePayload?: Array<{ payload?: ChartPoint }> }) => { const item = state?.activePayload?.[0]?.payload; if (item) setSelectedId(item.point.id); }}><CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} /><XAxis dataKey="dateLabel" stroke="#cbd5e1" tickLine={false} axisLine={false} minTickGap={20} /><YAxis width={28} domain={[0, 100]} stroke="#cbd5e1" tickLine={false} axisLine={false} /><Tooltip cursor={{ stroke: "rgba(34,211,238,0.35)", strokeWidth: 1 }} contentStyle={{ background: "rgba(2, 6, 23, 0.92)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: "18px", color: "#f8fafc" }} /><Line type="monotone" dataKey="score" connectNulls={false} stroke="#67e8f9" strokeWidth={3} dot={{ r: 5, strokeWidth: 0, fill: "#22d3ee", cursor: "pointer" }} activeDot={{ r: 7, fill: "#cffafe" }} /></LineChart></ResponsiveContainer></div> : <div className="flex h-full items-center justify-center text-center text-sm text-slate-300 sm:text-base">当前筛选下还没有可展示的趋势数据。</div>}</div>
          <div className="space-y-4 sm:space-y-6"><div className="frost-panel min-w-0 overflow-hidden p-4 sm:p-6"><p className="text-sm uppercase tracking-[0.28em] text-cyan-200/80">Selected Point</p>{selected ? <><div className="mt-3 flex flex-wrap items-start gap-2"><span className="rounded-full bg-white/8 px-3 py-1 text-sm text-white">{selected.label}</span><span className="rounded-full bg-cyan-300/12 px-3 py-1 text-sm text-cyan-50">评分 {selected.score ?? "--"}</span></div><p className="mt-4 break-words text-sm leading-6 text-slate-400">{formatDateLong(selected.point.created_at)}</p><p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-slate-100/90 sm:text-base">{selected.summary}</p>{!selected.included ? <p className="mt-3 text-xs leading-6 text-amber-200">此记录未纳入技术趋势：需要同一 authority 下的确认事实。</p> : null}</> : <p className="mt-4 text-sm leading-7 text-slate-300 sm:text-base">点击折线图中的任意数据点，查看对应复盘摘要。</p>}</div><div className="grid gap-3 sm:grid-cols-2 sm:gap-4"><div className="stat-panel"><p className="stat-label">总次数</p><p className="stat-value">{data?.stats.total_count ?? 0}</p><p className="stat-meta">完成复盘记录</p></div><div className="stat-panel"><p className="stat-label">可用记录</p><p className="stat-value">{experiencesLoading ? "…" : includedCount}</p><p className="stat-meta">已确认可比较事实</p></div><div className="stat-panel"><p className="stat-label">排除记录</p><p className="stat-value">{experiencesLoading ? "…" : excludedCount}</p><p className="stat-meta">证据不足或冲突</p></div><div className="stat-panel"><p className="stat-label">最新可用评分</p><p className="stat-value">{[...projections].reverse().find((item) => item.score != null)?.score ?? "--"}</p><p className="stat-meta">同 authority 趋势</p></div></div></div>
        </div>
      </section>
      <IslandShareDialog preview={null} previews={sharePreview} title="进展分享图" onClose={() => setSharePreview([])} />
    </main>
  );
}
