import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { CompareKeyframePair, CompareVideoSide } from "../api/client";
import type { IceMediaPlayerHandle } from "./IceMediaPlayer";

type Entry = { player: IceMediaPlayerHandle; side: CompareVideoSide };
export type SynchronizedTimestampPair = { beforeTimestamp: number | null; afterTimestamp: number | null };

function windowFor(side: CompareVideoSide) {
  const start = side.sync_start ?? side.action_window_start ?? 0;
  const duration = side.sync_duration ?? side.action_window_duration ?? (side.action_window_end != null && side.action_window_start != null ? side.action_window_end - side.action_window_start : null);
  return { start, duration: duration && duration > 0 ? duration : null };
}

export function useSynchronizedMediaGroup(
  beforeRef: RefObject<IceMediaPlayerHandle | null>,
  afterRef: RefObject<IceMediaPlayerHandle | null>,
  before: CompareVideoSide,
  after: CompareVideoSide,
) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(0.5);
  const activeRef = useRef(false);
  const entries = useCallback((): Entry[] => [
    { player: beforeRef.current!, side: before },
    { player: afterRef.current!, side: after },
  ].filter((entry) => Boolean(entry.player && entry.side.available && entry.side.video_url)), [after, afterRef, before, beforeRef]);

  const applyRates = useCallback((base: number) => {
    const current = entries();
    const durations = current.map(({ side }) => windowFor(side).duration).filter((value): value is number => value != null);
    const longest = Math.max(...durations, 1);
    current.forEach(({ player, side }) => {
      const video = player.video();
      if (!video) return;
      const duration = windowFor(side).duration;
      video.muted = true;
      video.volume = 0;
      video.playbackRate = duration ? base * duration / longest : base;
    });
  }, [entries]);

  const seekRelative = useCallback((relative: number) => {
    entries().forEach(({ player, side }) => {
      const { start, duration } = windowFor(side);
      player.seek(duration ? start + Math.max(0, Math.min(1, relative)) * duration : start + relative);
    });
    activeRef.current = true;
  }, [entries]);

  const seekTimestamps = useCallback(({ beforeTimestamp, afterTimestamp }: SynchronizedTimestampPair) => {
    const sides = [
      { player: beforeRef.current, side: before, timestamp: beforeTimestamp },
      { player: afterRef.current, side: after, timestamp: afterTimestamp },
    ];
    sides.forEach(({ player, side, timestamp }) => {
      if (player && side.available && side.video_url) player.seek(timestamp ?? windowFor(side).start);
    });
    activeRef.current = true;
  }, [after, afterRef, before, beforeRef]);

  const seekKeyframe = useCallback((pair: CompareKeyframePair) => {
    seekTimestamps({ beforeTimestamp: pair.before.timestamp, afterTimestamp: pair.after.timestamp });
  }, [seekTimestamps]);

  const togglePlayback = useCallback(async () => {
    const current = entries();
    if (!current.length) return;
    if (isPlaying) {
      current.forEach(({ player }) => player.pause());
      setIsPlaying(false);
      return;
    }
    current.forEach(({ player, side }) => {
      const video = player.video();
      const { start, duration } = windowFor(side);
      if (video && (video.ended || !activeRef.current || (duration && (video.currentTime < start || video.currentTime >= start + duration)))) player.seek(start);
    });
    applyRates(speed);
    current.forEach(({ player }) => player.seek(player.video()?.currentTime ?? 0, { play: true }));
    activeRef.current = true;
    setIsPlaying(true);
  }, [applyRates, entries, isPlaying, speed]);

  useEffect(() => { applyRates(speed); }, [applyRates, speed]);
  useEffect(() => {
    const current = entries();
    const pause = () => setIsPlaying(false);
    current.forEach(({ player }) => player.video()?.addEventListener("ended", pause));
    return () => current.forEach(({ player }) => player.video()?.removeEventListener("ended", pause));
  }, [entries]);
  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setInterval(() => {
      const current = entries();
      if (current.length < 2) return;
      const reference = current[0];
      const referenceVideo = reference.player.video();
      const referenceWindow = windowFor(reference.side);
      if (!referenceVideo || !referenceWindow.duration) return;
      const relative = (referenceVideo.currentTime - referenceWindow.start) / referenceWindow.duration;
      current.slice(1).forEach(({ player, side }) => {
        const video = player.video();
        const targetWindow = windowFor(side);
        if (!video || !targetWindow.duration) return;
        const expected = targetWindow.start + relative * targetWindow.duration;
        if (Math.abs(video.currentTime - expected) > 0.18) player.seek(expected);
      });
    }, 800);
    return () => window.clearInterval(timer);
  }, [entries, isPlaying]);

  return { isPlaying, speed, setSpeed, togglePlayback, seekRelative, seekKeyframe, seekTimestamps };
}
