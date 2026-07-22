import { useCallback, useEffect, useRef, useState } from "react";
import type { PoseFrame } from "../api/client";
import { drawPoseOverlay } from "../utils/poseCanvas";

type Props = {
  frame: PoseFrame | null;
  frameUrl: string | null;
  connections: number[][];
  alt: string;
  className?: string;
};

export default function PoseFrameCanvas({ frame, frameUrl, connections, alt, className = "" }: Props) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = useState(false);

  const redraw = useCallback(() => {
    const image = imageRef.current;
    const canvas = canvasRef.current;
    if (!frame || !image || !canvas || !image.naturalWidth || !image.naturalHeight) return;
    drawPoseOverlay(canvas, frame, connections, {
      mediaWidth: image.naturalWidth,
      mediaHeight: image.naturalHeight,
    });
  }, [connections, frame]);

  useEffect(() => {
    setFailed(false);
  }, [frameUrl]);

  useEffect(() => {
    window.addEventListener("resize", redraw);
    return () => window.removeEventListener("resize", redraw);
  }, [redraw]);

  if (!frameUrl || failed) {
    return (
      <div className={`flex aspect-video items-center justify-center bg-slate-950 px-4 text-center text-sm text-slate-300 ${className}`}>
        当前阶段没有可展示的画面
      </div>
    );
  }

  return (
    <div className={`relative aspect-video overflow-hidden bg-slate-950 ${className}`}>
      <img
        ref={imageRef}
        src={frameUrl}
        alt={alt}
        className="absolute inset-0 h-full w-full object-contain"
        onLoad={redraw}
        onError={() => setFailed(true)}
      />
      {frame ? <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden="true" /> : null}
    </div>
  );
}
