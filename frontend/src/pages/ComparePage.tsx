import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  fetchAnalysisComparison,
  retryAnalysisComparison,
} from "../api/client";
import ReportCard from "../components/ReportCard";
import { parseApiDate } from "../utils/datetime";
import {
  canvasToCompressedBlob,
  copyImageBlobToClipboard,
  createShareImagePreview,
  createShareImageResult,
  drawRoundRect,
  drawWrappedText,
  measureWrappedText,
  normalizeShareText,
  shareImageFile,
  ShareImagePreview,
} from "../utils/shareCanvas";

const ISSUE_STYLES: Record<string, string> = {
  high: "border-rose-400/45 bg-rose-500/10",
  medium: "border-amber-300/45 bg-amber-400/10",
  low: "border-sky-300/40 bg-sky-400/10",
};

const SPEED_OPTIONS = [0.25, 0.5, 1] as const;

type VideoEntry = {
  video: HTMLVideoElement;
  side: CompareVideoSide;
};

function prepareVideoForSync(video: HTMLVideoElement) {
  video.muted = true;
  video.defaultMuted = true;
  video.volume = 0;
  video.playsInline = true;
}

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
    return "改善";
  }
  if (direction === "regressed") {
    return "需关注";
  }
  if (direction === "unchanged") {
    return "稳定";
  }
  return "观察";
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
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function comparisonStatusLabel(status: string) {
  if (status === "pending") {
    return "等待生成";
  }
  if (status === "processing") {
    return "生成中";
  }
  if (status === "completed") {
    return "已完成";
  }
  if (status === "failed") {
    return "生成失败";
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

function waitForVideoMetadata(video: HTMLVideoElement) {
  if (video.readyState >= 1) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => {
    const cleanup = () => {
      video.removeEventListener("loadedmetadata", handleReady);
      video.removeEventListener("error", handleReady);
    };
    const handleReady = () => {
      cleanup();
      resolve();
    };
    video.addEventListener("loadedmetadata", handleReady, { once: true });
    video.addEventListener("error", handleReady, { once: true });
  });
}

function seekVideoTo(video: HTMLVideoElement, value: number) {
  const duration = Number.isFinite(video.duration) ? video.duration : null;
  const clamped = duration ? Math.min(Math.max(0, value), Math.max(0, duration - 0.02)) : Math.max(0, value);
  video.currentTime = clamped;
}

async function createCompareShareImage(data: AnalysisCompareResponse) {
  const canvas = document.createElement("canvas");
  const width = 1080;
  const scale = 1;
  const before = data.analysis_a;
  const after = data.analysis_b;
  const actionTitle = normalizeShareSnippet(after.action_subtype || after.skill_category || after.action_type, "滑冰对比复盘", 24);
  const skaterLabel = before.skater_name ?? after.skater_name ?? "小运动员";
  const narrative = normalizeShareText(data.ai_narrative, "本次对比结果已生成，建议结合评分、关键帧和教练现场观察继续复盘。");
  const videoAiHighlight = normalizeShareText(
    data.video_ai_report?.summary || data.video_ai_report?.changes[0]?.description,
    "视频 AI 宏观观察可作为评分和关键帧之外的辅助参考。",
  );
  const improved = data.summary.improved[0];
  const added = data.summary.added[0];
  const bestMetric = data.metric_deltas.find((item) => item.available && typeof item.delta === "number");
  const bestSubscore = data.subscore_deltas.find((item) => typeof item.delta === "number");
  const sections = [
    {
      label: "主要变化",
      title: normalizeShareText(
        improved ? `${improved.category}：${improved.description}` : null,
        bestSubscore ? `${bestSubscore.label} ${signedValue(bestSubscore.delta, bestSubscore.unit)}` : "两次动作整体差异较小，适合继续观察稳定性。",
      ),
      color: "#059669",
      bg: "#ECFDF5",
    },
    {
      label: "继续关注",
      title: normalizeShareText(
        added ? `${added.category}：${added.description}` : null,
        data.summary.unchanged[0] ? `${data.summary.unchanged[0].category}：${data.summary.unchanged[0].description}` : "保持低冲击、短时间、多鼓励的训练节奏。",
      ),
      color: "#F97316",
      bg: "#FFF7ED",
    },
    {
      label: "量化参考",
      title: normalizeShareText(
        bestMetric ? `${bestMetric.label} ${signedValue(bestMetric.delta, bestMetric.unit)}，${formatValue(bestMetric.before, bestMetric.unit)} → ${formatValue(bestMetric.after, bestMetric.unit)}` : null,
        `${before.force_score ?? "--"} → ${after.force_score ?? "--"}，评分变化 ${data.score_delta >= 0 ? "+" : ""}${data.score_delta}`,
      ),
      color: "#2563EB",
      bg: "#EFF6FF",
    },
    ...(data.video_ai_report
      ? [
          {
            label: "视频 AI 观察",
            title: videoAiHighlight,
            color: "#0E7490",
            bg: "#ECFEFF",
          },
        ]
      : []),
  ];

  const measureCanvas = document.createElement("canvas");
  const measureCtx = measureCanvas.getContext("2d");
  if (!measureCtx) {
    throw new Error("share_image_canvas_failed");
  }
  const contentWidth = 856;
  const textWidth = 760;
  measureCtx.font = "500 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const narrativeHeight = measureWrappedText(measureCtx, narrative, contentWidth, 46, 5);
  measureCtx.font = "700 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const sectionHeights = sections.map((section) => Math.max(152, 88 + measureWrappedText(measureCtx, section.title, textWidth, 40, 3) + 34));
  const height = Math.min(
    6000,
    Math.max(1080, 64 + 330 + 70 + narrativeHeight + 70 + sectionHeights.reduce((sum, item) => sum + item + 32, 0) + 140),
  );
  canvas.width = width * scale;
  canvas.height = height * scale;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("share_image_canvas_failed");
  }
  ctx.scale(scale, scale);

  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#F8FBFF");
  gradient.addColorStop(0.54, "#EEF7F4");
  gradient.addColorStop(1, "#FFF7ED");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "rgba(255,255,255,0.88)";
  drawRoundRect(ctx, 64, 64, width - 128, height - 128, 48);
  ctx.fill();
  ctx.strokeStyle = "rgba(148,163,184,0.32)";
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.fillStyle = "#2563EB";
  ctx.font = "700 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("冰宝对比分享", 112, 142);

  ctx.fillStyle = "#0F172A";
  ctx.font = "800 58px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, `${actionTitle} 进步复盘`, 112, 230, 560, 66, 2);

  ctx.fillStyle = "#64748B";
  ctx.font = "500 28px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText(`${skaterLabel} · ${formatShortDate(before.created_at)} → ${formatShortDate(after.created_at)}`, 112, 352);

  ctx.fillStyle = data.score_delta >= 0 ? "#DCFCE7" : "#FFE4E6";
  drawRoundRect(ctx, 710, 142, 220, 220, 110);
  ctx.fill();
  ctx.strokeStyle = data.score_delta >= 0 ? "#86EFAC" : "#FDA4AF";
  ctx.lineWidth = 5;
  ctx.stroke();
  ctx.fillStyle = data.score_delta >= 0 ? "#047857" : "#E11D48";
  ctx.font = "800 72px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(`${data.score_delta >= 0 ? "+" : ""}${data.score_delta}`, 820, 248);
  ctx.font = "700 26px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("Score Δ", 820, 292);
  ctx.fillStyle = "#64748B";
  ctx.font = "600 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText(`${before.force_score ?? "--"} → ${after.force_score ?? "--"}`, 820, 326);
  ctx.textAlign = "start";

  ctx.fillStyle = "#334155";
  ctx.font = "500 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const narrativeUsedHeight = drawWrappedText(ctx, narrative, 112, 460, contentWidth, 46, 5);

  let y = 460 + narrativeUsedHeight + 70;
  sections.forEach((section, index) => {
    ctx.fillStyle = section.bg;
    const blockHeight = sectionHeights[index];
    drawRoundRect(ctx, 112, y, contentWidth, blockHeight, 28);
    ctx.fill();
    ctx.fillStyle = section.color;
    ctx.font = "800 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.fillText(section.label, 152, y + 48);
    ctx.fillStyle = "#0F172A";
    ctx.font = "700 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    drawWrappedText(ctx, section.title, 152, y + 94, textWidth, 40, 3);
    y += blockHeight + 32;
  });

  ctx.strokeStyle = "rgba(148,163,184,0.34)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(112, y + 26);
  ctx.lineTo(968, y + 26);
  ctx.stroke();

  ctx.fillStyle = "#475569";
  ctx.font = "600 28px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("由冰宝（IceBuddy）生成", 112, y + 86);
  ctx.fillStyle = "#94A3B8";
  ctx.font = "500 22px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("对比结论仅供复盘参考，冰上动作请在教练或家长陪同下完成", 112, y + 126);

  const blob = await canvasToCompressedBlob(canvas, { type: "image/jpeg", quality: 0.82, maxBytes: 1_500_000 });
  const filename = `icebuddy-compare-${after.id.slice(0, 8)}.jpg`;
  return createShareImageResult(blob, filename);
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
    <div className="min-w-0 overflow-hidden rounded-[22px] border border-slate-200 bg-white">
      <div className="flex min-h-[68px] items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-blue-500">{title}</p>
          <p className="mt-1 text-sm text-slate-500">
            动作窗口 {formatValue(side.action_window_start, "s")} - {formatValue(side.action_window_end, "s")}
          </p>
        </div>
        {side.is_slow_motion ? (
          <span className="shrink-0 rounded-full bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-600">
            慢动作 {Math.round(side.source_fps ?? 0)}fps
          </span>
        ) : null}
      </div>
      <div className="aspect-video bg-slate-950">
        {side.available && side.video_url ? (
          <video
            ref={videoRef}
            src={side.video_url}
            preload="metadata"
            muted
            playsInline
            disablePictureInPicture
            controlsList="nodownload noplaybackrate"
            className="h-full w-full object-contain"
          />
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
  const suppressMediaEventsRef = useRef(false);
  const isPlayingRef = useRef(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEED_OPTIONS)[number]>(0.5);
  const videoCompare = data.video_compare;

  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

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

  const getPlayableEntries = useCallback((): VideoEntry[] => {
    if (!videoCompare) {
      return [];
    }
    const entries = [
      { video: beforeRef.current, side: videoCompare.before },
      { video: afterRef.current, side: videoCompare.after },
    ].filter((entry): entry is VideoEntry => Boolean(entry.video && entry.side.available && entry.side.video_url));
    entries.forEach(({ video }) => prepareVideoForSync(video));
    return entries;
  }, [videoCompare]);

  useEffect(() => {
    getPlayableEntries();
  }, [getPlayableEntries]);

  const pauseEntries = useCallback((entries: VideoEntry[]) => {
    suppressMediaEventsRef.current = true;
    entries.forEach(({ video }) => video.pause());
    setIsPlaying(false);
    window.setTimeout(() => {
      suppressMediaEventsRef.current = false;
    }, 0);
  }, []);

  const seekBoth = useCallback(
    async (relativePosition: number) => {
      if (!videoCompare) {
        return;
      }
      const entries = getPlayableEntries();
      suppressMediaEventsRef.current = true;
      await Promise.all(entries.map(({ video }) => waitForVideoMetadata(video)));
      entries.forEach(({ video, side }) => {
        const { start, duration } = getActionWindow(side);
        if (duration) {
          seekVideoTo(video, start + relativePosition * duration);
        } else {
          seekVideoTo(video, start + relativePosition);
        }
      });
      window.setTimeout(() => {
        suppressMediaEventsRef.current = false;
      }, 0);
    },
    [videoCompare, getPlayableEntries, getActionWindow],
  );

  const seekKeyframe = useCallback(
    async (pair: CompareKeyframePair) => {
      if (!videoCompare) {
        return;
      }
      const entries = [
        { video: beforeRef.current as HTMLVideoElement | null, side: videoCompare.before, timestamp: pair.before.timestamp },
        { video: afterRef.current as HTMLVideoElement | null, side: videoCompare.after, timestamp: pair.after.timestamp },
      ].filter((entry): entry is VideoEntry & { timestamp: number | null } => Boolean(entry.video && entry.side.available && entry.side.video_url));
      suppressMediaEventsRef.current = true;
      await Promise.all(entries.map(({ video }) => waitForVideoMetadata(video)));
      entries.forEach(({ video, side, timestamp }) => {
        if (timestamp != null) {
          seekVideoTo(video, timestamp);
        } else {
          const { start } = getActionWindow(side);
          seekVideoTo(video, start);
        }
      });
      window.setTimeout(() => {
        suppressMediaEventsRef.current = false;
      }, 0);
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

      getPlayableEntries().forEach(({ video, side }) => {
        prepareVideoForSync(video);
        const duration = getActionWindow(side).duration;
        video.playbackRate = duration ? baseSpeed * (duration / maxDuration) : baseSpeed;
      });
    },
    [videoCompare, getActionWindow, getPlayableEntries],
  );

  const setPlaybackRate = useCallback(
    (nextSpeed: (typeof SPEED_OPTIONS)[number]) => {
      setSpeed(nextSpeed);
      applyProportionalRates(nextSpeed);
    },
    [applyProportionalRates],
  );

  const togglePlayback = useCallback(async () => {
    const entries = getPlayableEntries();
    if (!entries.length) {
      return;
    }
    if (isPlaying) {
      pauseEntries(entries);
      return;
    }
    suppressMediaEventsRef.current = true;
    await Promise.all(entries.map(({ video }) => waitForVideoMetadata(video)));
    applyProportionalRates(speed);
    entries.forEach(({ video, side }) => {
      prepareVideoForSync(video);
      const { start } = getActionWindow(side);
      seekVideoTo(video, start);
    });
    const results = await Promise.allSettled(entries.map(({ video }) => video.play()));
    suppressMediaEventsRef.current = false;
    const allStarted = results.every((result) => result.status === "fulfilled");
    if (!allStarted) {
      pauseEntries(entries);
      setIsPlaying(false);
      return;
    }
    setIsPlaying(true);
  }, [applyProportionalRates, getActionWindow, getPlayableEntries, isPlaying, pauseEntries, speed]);

  useEffect(() => {
    const entries = getPlayableEntries();
    const handleEnded = () => {
      pauseEntries(entries);
    };
    const handlePause = () => {
      if (suppressMediaEventsRef.current) {
        return;
      }
      if (isPlayingRef.current) {
        pauseEntries(entries);
        return;
      }
      setIsPlaying(entries.every(({ video }) => !video.paused && !video.ended));
    };
    entries.forEach(({ video }) => {
      video.addEventListener("ended", handleEnded);
      video.addEventListener("pause", handlePause);
    });
    return () => {
      entries.forEach(({ video }) => {
        video.removeEventListener("ended", handleEnded);
        video.removeEventListener("pause", handlePause);
      });
    };
  }, [getPlayableEntries, pauseEntries, speed]);

  useEffect(() => {
    applyProportionalRates(speed);
  }, [applyProportionalRates, speed]);

  if (!videoCompare) {
    return null;
  }

  return (
    <ReportCard title="同步回放" eyebrow="Video Sync">
      <div className="grid gap-4 lg:grid-cols-2">
        <VideoPane title="之前" side={videoCompare.before} videoRef={beforeRef} />
        <VideoPane title="现在" side={videoCompare.after} videoRef={afterRef} />
      </div>

      <div className="mt-4 rounded-[22px] border border-slate-200 bg-slate-50 p-3 tablet:p-4">
        <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void togglePlayback()}
              className="min-h-[44px] rounded-full bg-blue-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-600"
            >
              {isPlaying ? "暂停" : "同步播放"}
            </button>
            <button type="button" onClick={() => void seekBoth(0)} className="pill-link">
              跳到动作开始
            </button>
            <span className="rounded-full border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-500">全程静音</span>
          </div>

          <div className="flex w-fit rounded-full border border-slate-200 bg-white p-1">
            {SPEED_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setPlaybackRate(option)}
                className={`min-h-[34px] rounded-full px-3 text-xs font-semibold transition ${
                  speed === option ? "bg-blue-500 text-white" : "text-slate-500 hover:bg-slate-100"
                }`}
              >
                {option}x
              </button>
            ))}
          </div>
        </div>

        {data.keyframe_compare.length ? (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-200 pt-3">
            {data.keyframe_compare.map((item) => {
              return (
                <button key={item.key} type="button" onClick={() => void seekKeyframe(item)} className="pill-link">
                  {item.label}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </ReportCard>
  );
}

function VideoAiInsightSection({ data }: { data: AnalysisCompareResponse }) {
  const report = data.video_ai_report;
  if (!report) {
    return null;
  }

  const statusLabel = report.status === "completed" ? "完整视频已分析" : report.status === "partial" ? "部分视频已分析" : "视频 AI 辅助观察";
  const modelLabel = [report.provider, report.model].filter(Boolean).join(" / ") || "vision 模型";
  const primaryChange = report.changes[0];

  return (
    <ReportCard title="视频 AI 观察" eyebrow="Full Video">
      <div className="space-y-5">
        <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-900">{statusLabel}</p>
            <p className="mt-1 text-sm text-slate-500">
              {modelLabel} · 平均置信度 {formatPercent(report.average_confidence)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold text-slate-500">
            <span className="rounded-full bg-slate-100 px-3 py-1">之前 {formatPercent(report.before_confidence)}</span>
            <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-700">现在 {formatPercent(report.after_confidence)}</span>
          </div>
        </div>

        <section className="rounded-[24px] border border-cyan-100 bg-cyan-50/70 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">视频级变化</h3>
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
                  <span className="font-medium text-slate-700">之前：</span>
                  {item.before || "--"}
                </p>
                <p className="text-slate-500">
                  <span className="font-medium text-blue-700">现在：</span>
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
          <span className="font-semibold">下一次训练重点：</span>
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
          {data.quality?.subtype_mismatch || data.quality?.skill_mismatch ? (
            <div className="mt-3 rounded-[22px] border border-sky-200 bg-sky-50 px-4 py-3 text-sm leading-7 text-sky-700">
              已允许同一动作大类下的跨小项对比；本页结论更适合看长期趋势，不用于判定某个细项技术优劣。
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
  const [shareImagePreview, setShareImagePreview] = useState<ShareImagePreview | null>(null);

  useEffect(() => {
    if (comparison_id) {
      return;
    }
    if (!id_a || !id_b) {
      setError("无效的对比参数。");
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
          setError(getRequestErrorMessage(requestError, "对比任务创建失败，请返回历史记录页重试。"));
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
          setError(getRequestErrorMessage(requestError, "对比结果加载失败，请返回历史记录页重试。"));
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

  useEffect(() => {
    return () => {
      if (shareImagePreview?.url) {
        URL.revokeObjectURL(shareImagePreview.url);
      }
    };
  }, [shareImagePreview?.url]);

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
      showNotice("已重新提交对比任务");
    } catch (requestError) {
      setError(getRequestErrorMessage(requestError, "对比任务重试失败，请稍后再试。"));
    } finally {
      setIsRetrying(false);
    }
  };

  const handleShareCompare = async () => {
    if (!data) {
      return;
    }
    setIsSharing(true);
    setError(null);
    try {
      const result = await createCompareShareImage(data);
      const copiedToClipboard = await copyImageBlobToClipboard(result.blob);
      setShareImagePreview((current) => {
        if (current?.url) {
          URL.revokeObjectURL(current.url);
        }
        return createShareImagePreview(result, copiedToClipboard);
      });
      showNotice(copiedToClipboard ? "分享图已生成并复制" : "分享图已生成");
    } catch {
      setError("分享图生成失败，请稍后重试。");
    } finally {
      setIsSharing(false);
    }
  };

  const handleCopyShareImage = async () => {
    if (!shareImagePreview) {
      return;
    }
    const copied = await copyImageBlobToClipboard(shareImagePreview.blob);
    if (!copied) {
      setError("当前浏览器不能直接复制图片，请先下载后分享。");
      return;
    }
    setShareImagePreview((current) => (current ? { ...current, copiedToClipboard: true } : current));
    showNotice("分享图已复制");
  };

  const handleNativeShareImage = async () => {
    if (!shareImagePreview) {
      return;
    }
    const shared = await shareImageFile(shareImagePreview.blob, shareImagePreview.filename, "IceBuddy 对比分享图");
    if (!shared) {
      setError("当前浏览器不支持直接系统分享图片，请先下载后保存或发送。");
    }
  };

  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/history" className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
          ← 返回历史记录
        </Link>
        {data ? (
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void handleShareCompare()}
              disabled={isSharing}
              className="rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSharing ? "生成中…" : "分享对比图"}
            </button>
            <Link to={`/report/${data.analysis_b.id}`} className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
              查看最新报告
            </Link>
          </div>
        ) : null}
      </div>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}
      {isLoading ? <div className="rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">正在打开对比工作台…</div> : null}
      {!isLoading && comparison ? (
        <section className={`rounded-[28px] border px-5 py-4 text-sm ${comparisonStatusTone(comparison.status)}`}>
          <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
            <div>
              <p className="font-semibold">对比状态：{comparisonStatusLabel(comparison.status)}</p>
              {isWorking ? <p className="mt-1 opacity-80">两个完整视频正在后台分析，结果会自动刷新。</p> : null}
              {comparison.status === "failed" ? <p className="mt-1 opacity-80">{comparison.error_message || "对比生成失败，请重试。"}</p> : null}
            </div>
            {canRetry ? (
              <button
                type="button"
                onClick={() => void handleRetry()}
                disabled={isRetrying}
                className="w-fit rounded-full bg-white px-4 py-2 text-sm font-semibold text-rose-600 shadow-sm transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isRetrying ? "重新提交中…" : "重试生成"}
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
            <SummaryGroup title="改善项" items={data.summary.improved} tone="border border-emerald-200 bg-emerald-50/70" />
            <SummaryGroup title="新增项" items={data.summary.added} tone="border border-rose-200 bg-rose-50/70" />
            <SummaryGroup title="未变化" items={data.summary.unchanged} tone="border border-slate-200 bg-slate-50/80" />
          </div>
        </div>
      ) : null}

      {shareImagePreview ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/36 px-4 py-6 backdrop-blur-sm">
          <section className="app-card max-h-[92vh] w-full max-w-3xl overflow-y-auto p-5 tablet:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Share Image</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">对比分享图</h2>
                <p className="mt-2 text-sm text-slate-500">
                  {shareImagePreview.copiedToClipboard
                    ? "已复制到剪贴板，也可以用系统分享保存或发送。"
                    : shareImagePreview.canNativeShare
                      ? "可用系统分享保存到照片或发送给别人。"
                      : "当前浏览器未开放图片分享能力，可下载后保存。"}
                </p>
                <p className="mt-1 text-xs text-slate-400">{Math.max(1, Math.round(shareImagePreview.sizeBytes / 1024))} KB · JPEG</p>
              </div>
              <button
                type="button"
                onClick={() => setShareImagePreview(null)}
                className="min-h-[40px] rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
              >
                关闭
              </button>
            </div>

            <div className="mt-5 overflow-hidden rounded-[28px] border border-slate-200 bg-slate-100">
              <img src={shareImagePreview.url} alt="对比分享图预览" className="mx-auto block max-h-[62vh] w-auto max-w-full object-contain" />
            </div>

            <div className="mt-5 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => void handleNativeShareImage()}
                disabled={!shareImagePreview.canNativeShare}
                className="min-h-[44px] rounded-full border border-emerald-200 bg-emerald-50 px-5 py-3 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                系统分享/保存
              </button>
              <button
                type="button"
                onClick={() => void handleCopyShareImage()}
                className="min-h-[44px] rounded-full border border-blue-200 bg-blue-50 px-5 py-3 text-sm font-semibold text-blue-700 transition hover:bg-blue-100"
              >
                复制图片
              </button>
              <a
                href={shareImagePreview.url}
                download={shareImagePreview.filename}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
              >
                下载图片
              </a>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
