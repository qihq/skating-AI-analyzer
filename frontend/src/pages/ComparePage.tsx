import axios from "axios";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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
  AnalysisComparisonDetail,
  CompareDelta,
  CompareKeyframePair,
  CompareKeyframeSide,
  CompareVideoSide,
  createAnalysisComparison,
  fetchAnalysisMedia,
  fetchAnalysisComparison,
  retryAnalysisComparison,
  type MediaManifest,
} from "../api/client";
import { IceMediaPlayer, type IceMediaPlayerHandle } from "../media/IceMediaPlayer";
import { useSynchronizedMediaGroup } from "../media/useSynchronizedMediaGroup";
import ReportCard from "../components/ReportCard";
import { parseApiDate } from "../utils/datetime";
import { createShareImagePreview, normalizeShareText, ShareImagePreview } from "../utils/shareCanvas";
import { exportShareDocument } from "../utils/shareExport";
import IslandShareDialog from "../modern/IslandShareDialog";

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

function formatShortDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
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

function videoAiDirectionTone(direction: string) {
  if (direction === "improved") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (direction === "regressed") {
    return "border-rose-200 bg-rose-50 text-rose-600";
  }
  if (direction === "unchanged") {
    return "border-slate-200 bg-slate-50 text-slate-600";
  }
  return "border-sky-200 bg-sky-50 text-sky-700";
}

function videoAiDirectionLabel(direction: string) {
  if (direction === "improved") {
    return "æ”¹å–„";
  }
  if (direction === "regressed") {
    return "éœ€å…³æ³¨";
  }
  if (direction === "unchanged") {
    return "ç¨³å®š";
  }
  return "è§‚å¯Ÿ";
}

function deltaBarWidth(delta: number | null) {
  if (typeof delta !== "number") {
    return "0%";
  }
  return `${Math.min(Math.abs(delta), 30) * (100 / 30)}%`;
}

function formatPercent(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return `${Math.round(value * 100)}%`;
}

