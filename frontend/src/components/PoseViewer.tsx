import { useEffect, useRef, useState } from "react";

import { PoseFrame, PoseKeypoint, PoseResponse } from "../api/client";

type PoseViewerProps = {
  pose: PoseResponse;
  activeFrameId?: string | null;
  activeSourcePts?: number | null;
  selectedEventId?: string | null;
  selectedEventLabel?: string | null;
  onFrameChange?: (frameId: string) => void;
  variant?: "compact" | "debug";
  diagnosticsByFrame?: Record<string, PoseViewerDiagnostic>;
};

type PoseViewerBBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type PoseViewerDiagnostic = {
  rejectedCandidates?: Array<{
    bbox?: PoseViewerBBox | null;
    reasons?: string[];
    source?: string | null;
    trackerId?: number | null;
    confidence?: number | null;
  }>;
  predictionBBox?: PoseViewerBBox | null;
  state?: string | null;
};

const UPPER_BODY = new Set([11, 12, 13, 14, 15, 16]);
const LOWER_BODY = new Set([23, 24, 25, 26, 27, 28, 29, 30, 31, 32]);
const AXIS_POINTS = new Set([0, 11, 12, 23, 24]);

function frameIdFromName(frame: string) {
  return frame.replace(/\.jpg$/i, "");
}

function keypointColor(point: PoseKeypoint) {
  if (point.provenance === "smoothed") return "#A78BFA";
  if (point.provenance === "clipped") return "#FB923C";
  if (point.provenance === "interpolated-display-only") return "#94A3B8";
  if (point.provenance === "identity-blocked" || point.provenance === "missing") return "#64748B";
  if (AXIS_POINTS.has(point.id)) {
    return "#F8FAFC";
  }
  if (UPPER_BODY.has(point.id)) {
    return "#34D399";
  }
  if (LOWER_BODY.has(point.id)) {
    return "#F59E0B";
  }
  return "#38BDF8";
}

