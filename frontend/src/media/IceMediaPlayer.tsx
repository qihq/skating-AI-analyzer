import type { PoseResponse } from "../api/client";
import { MediaControls } from "./MediaControls";
import type { MediaManifest, MediaMarker } from "./types";
import { useMediaController } from "./useMediaController";
import { VideoSurface } from "./VideoSurface";
import { PoseSurface } from "./PoseSurface";

type Props = { manifest?: MediaManifest | null; fallbackSrc?: string; pose?: PoseResponse | null; markers?: MediaMarker[]; mode?: "video" | "pose" | "overlay"; className?: string };

export function IceMediaPlayer({ manifest, fallbackSrc, pose, markers = [], mode = "video", className = "" }: Props) {
  const fallbackManifest: MediaManifest | null = manifest ?? (fallbackSrc ? { schema_version: "fallback", status: "ready", sources: [{ quality: "original", status: "ready", width: null, height: null, url: fallbackSrc, filename: null, error: null }] } : null);
  const controller = useMediaController(fallbackManifest);
  return <section className={`ice-media-player ${className}`}>
    <div className="ice-media-player__surface">
      {mode !== "pose" ? <VideoSurface controller={controller} manifest={fallbackManifest}>{mode === "overlay" && pose ? <PoseSurface pose={pose} timestamp={controller.state.previewTime ?? controller.state.currentTime} className="ice-media-player__overlay" /> : null}</VideoSurface> : null}
      {mode === "pose" && pose ? <PoseSurface pose={pose} timestamp={controller.state.previewTime ?? controller.state.currentTime} /> : null}
    </div>
    <MediaControls controller={controller} markers={markers} />
  </section>;
}