function normalizeShareSnippet(value: string | null | undefined, fallback: string, maxLength = 92) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) {
    return fallback;
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}â€¦` : text;
}

function comparisonStatusLabel(status: string) {
  if (status === "pending") {
    return "ç­‰å¾…ç”Ÿæˆ";
  }
  if (status === "processing") {
    return "ç”Ÿæˆä¸­";
  }
  if (status === "completed") {
    return "å·²å®Œæˆ";
  }
  if (status === "failed") {
    return "ç”Ÿæˆå¤±è´¥";
  }
  return status;
}

function comparisonStatusTone(status: string) {
  if (status === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-600";
  }
  if (status === "processing") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function getRequestErrorMessage(requestError: unknown, fallback: string) {
  const detail = axios.isAxiosError(requestError) ? requestError.response?.data?.detail : null;
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String(detail.message);
  }
  return fallback;
}

function createCompareShareDocument(data: AnalysisCompareResponse) {
  const before = data.analysis_a;
  const after = data.analysis_b;
  const actionTitle = normalizeShareSnippet(after.action_subtype || after.skill_category || after.action_type, "æ»‘å†°å¯¹æ¯”å¤ç›˜", 24);
  const skaterLabel = before.skater_name ?? after.skater_name ?? "å°è¿åŠ¨å‘˜";
  const narrative = normalizeShareText(data.ai_narrative, "æœ¬æ¬¡å¯¹æ¯”ç»“æžœå·²ç”Ÿæˆï¼Œå»ºè®®ç»“åˆè¯„åˆ†ã€å…³é”®å¸§å’Œæ•™ç»ƒçŽ°åœºè§‚å¯Ÿç»§ç»­å¤ç›˜ã€‚");
  const improved = data.summary.improved[0];
  const added = data.summary.added[0];
  const bestMetric = data.metric_deltas.find((item) => item.available && typeof item.delta === "number");
  const bestSubscore = data.subscore_deltas.find((item) => typeof item.delta === "number");
  const videoAi = data.video_ai_report;
  const keyframeSummary = data.keyframe_compare
    .map((item) => {
      const beforeText = item.before.timestamp != null ? `${item.before.timestamp.toFixed(2)}s` : "--";
      const afterText = item.after.timestamp != null ? `${item.after.timestamp.toFixed(2)}s` : "--";
      const rhythm = item.relative_delta_seconds != null ? `ï¼ŒèŠ‚å¥ ${signedValue(item.relative_delta_seconds, "s")}` : "";
      return `${item.label}ï¼š${beforeText} â†’ ${afterText}${rhythm}`;
    })
    .join("ï¼›");
  const sections = [
    {
      label: "ä¸»è¦å˜åŒ–",
      title: normalizeShareText(
        improved ? `${improved.category}ï¼š${improved.description}` : null,
        bestSubscore ? `${bestSubscore.label} ${signedValue(bestSubscore.delta, bestSubscore.unit)}` : "ä¸¤æ¬¡åŠ¨ä½œæ•´ä½“å·®å¼‚è¾ƒå°ï¼Œé€‚åˆç»§ç»­è§‚å¯Ÿç¨³å®šæ€§ã€‚",
      ),
      color: "#059669",
      bg: "#ECFDF5",
    },
    {
      label: "ç»§ç»­å…³æ³¨",
      title: normalizeShareText(
        added ? `${added.category}ï¼š${added.description}` : null,
        data.summary.unchanged[0] ? `${data.summary.unchanged[0].category}ï¼š${data.summary.unchanged[0].description}` : "ä¿æŒä½Žå†²å‡»ã€çŸ­æ—¶é—´ã€å¤šé¼“åŠ±çš„è®­ç»ƒèŠ‚å¥ã€‚",
      ),
      color: "#F97316",
      bg: "#FFF7ED",
    },
    {
      label: "é‡åŒ–å‚è€ƒ",
      title: normalizeShareText(
        bestMetric ? `${bestMetric.label} ${signedValue(bestMetric.delta, bestMetric.unit)}ï¼Œ${formatValue(bestMetric.before, bestMetric.unit)} â†’ ${formatValue(bestMetric.after, bestMetric.unit)}` : null,
        `${before.force_score ?? "--"} â†’ ${after.force_score ?? "--"}ï¼Œè¯„åˆ†å˜åŒ– ${data.score_delta >= 0 ? "+" : ""}${data.score_delta}`,
      ),
      color: "#2563EB",
      bg: "#EFF6FF",
    },
    ...(videoAi
      ? [
          {
            label: "è§†é¢‘ AI è§‚å¯Ÿ",
            title: normalizeShareText(videoAi.summary, "è§†é¢‘ AI å®è§‚è§‚å¯Ÿå¯ä½œä¸ºè¯„åˆ†å’Œå…³é”®å¸§ä¹‹å¤–çš„è¾…åŠ©å‚è€ƒã€‚"),
            body: [
              ...videoAi.changes.map((item) => `${item.category}ï¼š${item.description}`),
              videoAi.training_focus ? `è®­ç»ƒé‡ç‚¹ï¼š${videoAi.training_focus}` : "",
            ]
              .filter(Boolean)
              .join("\n"),
            meta: videoAi.caveats.join(" "),
            color: "#0E7490",
            bg: "#ECFEFF",
          },
        ]
      : []),
    ...(keyframeSummary
      ? [
          {
            label: "å…³é”®å¸§",
            title: keyframeSummary,
            color: "#7C3AED",
            bg: "#F5F3FF",
          },
        ]
      : []),
  ];
  return {
    eyebrow: "å†°å®å¯¹æ¯”åˆ†äº«",
    title: `${actionTitle} è¿›æ­¥å¤ç›˜`,
    subtitle: `${skaterLabel} Â· ${formatShortDate(before.created_at)} â†’ ${formatShortDate(after.created_at)}`,
    intro: narrative,
    sections,
    footer: "å¯¹æ¯”ç»“è®ºä»…ä¾›å¤ç›˜å‚è€ƒï¼Œå†°ä¸ŠåŠ¨ä½œè¯·åœ¨æ•™ç»ƒæˆ–å®¶é•¿é™ªåŒä¸‹å®Œæˆ",
    filename: `icebuddy-compare-${after.id.slice(0, 8)}.jpg`,
  };
}

function VideoPane({ title, side, manifest, playerRef }: { title: string; side: CompareVideoSide; manifest: MediaManifest | null; playerRef: React.RefObject<IceMediaPlayerHandle | null> }) {
  return <div className="min-w-0 overflow-hidden rounded-[22px] border border-slate-200 bg-white">
    <div className="flex min-h-[68px] items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
      <div><p className="text-xs uppercase tracking-[0.24em] text-blue-500">{title}</p><p className="mt-1 text-sm text-slate-500">动作窗口 {formatValue(side.action_window_start, "s")} - {formatValue(side.action_window_end, "s")}</p></div>
      {side.is_slow_motion ? <span className="shrink-0 rounded-full bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-600">慢动作 {Math.round(side.source_fps ?? 0)}fps</span> : null}
    </div>
    {side.available && side.video_url ? <IceMediaPlayer ref={playerRef} manifest={manifest} fallbackSrc={side.video_url} /> : <div className="flex aspect-video items-center justify-center bg-slate-950 px-6 text-center text-sm leading-7 text-slate-400">{side.missing_reason ?? "原视频不可用，仍可查看关键帧与量化对比。"}</div>}
  </div>;
}

function SyncedVideoSection({ data }: { data: AnalysisCompareResponse }) {
  const beforeRef = useRef<IceMediaPlayerHandle | null>(null);
  const afterRef = useRef<IceMediaPlayerHandle | null>(null);
  const videoCompare = data.video_compare;
  const [manifests, setManifests] = useState<{ before: MediaManifest | null; after: MediaManifest | null }>({ before: null, after: null });
  const fallbackSide: CompareVideoSide = { analysis_id: "", video_url: null, available: false, missing_reason: null, action_window_start: null, action_window_end: null, action_window_duration: null, sync_start: null, sync_duration: null, is_slow_motion: false, source_fps: null };
  const group = useSynchronizedMediaGroup(beforeRef, afterRef, videoCompare?.before ?? fallbackSide, videoCompare?.after ?? fallbackSide);
  useEffect(() => {
    if (!videoCompare) return;
    let cancelled = false;
    void Promise.all([fetchAnalysisMedia(videoCompare.before.analysis_id), fetchAnalysisMedia(videoCompare.after.analysis_id)])
      .then(([before, after]) => { if (!cancelled) setManifests({ before, after }); })
      .catch(() => { if (!cancelled) setManifests({ before: null, after: null }); });
    return () => { cancelled = true; };
  }, [videoCompare]);
  if (!videoCompare) return null;

  return <ReportCard title="同步回放" eyebrow="Video Sync">
    <div className="grid gap-4 lg:grid-cols-2">
      <VideoPane title="之前" side={videoCompare.before} manifest={manifests.before} playerRef={beforeRef} />
      <VideoPane title="现在" side={videoCompare.after} manifest={manifests.after} playerRef={afterRef} />
    </div>
    <div className="mt-4 rounded-[22px] border border-slate-200 bg-slate-50 p-3 tablet:p-4">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void group.togglePlayback()} className="min-h-[44px] rounded-full bg-blue-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-600">{group.isPlaying ? "暂停" : "同步播放"}</button>
          <button type="button" onClick={() => group.seekRelative(0)} className="pill-link">跳到动作开始</button>
          <span className="rounded-full border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-500">全程静音</span>
        </div>
        <div className="flex w-fit rounded-full border border-slate-200 bg-white p-1">
          {SPEED_OPTIONS.map((option) => <button key={option} type="button" onClick={() => group.setSpeed(option)} className={`min-h-[34px] rounded-full px-3 text-xs font-semibold transition ${group.speed === option ? "bg-blue-500 text-white" : "text-slate-500 hover:bg-slate-100"}`}>{option}x</button>)}
        </div>
      </div>
      {data.keyframe_compare.length ? <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-200 pt-3">{data.keyframe_compare.map((item) => <button key={item.key} type="button" onClick={() => group.seekKeyframe(item)} className="pill-link">{item.label}</button>)}</div> : null}
    </div>
  </ReportCard>;
}

function VideoAiInsightSection({ data }: { data: AnalysisCompareResponse }) {
  const report = data.video_ai_report;
  if (!report) {
    return null;
  }

  const statusLabel = report.status === "completed" ? "å®Œæ•´è§†é¢‘å·²åˆ†æž" : report.status === "partial" ? "éƒ¨åˆ†è§†é¢‘å·²åˆ†æž" : "è§†é¢‘ AI è¾…åŠ©è§‚å¯Ÿ";
  const modelLabel = [report.provider, report.model].filter(Boolean).join(" / ") || "vision æ¨¡åž‹";
  const primaryChange = report.changes[0];

  return (
    <ReportCard title="è§†é¢‘ AI è§‚å¯Ÿ" eyebrow="Full Video">
      <div className="space-y-5">
        <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-900">{statusLabel}</p>
            <p className="mt-1 text-sm text-slate-500">
              {modelLabel} Â· å¹³å‡ç½®ä¿¡åº¦ {formatPercent(report.average_confidence)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
            <span className="rounded-full bg-slate-100 px-3 py-1">ä¹‹å‰ {formatPercent(report.before_confidence)}</span>
            <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-700">çŽ°åœ¨ {formatPercent(report.after_confidence)}</span>
          </div>
        </div>

        <section className="rounded-[24px] border border-cyan-100 bg-cyan-50/70 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">è§†é¢‘çº§å˜åŒ–</h3>
            {primaryChange ? (
              <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${videoAiDirectionTone(primaryChange.direction)}`}>
                {videoAiDirectionLabel(primaryChange.direction)}
              </span>
            ) : null}
          </div>
          <p className="mt-3 text-sm leading-7 text-slate-600">{report.summary}</p>
          {primaryChange ? <p className="mt-3 text-sm leading-7 text-slate-700">{primaryChange.description}</p> : null}
        </section>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {report.observations.map((item) => (
            <article key={item.key} className="min-w-0 rounded-[22px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-semibold text-slate-900">{item.label}</p>
              <div className="mt-3 space-y-3 text-sm leading-6">
                <p className="text-slate-500">
                  <span className="font-medium text-slate-700">ä¹‹å‰ï¼š</span>
                  {item.before || "--"}
                </p>
                <p className="text-slate-500">
                  <span className="font-medium text-blue-700">çŽ°åœ¨ï¼š</span>
                  {item.after || "--"}
                </p>
              </div>
            </article>
          ))}
        </div>

        {report.changes.length > 1 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {report.changes.slice(1).map((item, index) => (
              <article key={`${item.category}-${index}`} className={`rounded-[22px] border p-4 ${videoAiDirectionTone(item.direction)}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold">{item.category}</p>
                  <span className="rounded-full bg-white/70 px-3 py-1 text-xs">{videoAiDirectionLabel(item.direction)}</span>
                </div>
                <p className="mt-3 text-sm leading-7">{item.description}</p>
              </article>
            ))}
          </div>
        ) : null}

        <div className="rounded-[22px] border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm leading-7 text-emerald-800">
          <span className="font-semibold">ä¸‹ä¸€æ¬¡è®­ç»ƒé‡ç‚¹ï¼š</span>
          {report.training_focus}
        </div>

        {report.caveats.length ? (
          <div className="rounded-[22px] border border-amber-100 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-700">
            {report.caveats.join(" ")}
          </div>
        ) : null}
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
          {side.confidence != null ? ` Â· ${(side.confidence * 100).toFixed(0)}%` : ""}
        </p>
      </div>
      <div className="aspect-video bg-slate-950">
        {side.available && side.frame_url ? (
          <img src={side.frame_url} alt={`${title} ${side.frame_id ?? ""}`} className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full items-center justify-center px-4 text-center text-sm leading-6 text-slate-400">
            {side.missing_reason ?? "è¯¥é˜¶æ®µæœªå¯é è¯†åˆ«"}
          </div>
        )}
      </div>
      <div className="space-y-1 px-4 py-3 text-xs text-slate-400">
        <p>{side.frame_id ?? "æ— å…³é”®å¸§"}</p>
        {side.source || side.phase_label || side.selection_reason ? (
          <p>
            {side.source ? `æ¥æºï¼š${side.source}` : ""}
            {side.phase_label ? ` Â· é˜¶æ®µï¼š${side.phase_label}` : ""}
            {side.selection_reason ? ` Â· ${side.selection_reason}` : ""}
          </p>
        ) : null}
        {side.refinement_method ? (
          <p>
            ç²¾ä¿®ï¼š{side.refinement_method}
            {side.refinement_delta_sec != null ? ` Â· ${signedValue(side.refinement_delta_sec, "s")}` : ""}
            {side.pre_refine_timestamp != null ? ` Â· åŽŸ ${side.pre_refine_timestamp.toFixed(2)}s` : ""}
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
    <ReportCard title="å…³é”®å¸§å§¿æ€å¯¹ç…§" eyebrow="Pose Frames">
      <div className="space-y-5">
        {data.keyframe_compare.map((item) => (
          <section key={item.key} className="rounded-[28px] border border-slate-200 bg-slate-50 p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-xl font-semibold text-slate-900">{item.label}</h3>
              <div className="flex flex-wrap items-center gap-2">
                {item.delta_seconds != null ? (
                  <span className={`rounded-full bg-white px-3 py-1 text-xs font-semibold ${trendClass(item.delta_seconds)}`}>
                    Video {signedValue(item.delta_seconds, "s")}
                  </span>
                ) : null}
                {item.relative_delta_seconds != null ? (
                  <span className={`rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold ${trendClass(item.relative_delta_seconds)}`}>
                    Rhythm {signedValue(item.relative_delta_seconds, "s")}
                  </span>
                ) : null}
                <span className="rounded-full bg-cyan-50 px-3 py-1 text-xs uppercase tracking-[0.2em] text-cyan-700">{item.key}</span>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <KeyframeImage side={item.before} title="ä¹‹å‰" />
              <KeyframeImage side={item.after} title="çŽ°åœ¨" />
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
          <Radar name="ä¹‹å‰" dataKey="before" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.18} />
          <Radar name="çŽ°åœ¨" dataKey="after" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.28} />
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
            <span>ä¹‹å‰ {formatValue(item.before, item.unit)}</span>
            <span>çŽ°åœ¨ {formatValue(item.after, item.unit)}</span>
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
    return <p className="text-sm leading-7 text-slate-500">å½“å‰ä¸¤æ¡è®°å½•ç¼ºå°‘å¯ç›´æŽ¥æ¯”è¾ƒçš„ç”Ÿç‰©åŠ›å­¦æŒ‡æ ‡ã€‚</p>;
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
      <ReportCard title="åˆ†é¡¹è¯„åˆ†å˜åŒ–" eyebrow="Subscores">
        <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
          <SubscoreRadar items={data.subscore_deltas} />
          <DeltaBars items={data.subscore_deltas} />
        </div>
      </ReportCard>

      <ReportCard title="ç”Ÿç‰©åŠ›å­¦æŒ‡æ ‡å˜åŒ–" eyebrow="Biomechanics">
        <MetricChart items={data.metric_deltas} />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {data.metric_deltas.map((item) => (
            <article key={item.key} className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm text-slate-500">{item.label}</p>
              <p className={`mt-2 text-2xl font-semibold ${trendClass(item.delta)}`}>{signedValue(item.delta, item.unit)}</p>
              <p className="mt-2 text-xs text-slate-400">
                {formatValue(item.before, item.unit)} â†’ {formatValue(item.after, item.unit)}
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
                {item.before_severity ? <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-500">ä¹‹å‰ {item.before_severity}</span> : null}
                {item.after_severity ? <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-500">çŽ°åœ¨ {item.after_severity}</span> : null}
              </div>
              <p className="mt-3 text-sm leading-7 text-slate-600">{item.description}</p>
            </article>
          ))
        ) : (
          <p className="text-sm text-slate-500">å½“å‰æ²¡æœ‰è¯¥åˆ†ç±»å˜åŒ–ã€‚</p>
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
          <h1 className="mt-3 text-3xl font-semibold text-slate-900 sm:text-4xl">{actionName} è¿›æ­¥å¤ç›˜</h1>
          <div className="mt-4 flex flex-wrap gap-3 text-sm text-slate-500">
            <span>{before.skater_name ?? after.skater_name ?? "å°è¿åŠ¨å‘˜"}</span>
            <span>{formatDate(before.created_at)} â†’ {formatDate(after.created_at)}</span>
            <span>{after.action_type}</span>
          </div>
          {data.ai_narrative ? <p className="mt-5 max-w-4xl text-base leading-8 text-slate-600">{data.ai_narrative}</p> : null}
          {data.quality?.warnings.length ? (
            <div className="mt-4 rounded-[22px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-7 text-amber-700">
              {data.quality.warnings.join(" ")}
            </div>
          ) : null}
          {data.quality?.subtype_mismatch || data.quality?.skill_mismatch ? (
            <div className="mt-3 rounded-[22px] border border-sky-200 bg-sky-50 px-4 py-3 text-sm leading-7 text-sky-700">
              å·²å…è®¸åŒä¸€åŠ¨ä½œå¤§ç±»ä¸‹çš„è·¨å°é¡¹å¯¹æ¯”ï¼›æœ¬é¡µç»“è®ºæ›´é€‚åˆçœ‹é•¿æœŸè¶‹åŠ¿ï¼Œä¸ç”¨äºŽåˆ¤å®šæŸä¸ªç»†é¡¹æŠ€æœ¯ä¼˜åŠ£ã€‚
            </div>
          ) : null}
        </div>
        <div className={`rounded-[28px] border p-5 text-center ${scoreTone(data.score_delta)}`}>
          <p className="text-sm uppercase tracking-[0.24em] opacity-80">è¯„åˆ†å˜åŒ–</p>
          <p className="mt-3 text-5xl font-semibold">
            {data.score_delta >= 0 ? "+" : ""}
            {data.score_delta}
          </p>
          <p className="mt-3 text-sm opacity-80">
            {before.force_score ?? "--"} â†’ {after.force_score ?? "--"}
          </p>
        </div>
      </div>
    </header>
  );
}

export default function ComparePage() {
  const { id_a, id_b, comparison_id } = useParams<{ id_a?: string; id_b?: string; comparison_id?: string }>();
  const navigate = useNavigate();
  const [comparison, setComparison] = useState<AnalysisComparisonDetail | null>(null);
  const [data, setData] = useState<AnalysisCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRetrying, setIsRetrying] = useState(false);
  const [pollVersion, setPollVersion] = useState(0);
  const [isSharing, setIsSharing] = useState(false);
  const [shareImagePreview, setShareImagePreview] = useState<ShareImagePreview[]>([]);

  useEffect(() => {
    if (comparison_id) {
      return;
    }
    if (!id_a || !id_b) {
      setError("æ— æ•ˆçš„å¯¹æ¯”å‚æ•°ã€‚");
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    const createComparison = async () => {
      setIsLoading(true);
      try {
        const created = await createAnalysisComparison(id_a, id_b);
        if (!cancelled) {
          navigate(`/compare/results/${created.id}`, { replace: true });
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(getRequestErrorMessage(requestError, "å¯¹æ¯”ä»»åŠ¡åˆ›å»ºå¤±è´¥ï¼Œè¯·è¿”å›žåŽ†å²è®°å½•é¡µé‡è¯•ã€‚"));
          setIsLoading(false);
        }
      }
    };

    void createComparison();
    return () => {
      cancelled = true;
    };
  }, [comparison_id, id_a, id_b, navigate]);

  useEffect(() => {
    if (!comparison_id) {
      return;
    }

    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      try {
        const detail = await fetchAnalysisComparison(comparison_id);
        if (cancelled) {
          return;
        }
        setComparison(detail);
        setData(detail.result);
        setError(null);
        setIsLoading(false);
        if (detail.status === "pending" || detail.status === "processing") {
          timer = window.setTimeout(load, 3000);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(getRequestErrorMessage(requestError, "å¯¹æ¯”ç»“æžœåŠ è½½å¤±è´¥ï¼Œè¯·è¿”å›žåŽ†å²è®°å½•é¡µé‡è¯•ã€‚"));
          setIsLoading(false);
        }
      }
    };

    setIsLoading(true);
    void load();
    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [comparison_id, pollVersion]);

  const hasContent = useMemo(() => Boolean(data && !error), [data, error]);
  const isWorking = comparison?.status === "pending" || comparison?.status === "processing";
  const canRetry = Boolean(comparison_id && comparison?.status === "failed");

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const handleRetry = async () => {
    if (!comparison_id || !canRetry || isRetrying) {
      return;
    }
    setIsRetrying(true);
    setError(null);
    try {
      const detail = await retryAnalysisComparison(comparison_id);
      setComparison(detail);
      setData(detail.result);
      setPollVersion((current) => current + 1);
      showNotice("å·²é‡æ–°æäº¤å¯¹æ¯”ä»»åŠ¡");
    } catch (requestError) {
      setError(getRequestErrorMessage(requestError, "å¯¹æ¯”ä»»åŠ¡é‡è¯•å¤±è´¥ï¼Œè¯·ç¨åŽå†è¯•ã€‚"));
    } finally {
      setIsRetrying(false);
    }
  };

  const handleShareCompare = async () => {
    if (!data) return;
    setIsSharing(true);
    setError(null);
    try {
      const result = await exportShareDocument(createCompareShareDocument(data));
      setShareImagePreview(result.pages.map((page) => createShareImagePreview(page, false)));
      showNotice("分享图已生成");
    } catch {
      setError("分享图生成失败，请稍后重试。");
    } finally {
      setIsSharing(false);
    }
  };
  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/history" className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
          â† è¿”å›žåŽ†å²è®°å½•
        </Link>
        {data ? (
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void handleShareCompare()}
              disabled={isSharing}
              className="rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSharing ? "ç”Ÿæˆä¸­â€¦" : "åˆ†äº«å¯¹æ¯”å›¾"}
            </button>
            <Link to={`/report/${data.analysis_b.id}`} className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
              æŸ¥çœ‹æœ€æ–°æŠ¥å‘Š
            </Link>
          </div>
        ) : null}
      </div>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}
      {isLoading ? <div className="rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">æ­£åœ¨æ‰“å¼€å¯¹æ¯”å·¥ä½œå°â€¦</div> : null}
      {!isLoading && comparison ? (
        <section className={`rounded-[28px] border px-5 py-4 text-sm ${comparisonStatusTone(comparison.status)}`}>
          <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
            <div>
              <p className="font-semibold">å¯¹æ¯”çŠ¶æ€ï¼š{comparisonStatusLabel(comparison.status)}</p>
              {isWorking ? <p className="mt-1 opacity-80">ä¸¤ä¸ªå®Œæ•´è§†é¢‘æ­£åœ¨åŽå°åˆ†æžï¼Œç»“æžœä¼šè‡ªåŠ¨åˆ·æ–°ã€‚</p> : null}
              {comparison.status === "failed" ? <p className="mt-1 opacity-80">{comparison.error_message || "å¯¹æ¯”ç”Ÿæˆå¤±è´¥ï¼Œè¯·é‡è¯•ã€‚"}</p> : null}
            </div>
            {canRetry ? (
              <button
                type="button"
                onClick={() => void handleRetry()}
                disabled={isRetrying}
                className="w-fit rounded-full bg-white px-4 py-2 text-sm font-semibold text-rose-600 shadow-sm transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isRetrying ? "é‡æ–°æäº¤ä¸­â€¦" : "é‡è¯•ç”Ÿæˆ"}
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      {hasContent && data ? (
        <div className="space-y-6">
          <HeroSummary data={data} />
          <SyncedVideoSection data={data} />
          <VideoAiInsightSection data={data} />
          <MetricsSection data={data} />
          <KeyframeCompareSection data={data} />
          <div className="grid gap-6 lg:grid-cols-3">
            <SummaryGroup title="æ”¹å–„é¡¹" items={data.summary.improved} tone="border border-emerald-200 bg-emerald-50/70" />
            <SummaryGroup title="æ–°å¢žé¡¹" items={data.summary.added} tone="border border-rose-200 bg-rose-50/70" />
            <SummaryGroup title="æœªå˜åŒ–" items={data.summary.unchanged} tone="border border-slate-200 bg-slate-50/80" />
          </div>
        </div>
      ) : null}

      <IslandShareDialog preview={null} previews={shareImagePreview} title="对比分享图" onClose={() => setShareImagePreview([])} />
    </div>
  );
}