function drawPose(
  canvas: HTMLCanvasElement,
  frame: PoseFrame,
  connections: number[][],
  hasFrameImage: boolean,
  diagnostic?: PoseViewerDiagnostic,
) {
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const width = canvas.clientWidth || 720;
  const height = Math.round(width * 0.5625);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 3);
  const pixelWidth = Math.round(width * pixelRatio);
  const pixelHeight = Math.round(height * pixelRatio);

  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
    canvas.style.height = `${height}px`;
  }

  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  if (!hasFrameImage) {
    context.fillStyle = "#020617";
    context.fillRect(0, 0, width, height);
  }

  if (frame.target_bbox) {
    const isInterpolatedFrame = frame.tracking_state === "interpolated";
    const isLowConfidenceFrame = frame.tracking_state === "low_confidence" || (typeof frame.tracking_confidence === "number" && frame.tracking_confidence <= 0.2);
    context.strokeStyle = isInterpolatedFrame
      ? "rgba(148, 163, 184, 0.75)"
      : isLowConfidenceFrame
        ? "rgba(245, 158, 11, 0.95)"
        : "rgba(56, 189, 248, 0.95)";
    context.lineWidth = 2;
    context.setLineDash(isInterpolatedFrame || isLowConfidenceFrame ? [4, 8] : [8, 6]);
    context.strokeRect(
      frame.target_bbox.x * width,
      frame.target_bbox.y * height,
      frame.target_bbox.width * width,
      frame.target_bbox.height * height,
    );
    context.setLineDash([]);
    if (typeof frame.tracking_confidence === "number") {
      context.fillStyle = "rgba(8, 47, 73, 0.88)";
      context.fillRect(frame.target_bbox.x * width, Math.max(0, frame.target_bbox.y * height - 24), 112, 20);
      context.fillStyle = "#E0F2FE";
      context.font = "12px sans-serif";
      context.fillText(
        `${isInterpolatedFrame ? "interp" : isLowConfidenceFrame ? "low" : "lock"} ${(frame.tracking_confidence * 100).toFixed(0)}%`,
        frame.target_bbox.x * width + 8,
        Math.max(14, frame.target_bbox.y * height - 10),
      );
    }
  }

  // An uncertain or lost identity never renders an authoritative skeleton.
  if (frame.identity_state === "uncertain" || frame.identity_state === "lost" || frame.pose_provenance === "identity-blocked") {
    return;
  }

  if (diagnostic?.predictionBBox) {
    context.strokeStyle = "rgba(168, 85, 247, 0.95)";
    context.lineWidth = 2;
    context.setLineDash([3, 6]);
    context.strokeRect(
      diagnostic.predictionBBox.x * width,
      diagnostic.predictionBBox.y * height,
      diagnostic.predictionBBox.width * width,
      diagnostic.predictionBBox.height * height,
    );
    context.setLineDash([]);
  }

  for (const candidate of diagnostic?.rejectedCandidates ?? []) {
    if (!candidate.bbox) {
      continue;
    }
    context.strokeStyle = "rgba(244, 63, 94, 0.92)";
    context.lineWidth = 2;
    context.setLineDash([8, 4]);
    context.strokeRect(
      candidate.bbox.x * width,
      candidate.bbox.y * height,
      candidate.bbox.width * width,
      candidate.bbox.height * height,
    );
    context.setLineDash([]);
    const label = (candidate.reasons ?? []).slice(0, 2).join(", ") || "rejected";
    context.fillStyle = "rgba(127, 29, 29, 0.88)";
    context.fillRect(candidate.bbox.x * width, Math.max(0, candidate.bbox.y * height - 22), Math.min(220, Math.max(96, label.length * 7)), 18);
    context.fillStyle = "#FFE4E6";
    context.font = "11px sans-serif";
    context.fillText(label, candidate.bbox.x * width + 6, Math.max(12, candidate.bbox.y * height - 9));
  }

  const points = new Map(frame.keypoints.map((point) => [point.id, point]));
  context.lineCap = "round";
  context.lineJoin = "round";

  for (const [from, to] of connections) {
    const a = points.get(from);
    const b = points.get(to);
    if (!a || !b || a.visibility < 0.5 || b.visibility < 0.5) {
      continue;
    }
    const interpolated = frame.tracking_state === "interpolated" || Boolean(a.interpolated) || Boolean(b.interpolated) || a.provenance === "interpolated-display-only" || b.provenance === "interpolated-display-only";
    const smoothed = a.provenance === "smoothed" || b.provenance === "smoothed";
    const clipped = a.provenance === "clipped" || b.provenance === "clipped";
    const lowConfidence = frame.tracking_state === "low_confidence" || (typeof frame.tracking_confidence === "number" && frame.tracking_confidence <= 0.2);
    context.strokeStyle = interpolated ? "rgba(148, 163, 184, 0.42)" : clipped ? "rgba(251, 146, 60, 0.72)" : smoothed ? "rgba(167, 139, 250, 0.72)" : lowConfidence ? "rgba(245, 158, 11, 0.46)" : "rgba(226, 232, 240, 0.82)";
    context.lineWidth = interpolated ? 2 : 3;
    context.setLineDash(interpolated ? [6, 6] : clipped ? [2, 5] : []);
    context.beginPath();
    context.moveTo(a.x * width, a.y * height);
    context.lineTo(b.x * width, b.y * height);
    context.stroke();
  }
  context.setLineDash([]);

  for (const point of frame.keypoints) {
    if (point.visibility < 0.5) {
      continue;
    }
    const lowConfidence = frame.tracking_state === "low_confidence" || (typeof frame.tracking_confidence === "number" && frame.tracking_confidence <= 0.2);
    context.fillStyle = frame.tracking_state === "interpolated" || point.interpolated || point.provenance === "interpolated-display-only" ? "rgba(148, 163, 184, 0.62)" : lowConfidence ? "rgba(245, 158, 11, 0.72)" : keypointColor(point);
    context.beginPath();
    context.arc(point.x * width, point.y * height, AXIS_POINTS.has(point.id) ? 5 : 4, 0, Math.PI * 2);
    context.fill();
  }
}

