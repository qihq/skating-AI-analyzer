import { useEffect, useRef, useState } from "react";

import { PoseFrame, PoseKeypoint, PoseResponse } from "../api/client";

type PoseViewerProps = {
  pose: PoseResponse;
  activeFrameId?: string | null;
  onFrameChange?: (frameId: string) => void;
};

const UPPER_BODY = new Set([11, 12, 13, 14, 15, 16]);
const LOWER_BODY = new Set([23, 24, 25, 26, 27, 28, 29, 30, 31, 32]);
const AXIS_POINTS = new Set([0, 11, 12, 23, 24]);

function frameIdFromName(frame: string) {
  return frame.replace(/\.jpg$/i, "");
}

function keypointColor(point: PoseKeypoint) {
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
  image: HTMLImageElement | null,
  frame: PoseFrame,
  connections: number[][],
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
  context.fillStyle = "#020617";
  context.fillRect(0, 0, width, height);

  if (image?.complete) {
    context.drawImage(image, 0, 0, width, height);
    context.fillStyle = "rgba(2, 6, 23, 0.22)";
    context.fillRect(0, 0, width, height);
  }

  if (frame.target_bbox) {
    context.strokeStyle = "rgba(56, 189, 248, 0.95)";
    context.lineWidth = 2;
    context.setLineDash([8, 6]);
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
      context.fillText(`lock ${(frame.tracking_confidence * 100).toFixed(0)}%`, frame.target_bbox.x * width + 8, Math.max(14, frame.target_bbox.y * height - 10));
    }
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
    context.strokeStyle = "rgba(226, 232, 240, 0.82)";
    context.lineWidth = 3;
    context.beginPath();
    context.moveTo(a.x * width, a.y * height);
    context.lineTo(b.x * width, b.y * height);
    context.stroke();
  }

  for (const point of frame.keypoints) {
    if (point.visibility < 0.5) {
      continue;
    }
    context.fillStyle = keypointColor(point);
    context.beginPath();
    context.arc(point.x * width, point.y * height, AXIS_POINTS.has(point.id) ? 5 : 4, 0, Math.PI * 2);
    context.fill();
  }
}

export default function PoseViewer({ pose, activeFrameId, onFrameChange }: PoseViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  const frames = pose.frames;
  const currentFrame = frames[frameIndex];

  useEffect(() => {
    if (!activeFrameId) {
      return;
    }
    const nextIndex = frames.findIndex((frame) => frameIdFromName(frame.frame) === activeFrameId);
    if (nextIndex >= 0) {
      setFrameIndex(nextIndex);
      setIsPlaying(false);
    }
  }, [activeFrameId, frames]);

  useEffect(() => {
    if (!currentFrame) {
      return;
    }

    const redraw = () => {
      if (canvasRef.current) {
        drawPose(canvasRef.current, imageRef.current, currentFrame, pose.connections);
      }
    };
    const image = new Image();
    image.src = pose.frame_urls[currentFrame.frame] ?? "";
    image.onload = () => {
      imageRef.current = image;
      redraw();
    };
    image.onerror = () => {
      imageRef.current = null;
      redraw();
    };

    onFrameChange?.(frameIdFromName(currentFrame.frame));
    window.addEventListener("resize", redraw);
    return () => {
      window.removeEventListener("resize", redraw);
    };
  }, [currentFrame, onFrameChange, pose.connections, pose.frame_urls]);

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

  return (
    <div className="space-y-4">
      <canvas ref={canvasRef} className="h-auto w-full rounded-[1.5rem] border border-white/10 bg-slate-950" />

      <div className="flex flex-wrap items-center gap-3 rounded-[1.25rem] border border-white/10 bg-white/5 p-3">
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
      </div>
    </div>
  );
}
