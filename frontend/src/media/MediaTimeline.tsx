import { useMemo } from "react";
import type { BufferedRange, MediaMarker } from "./types";

type Props = {
  duration: number;
  currentTime: number;
  previewTime: number | null;
  buffered: BufferedRange[];
  markers?: MediaMarker[];
  onPreview: (time: number) => void;
  onCommit: (time: number) => void;
};

export function MediaTimeline({ duration, currentTime, previewTime, buffered, markers = [], onPreview, onCommit }: Props) {
  const value = previewTime ?? currentTime;
  const safeDuration = Math.max(duration, 0);
  const markerLabel = useMemo(() => markers.map((marker) => marker.label).join("，"), [markers]);
  const readTime = (value: string) => Math.max(0, Math.min(Number(value), safeDuration));
  return <div className="ice-media-timeline">
    <div aria-hidden="true" className="ice-media-timeline__buffer">
      {buffered.map((range, index) => <span key={index} style={{ left: `${range.start / Math.max(safeDuration, 1) * 100}%`, width: `${(range.end - range.start) / Math.max(safeDuration, 1) * 100}%` }} />)}
      {markers.map((marker) => <i key={marker.id} style={{ left: `${marker.timestamp / Math.max(safeDuration, 1) * 100}%` }} title={marker.label} />)}
    </div>
    <input aria-label={`播放进度${markerLabel ? `，关键帧：${markerLabel}` : ""}`} type="range" min="0" max={safeDuration || 0} step="0.01" value={Math.min(value, safeDuration || value)}
      onChange={(event) => onPreview(readTime(event.target.value))} onPointerUp={(event) => onCommit(readTime((event.target as HTMLInputElement).value))}
      onKeyUp={(event) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) onCommit(readTime((event.target as HTMLInputElement).value)); }} />
  </div>;
}