export default function PoseViewer({ pose, activeFrameId, activeSourcePts, selectedEventId, selectedEventLabel, onFrameChange, variant = "compact", diagnosticsByFrame = {} }: PoseViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);
  const selfSyncedFrameIdRef = useRef<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [frameImageError, setFrameImageError] = useState(false);

  const frames = pose.frames;
  const currentFrame = frames[frameIndex];
  const currentFrameUrl = currentFrame ? pose.frame_urls[currentFrame.frame] ?? "" : "";
  const currentFrameId = currentFrame ? frameIdFromName(currentFrame.frame) : "";
  const currentDiagnostic = currentFrameId ? diagnosticsByFrame[currentFrameId] : undefined;
  const rejectedCount = currentDiagnostic?.rejectedCandidates?.length ?? 0;

  useEffect(() => {
    if (!activeFrameId) {
      return;
    }
    const nextIndex = frames.findIndex((frame) => frameIdFromName(frame.frame) === activeFrameId);
    if (nextIndex >= 0 && nextIndex !== frameIndex) {
      if (selfSyncedFrameIdRef.current === activeFrameId) {
        selfSyncedFrameIdRef.current = null;
        return;
      }
      setFrameIndex(nextIndex);
      setIsPlaying(false);
    }
  }, [activeFrameId, frameIndex, frames]);

  useEffect(() => {
    if (activeSourcePts == null || !Number.isFinite(activeSourcePts) || !frames.length) return;
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    frames.forEach((frame, index) => {
      const pts = frame.source_pts_sec ?? pose.frame_timestamps?.[frame.frame] ?? pose.frame_timestamps?.[frameIdFromName(frame.frame)];
      if (typeof pts !== "number") return;
      const distance = Math.abs(pts - activeSourcePts);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    if (nearestIndex !== frameIndex) {
      setFrameIndex(nearestIndex);
      setIsPlaying(false);
    }
  }, [activeSourcePts, frameIndex, frames, pose.frame_timestamps]);

  useEffect(() => {
    if (!currentFrame) {
      return;
    }

    setFrameImageError(false);

    const redraw = () => {
      if (canvasRef.current) {
        drawPose(
          canvasRef.current,
          currentFrame,
          pose.connections,
          Boolean(currentFrameUrl) && !frameImageError && Boolean(imageRef.current?.complete),
          currentDiagnostic,
        );
      }
    };

    const nextFrameId = frameIdFromName(currentFrame.frame);
    selfSyncedFrameIdRef.current = nextFrameId;
    onFrameChange?.(nextFrameId);
    redraw();
    window.addEventListener("resize", redraw);
    return () => {
      window.removeEventListener("resize", redraw);
    };
  }, [currentFrame, currentDiagnostic, currentFrameUrl, frameImageError, onFrameChange, pose.connections]);

  useEffect(() => {
    if (!isPlaying || frames.length <= 1) {
      if (animationRef.current) {
        window.cancelAnimationFrame(animationRef.current);
      }
      return;
    }

    const tick = (timestamp: number) => {
      if (timestamp - lastTickRef.current >= 200) {
        setFrameIndex((current) => (current + 1) % frames.length);
        lastTickRef.current = timestamp;
      }
      animationRef.current = window.requestAnimationFrame(tick);
    };

    animationRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (animationRef.current) {
        window.cancelAnimationFrame(animationRef.current);
      }
    };
  }, [frames.length, isPlaying]);

  if (!frames.length) {
    return (
      <div className="rounded-[1.5rem] border border-white/10 bg-white/5 p-6 text-slate-300">
        当前记录还没有可展示的骨骼姿态数据。新上传的视频会在后台自动尝试提取。
      </div>
    );
  }

  const jumpTo = (nextIndex: number) => {
    setFrameIndex(Math.max(0, Math.min(nextIndex, frames.length - 1)));
  };
  const viewerFrameClass =
    variant === "debug"
      ? "relative overflow-hidden rounded-[1.5rem] border border-white/10 bg-slate-950 shadow-[0_20px_70px_rgba(15,23,42,0.18)]"
      : "relative overflow-hidden rounded-[1.5rem] border border-white/10 bg-slate-950";
  const aspectClass = variant === "debug" ? "aspect-video w-full min-h-[220px] tablet:min-h-[360px] web:min-h-[520px]" : "aspect-video w-full";
  const controlsClass =
    variant === "debug"
      ? "flex flex-wrap items-center gap-3 rounded-[1.25rem] border border-slate-200 bg-white p-3 shadow-sm"
      : "flex flex-wrap items-center gap-3 rounded-[1.25rem] border border-white/10 bg-white/5 p-3";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600" aria-label="姿态证据图例">
        {selectedEventId ? <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 font-semibold text-blue-700">事件 {selectedEventLabel ?? selectedEventId}</span> : null}
        <span className="rounded-full border border-slate-200 bg-white px-3 py-1"><i className="mr-1 inline-block h-2 w-2 rounded-full bg-slate-400" />实测</span>
        <span className="rounded-full border border-violet-200 bg-violet-50 px-3 py-1 text-violet-700"><i className="mr-1 inline-block h-2 w-2 rounded-full bg-violet-400" />平滑</span>
        <span className="rounded-full border border-slate-300 bg-slate-100 px-3 py-1 text-slate-700">虚线：仅显示插值</span>
        <span className="rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-orange-700">裁剪 / 可见性不足</span>
        <span className="rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-rose-700">身份不确定：不显示骨架</span>
      </div>
      <div className={viewerFrameClass}>
        <div className={aspectClass}>
          {currentFrameUrl && !frameImageError ? (
            <img
              ref={imageRef}
              src={currentFrameUrl}
              alt={currentFrame ? `pose frame ${frameIdFromName(currentFrame.frame)}` : "pose frame"}
              className="absolute inset-0 h-full w-full object-contain"
              onLoad={() => {
                if (canvasRef.current && currentFrame) {
                  drawPose(canvasRef.current, currentFrame, pose.connections, true, currentDiagnostic);
                }
              }}
              onError={() => {
                imageRef.current = null;
                setFrameImageError(true);
              }}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950 text-sm text-slate-300">
              当前帧图片加载失败，已退回骨骼视图
            </div>
          )}
          <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
        </div>
      </div>

      <div className={controlsClass}>
        <button type="button" className="pose-control" onClick={() => jumpTo(0)}>
          ⏮
        </button>
        <button type="button" className="pose-control" onClick={() => jumpTo(frameIndex - 1)}>
          ⏪
        </button>
        <button type="button" className="pose-control min-w-16" onClick={() => setIsPlaying((value) => !value)}>
          {isPlaying ? "⏸" : "▶"}
        </button>
        <button type="button" className="pose-control" onClick={() => jumpTo(frameIndex + 1)}>
          ⏩
        </button>
        <button type="button" className="pose-control" onClick={() => jumpTo(frames.length - 1)}>
          ⏭
        </button>

        <input
          type="range"
          min={0}
          max={frames.length - 1}
          value={frameIndex}
          onChange={(event) => jumpTo(Number(event.target.value))}
          className="min-w-44 flex-1 accent-cyan-300"
        />

        <span className="rounded-full bg-slate-950/70 px-3 py-2 text-sm text-slate-100">
          {currentFrame ? frameIdFromName(currentFrame.frame) : "--"} · {frameIndex + 1}/{frames.length}
        </span>
        <span className="rounded-full bg-slate-950/70 px-3 py-2 text-sm text-slate-100">PTS {typeof currentFrame?.source_pts_sec === "number" ? currentFrame.source_pts_sec.toFixed(3) : "--"}s</span>
        {currentFrame?.identity_state === "uncertain" || currentFrame?.identity_state === "lost" ? <span className="rounded-full bg-rose-100 px-3 py-2 text-sm font-semibold text-rose-800">身份{currentFrame.identity_state === "lost" ? "丢失" : "不确定"} · 骨架已隐藏</span> : null}
        {currentFrame?.pose_provenance ? <span className="rounded-full bg-white/90 px-3 py-2 text-xs font-semibold text-slate-700">pose: {currentFrame.pose_provenance}</span> : null}
        {currentDiagnostic?.state ? (
          <span className="rounded-full bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
            tracker {currentDiagnostic.state}
          </span>
        ) : null}
        {currentFrame?.tracking_state === "low_confidence" || (typeof currentFrame?.tracking_confidence === "number" && currentFrame.tracking_confidence <= 0.2) ? (
          <span className="rounded-full bg-amber-100 px-3 py-2 text-sm font-semibold text-amber-800">
            low confidence pose
          </span>
        ) : null}
        {rejectedCount ? (
          <span className="rounded-full bg-rose-100 px-3 py-2 text-sm font-semibold text-rose-800">
            {rejectedCount} rejected bbox
          </span>
        ) : null}
      </div>
    </div>
  );
}
