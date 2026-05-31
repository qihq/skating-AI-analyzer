import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  AnalysisCompareResponse,
  CompareDelta,
  CompareKeyframePair,
  CompareKeyframeSide,
  CompareVideoSide,
  fetchAnalysisCompare,
} from "../api/client";
import ReportCard from "../components/ReportCard";
import { parseApiDate } from "../utils/datetime";

const ISSUE_STYLES: Record<string, string> = {
  high: "border-rose-400/45 bg-rose-500/10",
  medium: "border-amber-300/45 bg-amber-400/10",
  low: "border-sky-300/40 bg-sky-400/10",
};

const SPEED_OPTIONS = [0.25, 0.5, 1] as const;

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(parseApiDate(dateString));
}

function formatValue(value: number | null | undefined, unit?: string | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  const text = Number.isInteger(value) ? String(value) : value.toFixed(Math.abs(value) < 10 ? 2 : 1);
  return `${text}${unit ?? ""}`;
}

function signedValue(value: number | null | undefined, unit?: string | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatValue(value, unit)}`;
}

function trendClass(delta: number | null) {
  if (typeof delta !== "number") {
    return "text-slate-500";
  }
  if (delta > 0) {
    return "text-emerald-600";
  }
  if (delta < 0) {
    return "text-rose-600";
  }
  return "text-slate-600";
}

function scoreTone(delta: number) {
  if (delta > 0) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (delta < 0) {
    return "border-rose-200 bg-rose-50 text-rose-600";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function deltaBarWidth(delta: number | null) {
  if (typeof delta !== "number") {
    return "0%";
  }
  return `${Math.min(Math.abs(delta), 30) * (100 / 30)}%`;
}

function VideoPane({
  title,
  side,
  videoRef,
}: {
  title: string;
  side: CompareVideoSide;
  videoRef: React.RefObject<HTMLVideoElement>;
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[28px] border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-blue-500">{title}</p>
          <p className="mt-1 text-sm text-slate-500">
            动作窗口 {formatValue(side.action_window_start, "s")} - {formatValue(side.action_window_end, "s")}
          </p>
        </div>
        {side.is_slow_motion ? (
          <span className="rounded-full bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-600">
            慢动作 {Math.round(side.source_fps ?? 0)}fps
          </span>
        ) : null}
      </div>
      <div className="aspect-video bg-slate-950">
        {side.available && side.video_url ? (
          <video ref={videoRef} src={side.video_url} preload="metadata" playsInline className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm leading-7 text-slate-400">
            {side.missing_reason ?? "原视频不可用，仍可查看关键帧与量化对比。"}
          </div>
        )}
      </div>
    </div>
  );
}

function SyncedVideoSection({ data }: { data: AnalysisCompareResponse }) {
  const beforeRef = useRef<HTMLVideoElement | null>(null);
  const afterRef = useRef<HTMLVideoElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEED_OPTIONS)[number]>(0.5);
  const videoCompare = data.video_compare;

  const getActionWindow = useCallback(
    (side: CompareVideoSide) => {
      const start = side.sync_start ?? side.action_window_start ?? 0;
      const duration = side.sync_duration ?? side.action_window_duration ?? (side.action_window_end != null && side.action_window_start != null
        ? side.action_window_end - side.action_window_start
        : null);
      return { start, duration: duration && duration > 0 ? duration : null };
    },
    [],
  );

  const seekBoth = useCallback(
    (relativePosition: number) => {
      if (!videoCompare) {
        return;
      }
      const pairs: Array<[HTMLVideoElement | null, CompareVideoSide]> = [
        [beforeRef.current, videoCompare.before],
        [afterRef.current, videoCompare.after],
      ];
      pairs.forEach(([video, side]) => {
        if (!video || !side.available) {
          return;
        }
        const { start, duration } = getActionWindow(side);
        if (duration) {
          video.currentTime = Math.max(0, start + relativePosition * duration);
        } else {
          video.currentTime = Math.max(0, start + relativePosition);
        }
      });
    },
    [videoCompare, getActionWindow],
  );

  const seekKeyframe = useCallback(
    (pair: CompareKeyframePair) => {
      if (!videoCompare) {
        return;
      }
      const items: Array<[HTMLVideoElement | null, CompareVideoSide, number | null]> = [
        [beforeRef.current, videoCompare.before, pair.before.timestamp],
        [afterRef.current, videoCompare.after, pair.after.timestamp],
      ];
      items.forEach(([video, side, timestamp]) => {
        if (!video || !side.available) {
          return;
        }
        if (timestamp != null) {
          video.currentTime = Math.max(0, timestamp);
        } else {
          const { start } = getActionWindow(side);
          video.currentTime = Math.max(0, start);
        }
      });
    },
    [videoCompare, getActionWindow],
  );

  const applyProportionalRates = useCallback(
    (baseSpeed: number) => {
      if (!videoCompare) {
        return;
      }
      const beforeDuration = getActionWindow(videoCompare.before).duration;
      const afterDuration = getActionWindow(videoCompare.after).duration;
      const maxDuration = Math.max(beforeDuration ?? 1, afterDuration ?? 1);

      const videos: Array<[HTMLVideoElement | null, CompareVideoSide]> = [
        [beforeRef.current, videoCompare.before],
        [afterRef.current, videoCompare.after],
      ];
      videos.forEach(([video, side]) => {
        if (!video) {
          return;
        }
        const duration = getActionWindow(side).duration;
        video.playbackRate = duration ? baseSpeed * (duration / maxDuration) : baseSpeed;
      });
    },
    [videoCompare, getActionWindow],
  );

  const setPlaybackRate = useCallback(
    (nextSpeed: (typeof SPEED_OPTIONS)[number]) => {
      setSpeed(nextSpeed);
      applyProportionalRates(nextSpeed);
    },
    [applyProportionalRates],
  );

  const togglePlayback = useCallback(async () => {
    const videos = [beforeRef.current, afterRef.current].filter(Boolean) as HTMLVideoElement[];
    if (!videos.length) {
      return;
    }
    if (isPlaying) {
      videos.forEach((video) => video.pause());
      setIsPlaying(false);
      return;
    }
    seekBoth(0);
    applyProportionalRates(speed);
    const results = await Promise.allSettled(videos.map((video) => video.play()));
    setIsPlaying(results.some((result) => result.status === "fulfilled"));
  }, [isPlaying, speed, seekBoth, applyProportionalRates]);

  useEffect(() => {
    const videos = [beforeRef.current, afterRef.current].filter(Boolean) as HTMLVideoElement[];
    const handlePause = () => setIsPlaying(false);
    videos.forEach((video) => {
      video.addEventListener("ended", handlePause);
      video.addEventListener("pause", handlePause);
    });
    return () => {
      videos.forEach((video) => {
        video.removeEventListener("ended", handlePause);
        video.removeEventListener("pause", handlePause);
      });
    };
  }, [speed]);

  if (!videoCompare) {
    return null;
  }

  return (
    <ReportCard title="同步回放" eyebrow="Video Sync">
      <div className="grid gap-4 lg:grid-cols-2">
        <VideoPane title="之前" side={videoCompare.before} videoRef={beforeRef} />
        <VideoPane title="现在" side={videoCompare.after} videoRef={afterRef} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3 rounded-[24px] border border-slate-200 bg-slate-50 p-3">
        <button type="button" onClick={() => seekBoth(0)} className="pill-link">
          跳到动作开始
        </button>
        {data.keyframe_compare.map((item) => {
          return (
            <button key={item.key} type="button" onClick={() => seekKeyframe(item)} className="pill-link">
              {item.label}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => void togglePlayback()}
          className="rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
        >
          {isPlaying ? "暂停" : "同步播放"}
        </button>
        <div className="ml-auto flex rounded-full border border-slate-200 bg-white p-1">
          {SPEED_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setPlaybackRate(option)}
              className={`rounded-full px-3 py-2 text-xs font-semibold transition ${
                speed === option ? "bg-blue-500 text-white" : "text-slate-500 hover:bg-slate-100"
              }`}
            >
              {option}x
            </button>
          ))}
        </div>
      </div>
    </ReportCard>
  );
}

function KeyframeImage({ side, title }: { side: CompareKeyframeSide; title: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[24px] border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        <p className="text-xs text-slate-400">
          {side.timestamp != null ? `${side.timestamp.toFixed(2)}s` : "--"}
          {side.confidence != null ? ` · ${(side.confidence * 100).toFixed(0)}%` : ""}
        </p>
      </div>
      <div className="aspect-video bg-slate-950">
        {side.available && side.frame_url ? (
          <img src={side.frame_url} alt={`${title} ${side.frame_id ?? ""}`} className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full items-center justify-center px-4 text-center text-sm leading-6 text-slate-400">
            {side.missing_reason ?? "该阶段未可靠识别"}
          </div>
        )}
      </div>
      <div className="space-y-1 px-4 py-3 text-xs text-slate-400">
        <p>{side.frame_id ?? "无关键帧"}</p>
        {side.source || side.phase_label || side.selection_reason ? (
          <p>
            {side.source ? `来源：${side.source}` : ""}
            {side.phase_label ? ` · 阶段：${side.phase_label}` : ""}
            {side.selection_reason ? ` · ${side.selection_reason}` : ""}
          </p>
        ) : null}
        {side.refinement_method ? (
          <p>
            精修：{side.refinement_method}
            {side.refinement_delta_sec != null ? ` · ${signedValue(side.refinement_delta_sec, "s")}` : ""}
            {side.pre_refine_timestamp != null ? ` · 原 ${side.pre_refine_timestamp.toFixed(2)}s` : ""}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function KeyframeCompareSection({ data }: { data: AnalysisCompareResponse }) {
  if (!data.keyframe_compare.length) {
    return null;
  }

  return (
    <ReportCard title="关键帧姿态对照" eyebrow="Pose Frames">
      <div className="space-y-5">
        {data.keyframe_compare.map((item) => (
          <section key={item.key} className="rounded-[28px] border border-slate-200 bg-slate-50 p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-xl font-semibold text-slate-900">{item.label}</h3>
              <span className="rounded-full bg-cyan-50 px-3 py-1 text-xs uppercase tracking-[0.2em] text-cyan-700">{item.key}</span>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <KeyframeImage side={item.before} title="之前" />
              <KeyframeImage side={item.after} title="现在" />
            </div>
          </section>
        ))}
      </div>
    </ReportCard>
  );
}

function SubscoreRadar({ items }: { items: CompareDelta[] }) {
  const chartData = items.map((item) => ({
    label: item.label,
    before: item.before ?? 0,
    after: item.after ?? 0,
  }));
  return (
    <div className="h-[320px] min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={chartData}>
          <PolarGrid stroke="rgba(226,232,240,0.5)" />
          <PolarAngleAxis dataKey="label" tick={{ fill: "#64748b", fontSize: 12 }} />
          <Radar name="之前" dataKey="before" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.18} />
          <Radar name="现在" dataKey="after" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.28} />
          <Tooltip
            contentStyle={{
              background: "#ffffff",
              border: "1px solid #e2e8f0",
              borderRadius: "16px",
              color: "#0f172a",
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

function DeltaBars({ items }: { items: CompareDelta[] }) {
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.key} className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-slate-900">{item.label}</p>
            <p className={`text-sm font-semibold ${trendClass(item.delta)}`}>{signedValue(item.delta, item.unit)}</p>
          </div>
          <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
            <span>之前 {formatValue(item.before, item.unit)}</span>
            <span>现在 {formatValue(item.after, item.unit)}</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full rounded-full ${typeof item.delta === "number" && item.delta < 0 ? "bg-rose-300" : "bg-blue-500"}`}
              style={{ width: deltaBarWidth(item.delta) }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function MetricChart({ items }: { items: CompareDelta[] }) {
  const available = items.filter((item) => item.available);
  if (!available.length) {
    return <p className="text-sm leading-7 text-slate-500">当前两条记录缺少可直接比较的生物力学指标。</p>;
  }
  const chartData = available.map((item) => ({
    label: item.label,
    delta: item.delta ?? 0,
  }));
  return (
    <div className="h-[260px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 10, right: 8, left: -20, bottom: 34 }}>
          <CartesianGrid stroke="rgba(148,163,184,0.14)" vertical={false} />
          <XAxis dataKey="label" stroke="#94a3b8" tickLine={false} axisLine={false} interval={0} angle={-18} textAnchor="end" tick={{ fontSize: 12 }} />
          <YAxis stroke="#94a3b8" tickLine={false} axisLine={false} />
          <Tooltip
            contentStyle={{
              background: "#ffffff",
              border: "1px solid #e2e8f0",
              borderRadius: "16px",
              color: "#0f172a",
            }}
          />
          <Bar dataKey="delta" fill="#3b82f6" radius={[8, 8, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function MetricsSection({ data }: { data: AnalysisCompareResponse }) {
  return (
    <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
      <ReportCard title="分项评分变化" eyebrow="Subscores">
        <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
          <SubscoreRadar items={data.subscore_deltas} />
          <DeltaBars items={data.subscore_deltas} />
        </div>
      </ReportCard>

      <ReportCard title="生物力学指标变化" eyebrow="Biomechanics">
        <MetricChart items={data.metric_deltas} />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {data.metric_deltas.map((item) => (
            <article key={item.key} className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm text-slate-500">{item.label}</p>
              <p className={`mt-2 text-2xl font-semibold ${trendClass(item.delta)}`}>{signedValue(item.delta, item.unit)}</p>
              <p className="mt-2 text-xs text-slate-400">
                {formatValue(item.before, item.unit)} → {formatValue(item.after, item.unit)}
              </p>
            </article>
          ))}
        </div>
      </ReportCard>
    </div>
  );
}

function SummaryGroup({
  title,
  items,
  tone,
}: {
  title: string;
  items: AnalysisCompareResponse["summary"]["improved"];
  tone: string;
}) {
  return (
    <ReportCard title={title} eyebrow="Compare" className={tone}>
      <div className="space-y-3">
        {items.length ? (
          items.map((item, index) => (
            <article key={`${item.category}-${index}`} className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <h3 className="text-base font-medium text-slate-900">{item.category}</h3>
                {item.before_severity ? <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-500">之前 {item.before_severity}</span> : null}
                {item.after_severity ? <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-500">现在 {item.after_severity}</span> : null}
              </div>
              <p className="mt-3 text-sm leading-7 text-slate-600">{item.description}</p>
            </article>
          ))
        ) : (
          <p className="text-sm text-slate-500">当前没有该分类变化。</p>
        )}
      </div>
    </ReportCard>
  );
}

function HeroSummary({ data }: { data: AnalysisCompareResponse }) {
  const before = data.analysis_a;
  const after = data.analysis_b;
  const actionName = after.action_subtype || after.skill_category || after.action_type;
  return (
    <header className="app-card overflow-hidden p-6 tablet:p-8">
      <div className="grid gap-6 lg:grid-cols-[1fr_260px] lg:items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Compare Review</p>
          <h1 className="mt-3 text-3xl font-semibold text-slate-900 sm:text-4xl">{actionName} 进步复盘</h1>
          <div className="mt-4 flex flex-wrap gap-3 text-sm text-slate-500">
            <span>{before.skater_name ?? after.skater_name ?? "小运动员"}</span>
            <span>{formatDate(before.created_at)} → {formatDate(after.created_at)}</span>
            <span>{after.action_type}</span>
          </div>
          {data.ai_narrative ? <p className="mt-5 max-w-4xl text-base leading-8 text-slate-600">{data.ai_narrative}</p> : null}
          {data.quality?.warnings.length ? (
            <div className="mt-4 rounded-[22px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-7 text-amber-700">
              {data.quality.warnings.join(" ")}
            </div>
          ) : null}
        </div>
        <div className={`rounded-[28px] border p-5 text-center ${scoreTone(data.score_delta)}`}>
          <p className="text-sm uppercase tracking-[0.24em] opacity-80">评分变化</p>
          <p className="mt-3 text-5xl font-semibold">
            {data.score_delta >= 0 ? "+" : ""}
            {data.score_delta}
          </p>
          <p className="mt-3 text-sm opacity-80">
            {before.force_score ?? "--"} → {after.force_score ?? "--"}
          </p>
        </div>
      </div>
    </header>
  );
}

export default function ComparePage() {
  const { id_a, id_b } = useParams<{ id_a: string; id_b: string }>();
  const [data, setData] = useState<AnalysisCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!id_a || !id_b) {
      setError("无效的对比参数。");
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      try {
        const response = await fetchAnalysisCompare(id_a, id_b);
        if (!cancelled) {
          setData(response);
          setError(null);
        }
      } catch (requestError) {
        if (!cancelled) {
          const detail = axios.isAxiosError(requestError) ? requestError.response?.data?.detail : null;
          setError(typeof detail === "string" ? detail : "对比结果加载失败，请返回历史记录页重试。");
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
  }, [id_a, id_b]);

  const hasContent = useMemo(() => Boolean(data && !error), [data, error]);

  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/history" className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
          ← 返回历史记录
        </Link>
        {data ? (
          <Link to={`/report/${data.analysis_b.id}`} className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
            查看最新报告
          </Link>
        ) : null}
      </div>

      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}
      {isLoading ? <div className="rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">正在生成对比工作台…</div> : null}

      {hasContent && data ? (
        <div className="space-y-6">
          <HeroSummary data={data} />
          <SyncedVideoSection data={data} />
          <KeyframeCompareSection data={data} />
          <MetricsSection data={data} />
          <div className="grid gap-6 lg:grid-cols-3">
            <SummaryGroup title="改善项" items={data.summary.improved} tone="border border-emerald-200 bg-emerald-50/70" />
            <SummaryGroup title="新增项" items={data.summary.added} tone="border border-rose-200 bg-rose-50/70" />
            <SummaryGroup title="未变化" items={data.summary.unchanged} tone="border border-slate-200 bg-slate-50/80" />
          </div>
        </div>
      ) : null}
    </div>
  );
}
