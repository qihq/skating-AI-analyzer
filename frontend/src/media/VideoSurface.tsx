import { forwardRef, useImperativeHandle, useRef, type ReactNode } from "react";
import type { MediaManifest } from "./types";
import { qualitySource } from "./qualitySelection";
import type { useMediaController } from "./useMediaController";

type Props = { controller: ReturnType<typeof useMediaController>; manifest: MediaManifest | null | undefined; className?: string; children?: ReactNode };

export const VideoSurface = forwardRef<HTMLVideoElement, Props>(function VideoSurface({ controller, manifest, className = "", children }, forwardedRef) {
  const internalRef = useRef<HTMLVideoElement | null>(null);
  useImperativeHandle(forwardedRef, () => internalRef.current as HTMLVideoElement);
  const source = controller.source ?? qualitySource(manifest, "auto");
  return <div className={`ice-video-surface ${className}`}>
    <video aria-label="分析视频" ref={(element) => { internalRef.current = element; controller.bindVideo(element); }} src={source?.url ?? undefined} playsInline preload="metadata" className="ice-video-surface__video" {...controller.mediaProps} />
    {children}
  </div>;
});
