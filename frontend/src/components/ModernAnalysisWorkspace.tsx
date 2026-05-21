import { MouseEvent, RefObject, useEffect, useMemo, useRef, useState } from "react";

import { AnalysisDetail, PoseFrame, PoseKeypoint, PoseResponse, SelectedSemanticFrame } from "../api/client";
import PoseViewer from "./PoseViewer";

type ModernAnalysisWorkspaceProps = {
  analysis: AnalysisDetail;
  pose: PoseResponse | null;
  selectedFrameId: string | null;
  onFrameChange: (frameId: string) => void;
};

type TimelineMarker = {
  key: string;
  label: string;
  timestamp: number;
  color: string;
};

type HoverPoint = {
  point: PoseKeypoint;
  x: number;
  y: number;
};

const MARKER_COLORS = ["#2563EB", "#7C3AED", "#22C55E", "#F59E0B", "#EF4444"];
const ACTION_SEGMENT_COLORS = ["#2563EB", "#22C55E", "#F59E0B", "#7C3AED", "#06B6D4"];

function metricUnavailableText() {
  return "暂无数据";
}

function frameStem(frameName: string) {
  return frameName.replace(/\.jpg$/i, "");
}

function timestampForFrame(pose: PoseResponse, frame: PoseFrame, index: number) {
  const direct = pose.frame_timestamps?.[frame.frame] ?? pose.frame_timestamps?.[frameStem(frame.frame)];
  if (typeof direct === "number" && Number.isFinite(direct)) {
    return direct;
  }
  const fps = typeof pose.effective_fps === "number" && pose.effective_fps > 0 ? pose.effective_fps : 5;
  return index / fps;
}

function drawSkeleton(
  canvas: HTMLCanvasElement,
  frame: PoseFrame | undefined,
  connections: number[][],
  hoverPoint: PoseKeypoint | null,
) {
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const width = canvas.clientWidth || 960;
  const height = canvas.clientHeight || Math.round(width * 0.5625);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 3);
  const pixelWidth = Math.round(width * pixelRatio);
  const pixelHeight = Math.round(height * pixelRatio);

  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }

  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  if (!frame?.keypoints?.length) {
    return;
  }

  const points = new Map(frame.keypoints.map((point) => [point.id, point]));
  context.lineCap = "round";
  context.lineJoin = "round";

  for (const [from, to] of connections) {
    const a = points.get(from);
    const b = points.get(to);
    if (!a || !b || a.visibility < 0.35 || b.visibility < 0.35) {
      continue;
    }
    context.strokeStyle = "rgba(34,211,238,0.82)";
    context.lineWidth = 2.25;
    context.shadowColor = "rgba(34,211,238,0.34)";
    context.shadowBlur = 6;
    context.beginPath();
    context.moveTo(a.x * width, a.y * height);
    context.lineTo(b.x * width, b.y * height);
    context.stroke();
    context.shadowBlur = 0;
  }

  for (const point of frame.keypoints) {
    if (point.visibility < 0.35) {
      continue;
    }
    const isHovered = hoverPoint?.id === point.id;
    context.fillStyle = isHovered ? "#F8FAFC" : "#34D399";
    context.strokeStyle = isHovered ? "#22D3EE" : "rgba(15,23,42,0.88)";
    context.lineWidth = isHovered ? 2.5 : 1.25;
    context.beginPath();
    context.arc(point.x * width, point.y * height, isHovered ? 5 : 2.8, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  }
}

function nearestFrameIndex(timestamps: number[], currentTime: number) {
  if (!timestamps.length) {
    return 0;
  }

  let bestIndex = 0;
  let bestDelta = Math.abs(timestamps[0] - currentTime);
  for (let index = 1; index < timestamps.length; index += 1) {
    const delta = Math.abs(timestamps[index] - currentTime);
    if (delta < bestDelta) {
      bestDelta = delta;
      bestIndex = index;
    }
  }
  return bestIndex;
}

