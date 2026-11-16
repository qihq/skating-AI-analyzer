import { forwardRef, useEffect, useImperativeHandle, useRef, type CSSProperties, type ReactNode } from "react";
import type { PoseResponse } from "../api/client";
import { MediaControls } from "./MediaControls";
import type { MediaManifest, MediaMarker, SourceFrameIdentity } from "./types";
import { useMediaController } from "./useMediaController";
import { VideoSurface } from "./VideoSurface";
import { PoseSurface } from "./PoseSurface";

export type IceMediaPlayerHandle = {
  seek: (timestamp: number, options?: { play?: boolean }) => void;
  pause: () => void;
  video: () => HTMLVideoElement | null;
};

type Props = { manifest?: MediaManifest | null; fallbackSrc?: string; pose?: PoseResponse | null; markers?: MediaMarker[]; mode?: "video" | "pose" | "overlay"; className?: string; aspectRatio?: number; onTimeChange?: (timestamp: number) => void; seekTime?: number | null; sourceFrame?: SourceFrameIdentity | null; onStepSourceFrame?: (direction: -1 | 1) => void; unavailableFrame?: boolean; overlay?: ReactNode };

export const IceMediaPlayer = forwardRef<IceMediaPlayerHandle | null, Props>(function IceMediaPlayer({ manifest, fallbackSrc, pose, markers = [], mode = "video", className = "", aspectRatio, onTimeChange, seekTime, sourceFrame, onStepSourceFrame, unavailableFrame = false, overlay }, forwardedRef) {
  const fallbackManifest: MediaManifest | null = manifest ?? (fallbackSrc ? { schema_version: "fallback", status: "ready", sources: [{ quality: "original", status: "ready", width: null, height: null, url: fallbackSrc, filename: null, error: null }] } : null);
  const controller = useMediaController(fallbackManifest);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  useImperativeHandle(forwardedRef, () => ({
    seek: (timestamp, options) => {
      controller.commitSeek(timestamp);
      if (options?.play) void controller.play();
    },
    pause: controller.pause,
    video: () => videoRef.current,
  }), [controller]);
  // Repeat after metadata arrives so an initial seek survives a browser source reset.
  useEffect(() => { if (seekTime != null) controller.commitSeek(seekTime); }, [controller.commitSeek, controller.state.duration, seekTime]);
  useEffect(() => { onTimeChange?.(controller.state.previewTime ?? controller.state.currentTime); }, [controller.state.currentTime, controller.state.previewTime, onTimeChange]);
  const style = aspectRatio ? { "--ice-media-aspect-ratio": String(aspectRatio) } as CSSProperties : undefined;
  return <section className={`ice-media-player ${className}`} style={style}>
    <div className="ice-media-player__surface">
      {mode !== "pose" ? <VideoSurface ref={videoRef} controller={controller} manifest={fallbackManifest}>{mode === "overlay" && pose ? <PoseSurface pose={pose} videoRef={videoRef} timestamp={controller.state.currentTime} className="ice-media-player__overlay" /> : null}{overlay}</VideoSurface> : null}
      {mode === "pose" && pose ? <PoseSurface pose={pose} timestamp={controller.state.previewTime ?? controller.state.currentTime} /> : null}
    </div>
    <MediaControls controller={controller} markers={markers} sourceFrame={sourceFrame ?? controller.state.sourceFrame} onStepSourceFrame={onStepSourceFrame ?? controller.stepSourceFrame} unavailableFrame={unavailableFrame} />
    {controller.state.timingWarning ? <p role="status" className="ice-media-controls__error">{controller.state.timingWarning}</p> : null}
  </section>;
});
