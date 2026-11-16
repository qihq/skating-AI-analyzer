import { useCallback, useEffect, useRef, useState } from "react";
import type { PoseFrame } from "../api/client";
import { drawPoseOverlay } from "../utils/poseCanvas";

type Props = {
  frame: PoseFrame | null;
  frameUrl: string | null;
  connections: number[][];
  alt: string;
  className?: string;
  unavailableLabel?: string;
};

export default function PoseFrameCanvas({ frame, frameUrl, connections, alt, className = "", unavailableLabel = "当前阶段没有可展示的画面" }: Props) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const loadedUrlRef = useRef<string | null>(null);
  const [failed, setFailed] = useState(false);

  const redraw = useCallback(() => {
    const image = imageRef.current;
    const canvas = canvasRef.current;
    if (!frame || !frameUrl || !image || !canvas) return;
    // Only paint once the element really holds the requested image: a src that
    // is still loading would otherwise be projected with the previous size.
    if (loadedUrlRef.current !== frameUrl) return;
    if (!image.complete || !image.naturalWidth || !image.naturalHeight) return;
    drawPoseOverlay(canvas, frame, connections, {
      mediaWidth: image.naturalWidth,
      mediaHeight: image.naturalHeight,
    });
  }, [connections, frame, frameUrl]);

  useEffect(() => {
    setFailed(false);
    loadedUrlRef.current = null;
  }, [frameUrl]);

  // Repaint on prop changes too: a cached image with an unchanged src never
  // fires another load event, so onLoad alone leaves the canvas blank.
  useEffect(() => {
    const image = imageRef.current;
    if (image && frameUrl && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0) {
      loadedUrlRef.current = frameUrl;
    }
    redraw();
  }, [frameUrl, redraw]);

  useEffect(() => {
    window.addEventListener("resize", redraw);
    return () => window.removeEventListener("resize", redraw);
  }, [redraw]);

  const handleLoad = useCallback(() => {
    const image = imageRef.current;
    if (!image || !frameUrl || !image.naturalWidth || !image.naturalHeight) return;
    loadedUrlRef.current = frameUrl;
    redraw();
  }, [frameUrl, redraw]);

  if (!frameUrl || failed) {
    return (
      <div className={`flex aspect-video items-center justify-center bg-slate-950 px-4 text-center text-sm text-slate-300 ${className}`}>
        {unavailableLabel}
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
        onLoad={handleLoad}
        onError={() => setFailed(true)}
      />
      {frame ? <canvas key={frameUrl} ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden="true" /> : null}
    </div>
  );
}