function useFrameTimestamps(pose: PoseResponse | null) {
  return useMemo(() => {
    if (!pose?.frames?.length) {
      return [];
    }
    return pose.frames.map((frame, index) => timestampForFrame(pose, frame, index));
  }, [pose]);
}

function SkeletonVideoPlayer({
  analysisId,
  pose,
  selectedFrameId,
  onFrameChange,
  timelineMarkers,
  videoRef,
}: {
  analysisId: string;
  pose: PoseResponse | null;
  selectedFrameId: string | null;
  onFrameChange: (frameId: string) => void;
  timelineMarkers: TimelineMarker[];
  videoRef: RefObject<HTMLVideoElement>;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const [videoFailed, setVideoFailed] = useState(false);
  const [activeFrameIndex, setActiveFrameIndex] = useState(0);
  const [hoverPoint, setHoverPoint] = useState<HoverPoint | null>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const frameTimestamps = useFrameTimestamps(pose);
  const activeFrame = pose?.frames[activeFrameIndex];

  useEffect(() => {
    if (!pose || !selectedFrameId) {
      return;
    }
    const index = pose.frames.findIndex((frame) => frameStem(frame.frame) === selectedFrameId || frame.frame === selectedFrameId);
    if (index >= 0) {
      setActiveFrameIndex(index);
      const timestamp = frameTimestamps[index];
      if (videoRef.current && typeof timestamp === "number" && Number.isFinite(timestamp)) {
        videoRef.current.currentTime = timestamp;
      }
    }
  }, [frameTimestamps, pose, selectedFrameId, videoRef]);

  useEffect(() => {
    const render = () => {
      const video = videoRef.current;
      if (video && pose?.frames.length) {
        const nextIndex = nearestFrameIndex(frameTimestamps, video.currentTime);
        setActiveFrameIndex((current) => {
          if (current === nextIndex) {
            return current;
          }
          const nextFrame = pose.frames[nextIndex];
          if (nextFrame) {
            onFrameChange(frameStem(nextFrame.frame));
          }
          return nextIndex;
        });
      }

      if (canvasRef.current) {
        drawSkeleton(canvasRef.current, pose?.frames[activeFrameIndex], pose?.connections ?? [], hoverPoint?.point ?? null);
      }
      animationRef.current = window.requestAnimationFrame(render);
    };

    animationRef.current = window.requestAnimationFrame(render);
    return () => {
      if (animationRef.current) {
        window.cancelAnimationFrame(animationRef.current);
      }
    };
  }, [activeFrameIndex, frameTimestamps, hoverPoint, onFrameChange, pose, videoRef]);

  useEffect(() => {
    const redraw = () => {
      if (canvasRef.current) {
        drawSkeleton(canvasRef.current, activeFrame, pose?.connections ?? [], hoverPoint?.point ?? null);
      }
    };
    redraw();
    window.addEventListener("resize", redraw);
    return () => window.removeEventListener("resize", redraw);
  }, [activeFrame, hoverPoint, pose?.connections]);

  const handlePointerMove = (event: MouseEvent<HTMLCanvasElement>) => {
    if (!canvasRef.current || !activeFrame?.keypoints?.length) {
      setHoverPoint(null);
      return;
    }
    const rect = canvasRef.current.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const nearest = activeFrame.keypoints.reduce<{ point: PoseKeypoint; distance: number } | null>((best, point) => {
      if (point.visibility < 0.35) {
        return best;
      }
      const px = point.x * rect.width;
      const py = point.y * rect.height;
      const distance = Math.hypot(px - x, py - y);
      if (!best || distance < best.distance) {
        return { point, distance };
      }
      return best;
    }, null);

    if (nearest && nearest.distance <= 18) {
      setHoverPoint({ point: nearest.point, x: x + 14, y: y + 14 });
      return;
    }
    setHoverPoint(null);
  };

  if (videoFailed && pose?.frames?.length) {
    return (
      <div className="rounded-lg border border-white/10 bg-slate-950/60 p-3">
        <PoseViewer pose={pose} activeFrameId={selectedFrameId} onFrameChange={onFrameChange} />
      </div>
    );
  }

  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-white/10 bg-[#070B12] shadow-[0_28px_90px_rgba(2,6,23,0.42)]">
      <div className="flex h-10 items-center justify-between border-b border-white/10 bg-[#0C1422] px-3 tablet:px-4">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-cyan-300 shadow-[0_0_14px_rgba(103,232,249,0.85)]" />
          <span className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-200">视频分析</span>
        </div>
        <span className="hidden rounded-md border border-white/10 bg-white/6 px-2 py-1 text-[11px] text-slate-400 tablet:inline">
          {pose?.frames?.length ? `${pose.frames.length} 帧姿态` : "等待姿态数据"}
        </span>
      </div>
      <div className="relative aspect-video">
        <video
          ref={videoRef}
          src={`/api/analysis/${analysisId}/video`}
          playsInline
          preload="metadata"
          className="h-full w-full bg-black object-contain"
          onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || 0)}
          onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onError={() => setVideoFailed(true)}
        />
        <canvas
          ref={canvasRef}
          className="absolute inset-0 h-full w-full"
          onMouseMove={handlePointerMove}
          onMouseLeave={() => setHoverPoint(null)}
        />
        {hoverPoint ? (
          <div
            className="pointer-events-none absolute z-10 rounded-md border border-slate-700 bg-slate-950/92 px-3 py-2 text-xs text-slate-100 shadow-lg"
            style={{ left: hoverPoint.x, top: hoverPoint.y }}
          >
            <p className="font-semibold">{hoverPoint.point.name || `关键点 ${hoverPoint.point.id}`}</p>
            <p className="mt-1 text-slate-300">
              x {hoverPoint.point.x.toFixed(3)} / y {hoverPoint.point.y.toFixed(3)} / z {hoverPoint.point.z.toFixed(3)}
            </p>
          </div>
        ) : null}
      </div>

      <div className="grid gap-3 border-t border-white/10 bg-[#0C1422] px-3 py-3 tablet:grid-cols-[auto_minmax(0,1fr)_auto] tablet:items-center tablet:px-4">
        <button
          type="button"
          onClick={() => {
            const video = videoRef.current;
            if (!video) {
              return;
            }
            if (video.paused) {
              void video.play().catch(() => undefined);
            } else {
              video.pause();
            }
          }}
          className="min-h-10 w-full rounded-md bg-cyan-400/18 px-4 text-sm font-semibold text-cyan-50 ring-1 ring-cyan-300/20 transition hover:bg-cyan-400/24 tablet:w-auto"
        >
          {isPlaying ? "暂停" : "播放"}
        </button>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(currentTime, duration || currentTime)}
          onChange={(event) => {
            const nextTime = Number(event.target.value);
            setCurrentTime(nextTime);
            if (videoRef.current) {
              videoRef.current.currentTime = nextTime;
            }
          }}
          className="min-w-0 w-full accent-cyan-300"
          aria-label="视频播放进度"
        />
        <span className="text-left text-sm font-medium text-slate-300 tablet:min-w-[104px] tablet:text-right">
          {currentTime.toFixed(2)}s / {duration ? duration.toFixed(2) : "--"}s
        </span>
      </div>

      <ActionTimeline markers={timelineMarkers} duration={duration || null} onSeek={(time) => {
        if (videoRef.current) {
          videoRef.current.currentTime = time;
          setCurrentTime(time);
          void videoRef.current.play().catch(() => undefined);
        }
      }} />
    </div>
  );
}

