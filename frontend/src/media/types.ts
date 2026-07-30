import type { MediaManifest, MediaQuality, MediaSource } from "../api/client";

export type { MediaManifest, MediaQuality, MediaSource };

export type MediaMarker = {
  id: string;
  timestamp: number;
  label: string;
  phase?: string;
};

export type SourceFrameIdentity = {
  sourceFrameIndex: number;
  pts: number;
  duration: number | null;
};

export type BufferedRange = { start: number; end: number };

export type MediaControllerState = {
  duration: number;
  currentTime: number;
  previewTime: number | null;
  paused: boolean;
  buffering: boolean;
  buffered: BufferedRange[];
  volume: number;
  muted: boolean;
  playbackRate: number;
  quality: MediaQuality;
  isFullscreen: boolean;
  isPictureInPicture: boolean;
  error: string | null;
};
