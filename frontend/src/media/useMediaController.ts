import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { availableQualities as listAvailableQualities, qualitySource } from "./qualitySelection";
import type { BufferedRange, MediaControllerState, MediaManifest, MediaQuality, SourceFrameIdentity } from "./types";

const initialState: MediaControllerState = {
  duration: 0, currentTime: 0, previewTime: null, paused: true, buffering: false, buffered: [],
  volume: 1, muted: false, playbackRate: 1, quality: "auto", isFullscreen: false, isPictureInPicture: false, error: null,
  sourceFrame: null, timingStatus: "unavailable", timingWarning: null,
};

type QualitySwitch = {
  token: number;
  url: string;
  previousUrl: string;
  recovering?: boolean;
  currentTime: number;
  paused: boolean;
  volume: number;
  muted: boolean;
  playbackRate: number;
  quality: MediaQuality;
};

function ranges(video: HTMLVideoElement): BufferedRange[] {
  return Array.from({ length: video.buffered.length }, (_, index) => ({ start: video.buffered.start(index), end: video.buffered.end(index) }));
}

export function useMediaController(manifest: MediaManifest | null | undefined) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const switchToken = useRef(0);
  const pendingSeek = useRef<number | null>(null);
  const pendingSwitch = useRef<QualitySwitch | null>(null);
  const [state, setState] = useState<MediaControllerState>(initialState);
  const source = useMemo(() => qualitySource(manifest, state.quality), [manifest, state.quality]);
  const availableQualities = useMemo(() => listAvailableQualities(manifest), [manifest]);
  const timeline = manifest?.source_timeline ?? null;
  const frameAtPts = useCallback((timestamp: number): SourceFrameIdentity | null => {
    if (!timeline || timeline.timestamp_status !== "exact") return null;
    const candidates = timeline.frames.filter((frame) => frame.pts_sec != null);
    const selected = candidates.reduce<typeof candidates[number] | null>((best, frame) => !best || Math.abs((frame.pts_sec as number) - timestamp) < Math.abs((best.pts_sec as number) - timestamp) ? frame : best, null);
    return selected && selected.pts_sec != null ? { sourceFrameIndex: selected.source_frame_index, pts: selected.pts_sec, duration: selected.duration_sec, status: selected.status } : null;
  }, [timeline]);
  const frameByIndex = useCallback((index: number): SourceFrameIdentity | null => {
    const selected = timeline?.frames.find((frame) => frame.source_frame_index === index);
    return selected && selected.pts_sec != null ? { sourceFrameIndex: selected.source_frame_index, pts: selected.pts_sec, duration: selected.duration_sec, status: selected.status } : null;
  }, [timeline]);

  const bindVideo = useCallback((video: HTMLVideoElement | null) => { videoRef.current = video; }, []);
  const commitSeek = useCallback((time: number) => {
    const video = videoRef.current;
    const next = Math.max(0, Math.min(time, Number.isFinite(video?.duration) ? video!.duration : time));
    pendingSeek.current = next;
    if (video) video.currentTime = next;
    setState((current) => ({ ...current, currentTime: next, previewTime: null, sourceFrame: frameAtPts(next) }));
  }, [frameAtPts]);
  const commitSourceFrame = useCallback((index: number) => {
    const frame = frameByIndex(index);
    if (!frame) { setState((current) => ({ ...current, error: "Requested source frame is unavailable." })); return false; }
    commitSeek(frame.pts);
    return true;
  }, [commitSeek, frameByIndex]);
  const stepSourceFrame = useCallback((direction: -1 | 1) => {
    const current = state.sourceFrame?.sourceFrameIndex ?? frameAtPts(state.currentTime)?.sourceFrameIndex;
    return current == null ? false : commitSourceFrame(current + direction);
  }, [commitSourceFrame, frameAtPts, state.currentTime, state.sourceFrame]);
  const previewSeek = useCallback((time: number) => setState((current) => ({ ...current, previewTime: Math.max(0, time) })), []);
  const togglePlay = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    try { if (video.paused) await video.play(); else video.pause(); } catch { setState((current) => ({ ...current, error: "播放被浏览器阻止" })); }
  }, []);
  const play = useCallback(async () => {
    const video = videoRef.current;
    if (!video || !video.paused) return;
    try { await video.play(); } catch { setState((current) => ({ ...current, error: "播放被浏览器阻止" })); }
  }, []);
  const pause = useCallback(() => { videoRef.current?.pause(); }, []);
  const setPlaybackRate = useCallback((playbackRate: number) => { if (videoRef.current) videoRef.current.playbackRate = playbackRate; setState((current) => ({ ...current, playbackRate })); }, []);
  const setVolume = useCallback((volume: number) => { const next = Math.max(0, Math.min(1, volume)); if (videoRef.current) videoRef.current.volume = next; setState((current) => ({ ...current, volume: next })); }, []);
  const setMuted = useCallback((muted: boolean) => { if (videoRef.current) videoRef.current.muted = muted; setState((current) => ({ ...current, muted })); }, []);
  const setQuality = useCallback(async (quality: MediaQuality) => {
    const video = videoRef.current;
    if (!video || quality === state.quality) { setState((current) => ({ ...current, quality })); return; }
    const candidate = qualitySource(manifest, quality);
    if (!candidate?.url) { setState((current) => ({ ...current, error: "该清晰度暂不可用" })); return; }
    if (candidate.url === source?.url) { setState((current) => ({ ...current, quality, error: null })); return; }
    // React owns the single src update (VideoSurface). Writing video.src/load() here as well would make the browser
    // load twice: the metadata restore below would run for the first load and the second load would reset to 0.
    pendingSeek.current = null; // The current video position supersedes an already-applied seek.
    pendingSwitch.current = {
      token: ++switchToken.current,
      url: candidate.url,
      previousUrl: source?.url ?? video.getAttribute("src") ?? video.src,
      currentTime: video.currentTime,
      paused: video.paused,
      volume: video.volume,
      muted: video.muted,
      playbackRate: video.playbackRate,
      quality: state.quality,
    };
    setState((current) => ({ ...current, quality, buffering: true, error: null }));
  }, [manifest, source?.url, state.quality]);

  const onLoadedMetadata = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const pending = pendingSwitch.current;
    const applied = pending && pending.token === switchToken.current && video.getAttribute("src") === pending.url ? pending : null;
    if (applied) pendingSwitch.current = null;
    const target = pendingSeek.current ?? applied?.currentTime ?? null;
    if (target != null) {
      video.currentTime = Math.min(target, Number.isFinite(video.duration) ? video.duration : target);
      pendingSeek.current = null;
    }
    if (applied) {
      video.volume = applied.volume; video.muted = applied.muted; video.playbackRate = applied.playbackRate;
      if (!applied.paused) void video.play().catch(() => setState((current) => ({ ...current, error: "播放被浏览器阻止" })));
      setState((current) => ({ ...current, buffering: false, error: applied.recovering ? "清晰度切换失败，已恢复视频" : null }));
    }
    const timingStatus = timeline?.timestamp_status ?? "unavailable";
    setState((current) => ({ ...current, duration: video.duration || timeline?.duration_sec || 0, volume: video.volume, muted: video.muted, playbackRate: video.playbackRate, timingStatus, timingWarning: timingStatus === "exact" ? null : timingStatus === "approximate_legacy" ? "Legacy timing is approximate; it is not V2 exact evidence." : "Source timestamps are unavailable." }));
  }, [timeline]);
  const onTimeUpdate = useCallback(() => { const video = videoRef.current; if (video) setState((current) => current.previewTime == null ? { ...current, currentTime: video.currentTime, buffered: ranges(video), sourceFrame: frameAtPts(video.currentTime) } : current); }, [frameAtPts]);
  const onPlay = useCallback(() => setState((current) => ({ ...current, paused: false })), []);
  const onPause = useCallback(() => setState((current) => ({ ...current, paused: true })), []);
  const onWaiting = useCallback(() => setState((current) => ({ ...current, buffering: true })), []);
  const onPlaying = useCallback(() => setState((current) => ({ ...current, buffering: false })), []);
  const onError = useCallback(() => {
    const pending = pendingSwitch.current;
    if (pending && videoRef.current?.getAttribute("src") !== pending.url) return;
    if (!pending || pending.recovering) {
      pendingSwitch.current = null;
      setState((current) => ({ ...current, buffering: false, error: "视频无法播放" }));
      return;
    }
    // The fallback also loads through React; restore its full playback snapshot on metadata.
    const fallback = qualitySource(manifest, pending.quality);
    if (!fallback?.url) {
      pendingSwitch.current = null;
      setState((current) => ({ ...current, buffering: false, error: "视频无法播放" }));
      return;
    }
    // Auto may now select a different transcode after a viewport change.
    // Match restoration to that actual fallback, rather than the old Auto URL.
    pendingSwitch.current = { ...pending, url: fallback.url, recovering: true };
    setState((current) => ({ ...current, quality: pending.quality, buffering: true, error: "清晰度切换失败，正在恢复视频" }));
  }, [manifest]);
  useEffect(() => () => { switchToken.current += 1; pendingSwitch.current = null; }, []);
  return { state, source, availableQualities, bindVideo, commitSeek, commitSourceFrame, stepSourceFrame, previewSeek, togglePlay, play, pause, setPlaybackRate, setVolume, setMuted, setQuality, mediaProps: { onLoadedMetadata, onTimeUpdate, onPlay, onPause, onWaiting, onPlaying, onError } };
}