function formatMetric(value: number | null | undefined, unit: string, digits = 1) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return { value: metricUnavailableText(), unit: "" };
  }
  return { value: value.toFixed(digits), unit };
}

function PerformanceMetrics({ analysis }: { analysis: AnalysisDetail }) {
  const metrics = analysis.bio_data?.jump_metrics;
  const landingImpact =
    typeof analysis.report?.subscores?.landing_absorption === "number"
      ? { value: Math.round(analysis.report.subscores.landing_absorption).toString(), unit: "/100" }
      : { value: metricUnavailableText(), unit: "" };
  const items = [
    { label: "跳跃高度", ...formatMetric(metrics?.estimated_height_cm, "cm", 1), accent: "#38BDF8", gradient: "from-sky-400/16 to-blue-500/8" },
    { label: "滞空时间", ...formatMetric(metrics?.air_time_seconds, "s", 2), accent: "#34D399", gradient: "from-emerald-400/16 to-teal-500/8" },
    {
      label: "旋转速度",
      ...formatMetric(typeof metrics?.rotation_rps === "number" ? metrics.rotation_rps * 60 : null, "rpm", 0),
      accent: "#A78BFA",
      gradient: "from-violet-400/16 to-fuchsia-500/8",
    },
    { label: "落冰稳定性", ...landingImpact, accent: "#F59E0B", gradient: "from-amber-400/16 to-orange-500/8" },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 ipad:grid-cols-4 web:grid-cols-1">
      {items.map((item) => (
        <article key={item.label} className={`min-w-0 rounded-lg border border-white/10 bg-gradient-to-br ${item.gradient} bg-slate-900/70 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]`}>
          <div className="flex items-center justify-between gap-3">
            <p className="min-w-0 text-sm font-medium leading-5 text-slate-300">{item.label}</p>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full shadow-[0_0_16px_currentColor]" style={{ backgroundColor: item.accent, color: item.accent }} />
          </div>
          <div className="mt-4 flex min-w-0 items-end gap-2">
            <span
              className={`min-w-0 max-w-full truncate font-semibold leading-none text-white ${
                item.value === metricUnavailableText() ? "text-[clamp(1.25rem,4.4vw,1.75rem)]" : "text-3xl"
              }`}
              title={item.value}
            >
              {item.value}
            </span>
            {item.unit ? <span className="pb-1 text-sm font-medium text-slate-400">{item.unit}</span> : null}
          </div>
          <svg viewBox="0 0 120 28" className="mt-4 h-7 w-full text-current opacity-80" style={{ color: item.accent }} aria-hidden="true">
            <path d="M2 22 C14 19 18 10 28 15 C38 20 42 7 53 11 C63 15 67 4 78 8 C90 12 95 20 106 11 C112 6 116 8 118 5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M2 22 C14 19 18 10 28 15 C38 20 42 7 53 11 C63 15 67 4 78 8 C90 12 95 20 106 11 C112 6 116 8 118 5 L118 28 L2 28 Z" fill="currentColor" opacity="0.08" />
          </svg>
        </article>
      ))}
    </div>
  );
}

