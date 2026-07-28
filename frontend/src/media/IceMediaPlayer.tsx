import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { PoseResponse } from "../api/client";
import { MediaControls } from "./MediaControls";
import type { MediaManifest, MediaMarker } from "./types";
import { useMediaController } from "./useMediaController";
import { VideoSurface } from "./VideoSurface";
import { PoseSurface } from "./PoseSurface";

export type IceMediaPlayerHandle = {
  seek: (timestamp: number, options?: { play?: boolean }) => void;
  pause: () => void;
  video: () => HTMLVideoElement | null;
};

type Props = { manifest?: MediaManifest | null; fallbackSrc?: string; pose?: PoseResponse | null; markers?: MediaMarker[]; mode?: "video" | "pose" | "overlay"; className?: string; onTimeChange?: (timestamp: number) => void; seekTime?: number | null };

export const IceMediaPlayer = forwardRef<IceMediaPlayerHandle, Props>(function IceMediaPlayer({ manifest, fallbackSrc, pose, markers = [], mode = "video", className = "", onTimeChange, seekTime }, forwardedRef) {
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
  return <section className={`ice-media-player ${className}`}>
    <div className="ice-media-player__surface">
      {mode !== "pose" ? <VideoSurface ref={videoRef} controller={controller} manifest={fallbackManifest}>{mode === "overlay" && pose ? <PoseSurface pose={pose} timestamp={controller.state.previewTime ?? controller.state.currentTime} className="ice-media-player__overlay" /> : null}</VideoSurface> : null}
      {mode === "pose" && pose ? <PoseSurface pose={pose} timestamp={controller.state.previewTime ?? controller.state.currentTime} /> : null}
    </div>
    <MediaControls controller={controller} markers={markers} />
  </section>;
});
