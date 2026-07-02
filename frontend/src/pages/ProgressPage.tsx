import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fetchProgress, ProgressPoint, ProgressResponse } from "../api/client";
import TopNav from "../components/TopNav";
import { parseApiDate } from "../utils/datetime";
import {
  copyImageBlobToClipboard,
  createAdaptiveSharePoster,
  createShareImagePreview,
  normalizeShareText,
  shareImageFile,
  ShareImagePreview,
} from "../utils/shareCanvas";

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;

type FilterOption = (typeof FILTER_OPTIONS)[number];
type ChartPoint = ProgressPoint & { dateLabel: string };

function formatDateShort(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(parseApiDate(dateString));
}

function formatDateLong(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(dateString));
}

async function createProgressShareImage(data: ProgressResponse, selectedPoint: ProgressPoint | null, activeFilter: FilterOption) {
  const orderedPoints = [...data.points].sort((left, right) => parseApiDate(left.created_at).getTime() - parseApiDate(right.created_at).getTime());
  const latest = orderedPoints[orderedPoints.length - 1] ?? null;
  const best = orderedPoints.reduce<ProgressPoint | null>((current, point) => (!current || point.force_score > current.force_score ? point : current), null);
  const recent = orderedPoints.slice(-8).reverse();
  const trend = orderedPoints.length >= 2 ? orderedPoints[orderedPoints.length - 1].force_score - orderedPoints[0].force_score : 0;
  const selected = selectedPoint ?? latest;
  const sections = [
    {
      label: "趋势概览",
      title: `共 ${data.stats.total_count} 次复盘，最近评分 ${data.stats.latest_score ?? "--"}，历史最高 ${data.stats.best_score ?? "--"}，近 5 次均值 ${data.stats.recent_five_average ?? "--"}`,
      body: orderedPoints.length >= 2 ? `区间变化 ${trend >= 0 ? "+" : ""}${trend} 分。最佳记录：${best ? `${formatDateShort(best.created_at)} ${best.force_score}分` : "暂无"}。` : "当前记录还不够形成长期趋势。",
      color: "#0891B2",
      bg: "#ECFEFF",
    },
    ...(selected
      ? [
          {
            label: "选中记录",
            title: `${selected.action_subtype || selected.action_type} · 评分 ${selected.force_score}`,
            body: normalizeShareText(selected.comments ?? selected.note ?? selected.summary, "本次没有填写 comments。"),
            meta: formatDateLong(selected.created_at),
            color: "#2563EB",
            bg: "#EFF6FF",
          },
        ]
      : []),
    {
      label: "最近记录",
      title: recent
        .map((point) => `${formatDateShort(point.created_at)} ${point.action_subtype || point.action_type} ${point.force_score}分`)
        .join("；"),
      body: recent
        .map((point) => {
          const comment = normalizeShareText(point.comments ?? point.note, "");
          return comment ? `${formatDateShort(point.created_at)} comments：${comment}` : "";
        })
        .filter(Boolean)
        .join("\n"),
      color: "#059669",
      bg: "#ECFDF5",
    },
  ];

  return createAdaptiveSharePoster({
    eyebrow: "IceBuddy Progress",
    title: `${activeFilter} 进步趋势`,
    subtitle: `${latest?.skater_name ?? selected?.skater_name ?? "小运动员"} · ${latest ? formatDateShort(latest.created_at) : "暂无日期"}`,
    scoreLabel: "Latest",
    scoreValue: String(data.stats.latest_score ?? "--"),
    scoreMeta: `Best ${data.stats.best_score ?? "--"}`,
    intro: "每次训练 comments 和评分趋势会一起保留，方便复盘近期动作稳定性。",
    sections,
    footer: "进展图由 IceBuddy 生成，趋势仅供训练复盘参考。",
    filename: `icebuddy-progress-${activeFilter}-${Date.now()}.jpg`,
  });
}