function labelForSemanticFrame(frame: SelectedSemanticFrame, index: number) {
  if (frame.phase_label) {
    return frame.phase_label;
  }
  if (frame.phase_code) {
    return frame.phase_code;
  }
  if (frame.key_moment) {
    return frame.key_moment;
  }
  return `标记 ${index + 1}`;
}

function buildTimelineMarkers(analysis: AnalysisDetail, pose: PoseResponse | null): TimelineMarker[] {
  const semantic = analysis.video_temporal_diagnostics?.selected_semantic_frames ?? [];
  const semanticMarkers = semantic
    .map((frame, index) => {
      if (typeof frame.timestamp !== "number" || !Number.isFinite(frame.timestamp)) {
        return null;
      }
      return {
        key: `${frame.phase_code ?? "semantic"}-${index}`,
        label: labelForSemanticFrame(frame, index),
        timestamp: frame.timestamp,
        color: MARKER_COLORS[index % MARKER_COLORS.length],
      };
    })
    .filter((item): item is TimelineMarker => Boolean(item));

  if (semanticMarkers.length) {
    return semanticMarkers;
  }

  const keyFrames = analysis.bio_data?.key_frames ?? {};
  const poseByStem = new Map((pose?.frames ?? []).map((frame, index) => [frameStem(frame.frame), { frame, index }]));
  return Object.entries(keyFrames)
    .map(([key, frameId], index) => {
      if (!frameId || !pose) {
        return null;
      }
      const match = poseByStem.get(frameStem(frameId));
      if (!match) {
        return null;
      }
      return {
        key,
        label: key === "T" ? "起跳" : key === "A" ? "最高点" : key === "L" ? "落冰" : key,
        timestamp: timestampForFrame(pose, match.frame, match.index),
        color: MARKER_COLORS[index % MARKER_COLORS.length],
      };
    })
    .filter((item): item is TimelineMarker => Boolean(item));
}

