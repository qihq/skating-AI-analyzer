import { Button, Select } from "../modern/AnimalUi";
import { formatTime } from "./formatTime";
import { MediaTimeline } from "./MediaTimeline";
import type { MediaMarker, MediaQuality } from "./types";
import "./media-player.css";

type Controller = ReturnType<typeof import("./useMediaController").useMediaController>;
type Props = { controller: Controller; markers?: MediaMarker[] };

export function MediaControls({ controller, markers = [] }: Props) {
  const { state, source, togglePlay, commitSeek, previewSeek, setMuted, setPlaybackRate, setQuality } = controller;
  const qualities: MediaQuality[] = ["auto", "original", "1080p", "720p", "480p"];
  return <div className="ice-media-controls">
    <MediaTimeline duration={state.duration} currentTime={state.currentTime} previewTime={state.previewTime} buffered={state.buffered} markers={markers} onPreview={previewSeek} onCommit={commitSeek} />
    <div className="ice-media-controls__row">
      <Button aria-label={state.paused ? "播放" : "暂停"} onClick={() => void togglePlay()}>{state.paused ? "播放" : "暂停"}</Button>
      <Button aria-label="后退五秒" onClick={() => commitSeek(state.currentTime - 5)}> -5s </Button>
      <Button aria-label="前进五秒" onClick={() => commitSeek(state.currentTime + 5)}> +5s </Button>
      <span className="ice-media-controls__time">{formatTime(state.previewTime ?? state.currentTime)} / {formatTime(state.duration)}</span>
      <Button aria-label={state.muted ? "取消静音" : "静音"} onClick={() => setMuted(!state.muted)}>{state.muted ? "取消静音" : "静音"}</Button>
      <Select value={String(state.playbackRate)} onChange={(value) => setPlaybackRate(Number(value))} options={[0.5, 0.75, 1, 1.25, 1.5, 2].map((value) => ({ key: String(value), label: `${value}x`, value: String(value) }))} />
      <Select value={state.quality} onChange={(value) => void setQuality(value as MediaQuality)} options={qualities.filter((quality) => quality === "auto" || quality === "original" || source?.quality === quality).map((quality) => ({ key: quality, label: quality === "auto" ? "自动" : quality, value: quality }))} />
      {markers.map((marker) => <Button key={marker.id} aria-label={`跳到${marker.label}`} onClick={() => commitSeek(marker.timestamp)}>{marker.label}</Button>)}
    </div>
    {state.buffering ? <span className="ice-media-controls__loading">缓冲中...</span> : null}
    {state.error ? <span role="alert" className="ice-media-controls__error">{state.error}</span> : null}
  </div>;
}
