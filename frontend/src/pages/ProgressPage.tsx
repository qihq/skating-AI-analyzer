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

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;

type FilterOption = (typeof FILTER_OPTIONS)[number];
type ChartPoint = ProgressPoint & { dateLabel: string };

function formatDateShort(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(new Date(dateString));
}

export default function ProgressPage() {
  const [activeFilter, setActiveFilter] = useState<FilterOption>("全部");
  const [data, setData] = useState<ProgressResponse | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<ProgressPoint | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const chartData = useMemo(
    () =>
      (data?.points ?? []).map((point): ChartPoint => ({
        ...point,
        dateLabel: formatDateShort(point.created_at),
      })),
    [data],
  );

  return (
    <main className="page-shell min-h-screen">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="ice-orb left-[8%] top-[8%]" />
        <div className="ice-orb bottom-[10%] right-[10%]" />
        <div className="grid-ice h-full w-full" />
      </div>

      <section className="mx-auto min-h-screen w-full max-w-6xl px-6 py-6 lg:px-10">
        <TopNav />

        <header className="frost-panel">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-cyan-200/80">Progress</p>
              <h2 className="mt-3 text-3xl font-semibold text-white">进步趋势折线图</h2>
              <p className="mt-2 max-w-3xl text-slate-300">
                跟踪每次训练复盘的发力评分变化，快速看到近期上升趋势、波动区间和最新阶段的训练摘要。
              </p>
            </div>
            <Link to="/history" className="pill-link">
              返回历史记录
            </Link>
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

        {error ? <div className="mt-5 text-sm text-rose-200">{error}</div> : null}

        <div className="mt-6 grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="frost-panel min-h-[420px]">
            {chartData.length ? (
              <ResponsiveContainer width="100%" height={360}>
                <LineChart
                  data={chartData}
                  onClick={(state: { activePayload?: Array<{ payload?: ChartPoint }> }) => {
                    const payload = state?.activePayload?.[0]?.payload as ChartPoint | undefined;
                    if (payload) {
                      setSelectedPoint(payload);
                    }
                  }}
                >
                  <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                  <XAxis dataKey="dateLabel" stroke="#cbd5e1" tickLine={false} axisLine={false} />
                  <YAxis domain={[0, 100]} stroke="#cbd5e1" tickLine={false} axisLine={false} />
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
            ) : (
              <div className="flex h-full items-center justify-center text-slate-300">当前筛选下还没有可展示的趋势数据。</div>
            )}
          </div>

          <div className="space-y-6">
            <div className="frost-panel">
              <p className="text-sm uppercase tracking-[0.28em] text-cyan-200/80">Selected Point</p>
              {selectedPoint ? (
                <>
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <span className="rounded-full bg-white/8 px-3 py-1 text-sm text-white">{selectedPoint.action_type}</span>
                    <span className="rounded-full bg-cyan-300/12 px-3 py-1 text-sm text-cyan-50">
                      评分 {selectedPoint.force_score}
                    </span>
                  </div>
                  <p className="mt-4 text-sm text-slate-400">{new Date(selectedPoint.created_at).toLocaleString("zh-CN")}</p>
                  <p className="mt-4 leading-7 text-slate-100/90">{selectedPoint.summary}</p>
                </>
              ) : (
                <p className="mt-4 text-slate-300">点击折线图中的任意数据点，查看对应训练摘要。</p>
              )}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
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
    </main>
  );
}