function ActionTimeline({
  markers,
  duration,
  onSeek,
}: {
  markers: TimelineMarker[];
  duration: number | null;
  onSeek: (timestamp: number) => void;
}) {
  const safeDuration =
    typeof duration === "number" && Number.isFinite(duration) && duration > 0
      ? duration
      : Math.max(1, ...markers.map((marker) => marker.timestamp + 0.5));

  return (
    <div className="border-t border-white/10 bg-[#0C1422] px-3 py-4 tablet:px-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-200">动作时间轴</p>
        <p className="text-xs text-slate-400">{markers.length ? `${markers.length} 个标注点` : "暂无关键帧标记"}</p>
      </div>
      <div className="mt-4 rounded-lg border border-white/10 bg-[#101826] p-3">
        <div className="relative h-[72px] rounded-md bg-slate-950/50 ring-1 ring-white/6">
          <div className="absolute inset-x-3 top-1/2 h-px -translate-y-1/2 bg-slate-600/65" />
          {markers.length ? (
            markers.map((marker) => {
              const left = Math.max(5, Math.min(95, (marker.timestamp / safeDuration) * 100));
              const width = `${Math.max(8, Math.min(22, (marker.timestamp / safeDuration) * 100))}%`;
              return (
                <button
                  key={marker.key}
                  type="button"
                  title={`${marker.label} / ${marker.timestamp.toFixed(2)}s`}
                  onClick={() => onSeek(marker.timestamp)}
                  className="group absolute top-1/2 h-8 -translate-y-1/2 rounded-md border border-white/14 shadow-sm transition hover:-translate-y-[54%] hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-cyan-300/60"
                  style={{ left: `${left}%`, width, transform: "translate(-50%, -50%)", backgroundColor: marker.color }}
                >
                  <span className="flex h-full items-center justify-between gap-2 px-2 text-left text-[11px] font-semibold text-white">
                    <span className="truncate">{marker.label}</span>
                    <span className="shrink-0 text-white/80">{marker.timestamp.toFixed(1)}s</span>
                  </span>
                </button>
              );
            })
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-slate-400">暂无关键帧标记</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ModernAnalysisWorkspace({ analysis, pose, selectedFrameId, onFrameChange }: ModernAnalysisWorkspaceProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const timelineMarkers = useMemo(() => buildTimelineMarkers(analysis, pose), [analysis, pose]);

  return (
    <section className="space-y-5 rounded-lg border border-white/10 bg-[#0C1422] p-4 text-slate-100 shadow-[0_24px_80px_rgba(2,6,23,0.26)] tablet:p-5">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-end tablet:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">AI 视频分析工作站</p>
          <h2 className="mt-2 text-2xl font-semibold leading-tight text-white">骨骼追踪与生物力学分析</h2>
        </div>
        <div className="w-fit shrink-0 rounded-lg border border-white/10 bg-slate-950/30 px-4 py-3 text-sm text-slate-300">
          {pose?.frames?.length ? `${pose.frames.length} 帧姿态数据` : "暂无姿态数据"}
        </div>
      </div>

      <PerformanceMetrics analysis={analysis} />

      <div className="grid min-w-0 gap-5 web:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          <SkeletonVideoPlayer
            analysisId={analysis.id}
            pose={pose}
            selectedFrameId={selectedFrameId}
            onFrameChange={onFrameChange}
            timelineMarkers={timelineMarkers}
            videoRef={videoRef}
          />
        </div>

        <aside className="min-w-0 rounded-lg border border-white/10 bg-[#0E1726] p-4 shadow-[0_18px_50px_rgba(2,6,23,0.18)]">
          <p className="text-sm font-semibold text-white">实时姿态概览</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 web:grid-cols-1">
            <div className="rounded-md border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">关键帧</p>
              <p className="mt-2 text-2xl font-semibold text-white">{pose?.frames?.length ?? 0}</p>
            </div>
            <div className="rounded-md border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">连接线</p>
              <p className="mt-2 text-2xl font-semibold text-white">{pose?.connections?.length ?? 0}</p>
            </div>
          </div>
          <div className="mt-4 rounded-md border border-white/10 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400">帧速信息</p>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              {typeof pose?.effective_fps === "number" && pose.effective_fps > 0 ? `有效 FPS：${pose.effective_fps.toFixed(1)}` : "有效 FPS 未提供，按帧序号估算时间。"}
            </p>
          </div>
          <div className="mt-4 rounded-md border border-white/10 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400">时间轴说明</p>
            <p className="mt-2 text-sm leading-6 text-slate-300">点击彩色条块即可跳转到对应动作阶段。</p>
          </div>
        </aside>
      </div>

      <div className="grid min-w-0 gap-5 web:grid-cols-[minmax(0,1fr)_360px] web:items-start">
        <aside className="min-w-0 rounded-lg border border-white/10 bg-[#0E1726] p-4 shadow-[0_18px_50px_rgba(2,6,23,0.18)]">
          <p className="text-sm font-semibold text-white">动作时间轴</p>
          <div className="mt-4 space-y-3">
            {timelineMarkers.length ? (
              timelineMarkers.map((marker) => (
                <button
                  key={marker.key}
                  type="button"
                  onClick={() => {
                    if (videoRef.current) {
                      videoRef.current.currentTime = marker.timestamp;
                      void videoRef.current.play().catch(() => undefined);
                    }
                  }}
                  className="flex min-h-[48px] w-full min-w-0 items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-3 text-left text-sm transition hover:border-white/20 hover:bg-white/8"
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: marker.color }} />
                    <span className="truncate font-medium text-slate-200">{marker.label}</span>
                  </span>
                  <span className="shrink-0 text-slate-400">{marker.timestamp.toFixed(2)}s</span>
                </button>
              ))
            ) : (
              <p className="text-sm leading-6 text-slate-400">本次分析暂未返回语义关键帧或生物力学关键帧。</p>
            )}
          </div>
        </aside>

        <aside className="min-w-0 rounded-lg border border-white/10 bg-[#0E1726] p-4 shadow-[0_18px_50px_rgba(2,6,23,0.18)]">
          <p className="text-sm font-semibold text-white">分析上下文</p>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4 rounded-md bg-white/5 px-3 py-3">
              <dt className="text-slate-400">动作</dt>
              <dd className="text-right font-medium text-slate-100">{analysis.action_type}</dd>
            </div>
            <div className="flex justify-between gap-4 rounded-md bg-white/5 px-3 py-3">
              <dt className="text-slate-400">流程版本</dt>
              <dd className="text-right font-medium text-slate-100">{analysis.pipeline_version ?? "未知"}</dd>
            </div>
            <div className="flex justify-between gap-4 rounded-md bg-white/5 px-3 py-3">
              <dt className="text-slate-400">源视频 FPS</dt>
              <dd className="text-right font-medium text-slate-100">{analysis.source_fps ? Math.round(analysis.source_fps) : "未知"}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </section>
  );
}
