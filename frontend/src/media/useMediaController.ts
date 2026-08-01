import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { qualitySource } from "./qualitySelection";
import type { BufferedRange, MediaControllerState, MediaManifest, MediaQuality, SourceFrameIdentity } from "./types";

const initialState: MediaControllerState = {
  duration: 0, currentTime: 0, previewTime: null, paused: true, buffering: false, buffered: [],
  volume: 1, muted: false, playbackRate: 1, quality: "auto", isFullscreen: false, isPictureInPicture: false, error: null,
  sourceFrame: null, timingStatus: "unavailable", timingWarning: null,
};

function ranges(video: HTMLVideoElement): BufferedRange[] {
  return Array.from({ length: video.buffered.length }, (_, index) => ({ start: video.buffered.start(index), end: video.buffered.end(index) }));
}

export function useMediaController(manifest: MediaManifest | null | undefined) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const switchToken = useRef(0);
  const pendingSeek = useRef<number | null>(null);
  const [state, setState] = useState<MediaControllerState>(initialState);
  const source = useMemo(() => qualitySource(manifest, state.quality), [manifest, state.quality]);
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
    const token = ++switchToken.current;
    const snapshot = { src: video.src, currentTime: video.currentTime, paused: video.paused, volume: video.volume, muted: video.muted, playbackRate: video.playbackRate, quality: state.quality };
    setState((current) => ({ ...current, buffering: true, error: null }));
    try {
      await new Promise<void>((resolve, reject) => {
        const onLoaded = () => { cleanup(); resolve(); };
        const onError = () => { cleanup(); reject(new Error("source failed")); };
        const cleanup = () => { video.removeEventListener("loadedmetadata", onLoaded); video.removeEventListener("error", onError); };
        video.addEventListener("loadedmetadata", onLoaded, { once: true }); video.addEventListener("error", onError, { once: true });
        video.src = candidate.url!; video.load();
      });
      if (token !== switchToken.current) return;
      video.currentTime = snapshot.currentTime; video.volume = snapshot.volume; video.muted = snapshot.muted; video.playbackRate = snapshot.playbackRate;
      if (!snapshot.paused) await video.play();
      setState((current) => ({ ...current, quality, buffering: false }));
    } catch {
      if (token !== switchToken.current) return;
      video.src = snapshot.src; video.load(); video.currentTime = snapshot.currentTime;
      setState((current) => ({ ...current, quality: snapshot.quality, buffering: false, error: "清晰度切换失败，已恢复原视频" }));
    }
  }, [manifest, state.quality]);

  const onLoadedMetadata = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (pendingSeek.current != null) {
      video.currentTime = Math.min(pendingSeek.current, Number.isFinite(video.duration) ? video.duration : pendingSeek.current);
      pendingSeek.current = null;
    }
    const timingStatus = timeline?.timestamp_status ?? "unavailable";
    setState((current) => ({ ...current, duration: video.duration || timeline?.duration_sec || 0, volume: video.volume, muted: video.muted, playbackRate: video.playbackRate, timingStatus, timingWarning: timingStatus === "exact" ? null : timingStatus === "approximate_legacy" ? "Legacy timing is approximate; it is not V2 exact evidence." : "Source timestamps are unavailable." }));
  }, [timeline]);
  const onTimeUpdate = useCallback(() => { const video = videoRef.current; if (video) setState((current) => current.previewTime == null ? { ...current, currentTime: video.currentTime, buffered: ranges(video), sourceFrame: frameAtPts(video.currentTime) } : current); }, [frameAtPts]);
  const onPlay = useCallback(() => setState((current) => ({ ...current, paused: false })), []);
  const onPause = useCallback(() => setState((current) => ({ ...current, paused: true })), []);
  const onWaiting = useCallback(() => setState((current) => ({ ...current, buffering: true })), []);
  const onPlaying = useCallback(() => setState((current) => ({ ...current, buffering: false })), []);
  const onError = useCallback(() => setState((current) => ({ ...current, buffering: false, error: "视频无法播放" })), []);
  useEffect(() => () => { switchToken.current += 1; }, []);
  return { state, source, bindVideo, commitSeek, commitSourceFrame, stepSourceFrame, previewSeek, togglePlay, play, pause, setPlaybackRate, setVolume, setMuted, setQuality, mediaProps: { onLoadedMetadata, onTimeUpdate, onPlay, onPause, onWaiting, onPlaying, onError } };
}