export default function ProgressPage() {
  const [activeFilter, setActiveFilter] = useState<FilterOption>("全部");
  const [data, setData] = useState<ProgressResponse | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<ProgressPoint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSharing, setIsSharing] = useState(false);
  const [sharePreview, setSharePreview] = useState<ShareImagePreview | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const response = await fetchProgress(activeFilter === "全部" ? undefined : { action_type: activeFilter });
        if (!cancelled) {
          setData(response);
          setSelectedPoint(response.points.length ? response.points[response.points.length - 1] : null);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("趋势数据加载失败，请稍后重试。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [activeFilter]);

  useEffect(() => {
    return () => {
      if (sharePreview?.url) {
        URL.revokeObjectURL(sharePreview.url);
      }
    };
  }, [sharePreview?.url]);

  const chartData = useMemo(
    () =>
      (data?.points ?? []).map((point): ChartPoint => ({
        ...point,
        dateLabel: formatDateShort(point.created_at),
      })),
    [data],
  );

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const handleShareProgress = async () => {
    if (!data || isSharing) {
      return;
    }
    setIsSharing(true);
    setError(null);
    try {
      const result = await createProgressShareImage(data, selectedPoint, activeFilter);
      const copiedToClipboard = await copyImageBlobToClipboard(result.blob);
      setSharePreview((current) => {
        if (current?.url) {
          URL.revokeObjectURL(current.url);
        }
        return createShareImagePreview(result, copiedToClipboard);
      });
      showNotice(copiedToClipboard ? "进展分享图已生成并复制" : "进展分享图已生成");
    } catch {
      setError("进展分享图生成失败，请稍后重试。");
    } finally {
      setIsSharing(false);
    }
  };

  const handleCopyShareImage = async () => {
    if (!sharePreview) {
      return;
    }
    const copied = await copyImageBlobToClipboard(sharePreview.blob);
    if (!copied) {
      setError("当前浏览器不能直接复制图片，请先下载后分享。");
      return;
    }
    setSharePreview((current) => (current ? { ...current, copiedToClipboard: true } : current));
    showNotice("进展分享图已复制");
  };

  const handleNativeShareImage = async () => {
    if (!sharePreview) {
      return;
    }
    const shared = await shareImageFile(sharePreview.blob, sharePreview.filename, "IceBuddy 进展分享图");
    if (!shared) {
      setError("当前浏览器不支持直接系统分享图片，请先下载后保存或发送。");
    }
  };

  return (
    <main className="page-shell page-scroll-container min-h-screen">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="ice-orb left-[8%] top-[8%]" />
        <div className="ice-orb bottom-[10%] right-[10%]" />
        <div className="grid-ice h-full w-full" />
      </div>

      <section className="mx-auto min-h-screen w-full max-w-6xl px-4 py-4 sm:px-6 sm:py-6 lg:px-10">
        <TopNav />

        <header className="frost-panel">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-cyan-200/80">Progress</p>
              <h2 className="mt-3 text-2xl font-semibold text-white sm:text-3xl">进步趋势折线图</h2>
              <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-300 sm:text-base">
                跟踪每次训练复盘的发力评分变化，快速看到近期上升趋势、波动区间和最新阶段的训练摘要。
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void handleShareProgress()}
                disabled={!data?.points.length || isSharing}
                className="pill-link w-fit disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSharing ? "生成中..." : "分享进展图"}
              </button>
              <Link to="/history" className="pill-link w-fit">
                返回历史记录
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

        {notice ? <div className="mt-5 rounded-[24px] border border-cyan-300/20 bg-cyan-300/12 px-5 py-4 text-sm text-cyan-50">{notice}</div> : null}
        {error ? <div className="mt-5 text-sm text-rose-200">{error}</div> : null}

        <div className="mt-6 grid gap-4 lg:grid-cols-[1.1fr_0.9fr] lg:gap-6">
          <div className="frost-panel min-h-[300px] overflow-hidden px-2 py-3 sm:min-h-[420px] sm:px-6 sm:py-5">
            {chartData.length ? (
              <div className="h-[280px] sm:h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={chartData}
                    margin={{ top: 8, right: 8, bottom: 8, left: -16 }}
                    onClick={(state: { activePayload?: Array<{ payload?: ChartPoint }> }) => {
                      const payload = state?.activePayload?.[0]?.payload as ChartPoint | undefined;
                      if (payload) {
                        setSelectedPoint(payload);
                      }
                    }}
                  >
                    <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                    <XAxis dataKey="dateLabel" stroke="#cbd5e1" tickLine={false} axisLine={false} minTickGap={20} />
                    <YAxis width={28} domain={[0, 100]} stroke="#cbd5e1" tickLine={false} axisLine={false} />
                    <Tooltip
                      cursor={{ stroke: "rgba(34,211,238,0.35)", strokeWidth: 1 }}
                      contentStyle={{
                        background: "rgba(2, 6, 23, 0.92)",
                        border: "1px solid rgba(255,255,255,0.12)",
                        borderRadius: "18px",
                        color: "#f8fafc",
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="force_score"
                      stroke="#67e8f9"
                      strokeWidth={3}
                      dot={{ r: 5, strokeWidth: 0, fill: "#22d3ee", cursor: "pointer" }}
                      activeDot={{ r: 7, fill: "#cffafe" }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-center text-sm text-slate-300 sm:text-base">
                当前筛选下还没有可展示的趋势数据。
              </div>
            )}
          </div>

          <div className="space-y-4 sm:space-y-6">
            <div className="frost-panel min-w-0 overflow-hidden p-4 sm:p-6">
              <p className="text-sm uppercase tracking-[0.28em] text-cyan-200/80">Selected Point</p>
              {selectedPoint ? (
                <>
                  <div className="mt-3 flex flex-wrap items-start gap-2">
                    <span className="rounded-full bg-white/8 px-3 py-1 text-sm text-white">{selectedPoint.action_subtype || selectedPoint.action_type}</span>
                    <span className="rounded-full bg-cyan-300/12 px-3 py-1 text-sm text-cyan-50">评分 {selectedPoint.force_score}</span>
                  </div>
                  <p className="mt-4 break-words text-sm leading-6 text-slate-400">{formatDateLong(selectedPoint.created_at)}</p>
                  <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-slate-100/90 sm:text-base">
                    {selectedPoint.summary}
                  </p>
                </>
              ) : (
                <p className="mt-4 text-sm leading-7 text-slate-300 sm:text-base">点击折线图中的任意数据点，查看对应训练摘要。</p>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2 sm:gap-4">
              <div className="stat-panel">
                <p className="stat-label">总次数</p>
                <p className="stat-value">{data?.stats.total_count ?? 0}</p>
                <p className="stat-meta">完成复盘记录</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">最近评分</p>
                <p className="stat-value">{data?.stats.latest_score ?? "--"}</p>
                <p className="stat-meta">最新一次结果</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">历史最高</p>
                <p className="stat-value">{data?.stats.best_score ?? "--"}</p>
                <p className="stat-meta">最佳表现</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">近 5 次均值</p>
                <p className="stat-value">{data?.stats.recent_five_average ?? "--"}</p>
                <p className="stat-meta">近期稳定性</p>
              </div>
            </div>
          </div>
        </div>
      </section>
      {sharePreview ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
          <section className="frost-panel max-h-[92vh] w-full max-w-3xl overflow-y-auto p-5 tablet:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.32em] text-cyan-200/80">Share Image</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">进展分享图</h2>
                <p className="mt-2 text-sm text-slate-300">
                  {sharePreview.copiedToClipboard ? "已复制到剪贴板，也可以下载保存。" : "可下载、复制或使用系统分享。"}
                </p>
                <p className="mt-1 text-xs text-slate-400">{Math.max(1, Math.round(sharePreview.sizeBytes / 1024))} KB · JPEG</p>
              </div>
              <button type="button" onClick={() => setSharePreview(null)} className="pill-link min-h-[40px]">
                关闭
              </button>
            </div>
            <div className="mt-5 max-h-[62vh] overflow-auto rounded-[28px] border border-white/10 bg-slate-950/40">
              <img src={sharePreview.url} alt="进展分享图预览" className="mx-auto block h-auto w-full max-w-[720px]" />
            </div>
            <div className="mt-5 flex flex-wrap justify-end gap-3">
              <button type="button" onClick={() => void handleNativeShareImage()} disabled={!sharePreview.canNativeShare} className="pill-link min-h-[44px] disabled:cursor-not-allowed disabled:opacity-50">
                系统分享/保存
              </button>
              <button type="button" onClick={() => void handleCopyShareImage()} className="pill-link min-h-[44px]">
                复制图片
              </button>
              <a href={sharePreview.url} download={sharePreview.filename} className="pill-link min-h-[44px]">
                下载图片
              </a>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
