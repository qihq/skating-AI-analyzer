import { Button } from "../modern/AnimalUi";
import { formatTime } from "./formatTime";
import { MediaTimeline } from "./MediaTimeline";
import type { MediaMarker, MediaQuality, SourceFrameIdentity } from "./types";
import "./media-player.css";

type Controller = ReturnType<typeof import("./useMediaController").useMediaController>;
type Props = {
  controller: Controller;
  markers?: MediaMarker[];
  sourceFrame?: SourceFrameIdentity | null;
  onStepSourceFrame?: (direction: -1 | 1) => void;
  unavailableFrame?: boolean;
};

export function MediaControls({ controller, markers = [], sourceFrame, onStepSourceFrame, unavailableFrame = false }: Props) {
  const { state, togglePlay, commitSeek, previewSeek, setMuted, setPlaybackRate, setQuality } = controller;
  const qualityOptions: MediaQuality[] = controller.availableQualities ?? ["auto"];
  return <div className="ice-media-controls">
    <MediaTimeline duration={state.duration} currentTime={state.currentTime} previewTime={state.previewTime} buffered={state.buffered} markers={markers} onPreview={previewSeek} onCommit={commitSeek} />
    <div className="ice-media-controls__row">
      <Button aria-label={state.paused ? "\u64ad\u653e" : "\u6682\u505c"} onClick={() => void togglePlay()}>{state.paused ? "\u64ad\u653e" : "\u6682\u505c"}</Button>
      <Button aria-label="\u540e\u9000\u4e94\u79d2" onClick={() => commitSeek(state.currentTime - 5)}> -5s </Button>
      <Button aria-label="\u524d\u8fdb\u4e94\u79d2" onClick={() => commitSeek(state.currentTime + 5)}> +5s </Button>
      {onStepSourceFrame ? <><Button aria-label="Previous source frame" onClick={() => onStepSourceFrame(-1)}>Prev frame</Button><Button aria-label="Next source frame" onClick={() => onStepSourceFrame(1)}>Next frame</Button></> : null}
      <span className="ice-media-controls__time">{formatTime(state.previewTime ?? state.currentTime)} / {formatTime(state.duration)}</span>
      {sourceFrame ? <output className="ice-media-controls__source-frame" aria-live="polite">PTS {sourceFrame.pts.toFixed(6)} / frame {sourceFrame.sourceFrameIndex}</output> : null}
      <Button aria-label={state.muted ? "\u53d6\u6d88\u9759\u97f3" : "\u9759\u97f3"} onClick={() => setMuted(!state.muted)}>{state.muted ? "\u53d6\u6d88\u9759\u97f3" : "\u9759\u97f3"}</Button>
      <label className="ice-media-controls__select">
        <span className="sr-only">Playback speed</span>
        <select aria-label="Playback speed" value={String(state.playbackRate)} onChange={(event) => setPlaybackRate(Number(event.target.value))}>
          {[0.5, 0.75, 1, 1.25, 1.5, 2].map((value) => <option key={value} value={value}>{value}x</option>)}
        </select>
      </label>
      <label className="ice-media-controls__select">
        <span className="sr-only">Video quality</span>
        <select aria-label="Video quality" value={state.quality} onChange={(event) => void setQuality(event.target.value as MediaQuality)}>
          {qualityOptions.map((quality) => <option key={quality} value={quality}>{quality === "auto" ? "Auto" : quality}</option>)}
        </select>
      </label>
      {markers.map((marker) => <Button key={marker.id} aria-label={`\u8df3\u5230${marker.label}`} onClick={() => commitSeek(marker.timestamp)}>{marker.label}</Button>)}
    </div>
    {state.buffering ? <span className="ice-media-controls__loading">Buffering...</span> : null}
    {state.error ? <span role="alert" className="ice-media-controls__error">{state.error}</span> : null}
    {unavailableFrame ? <span role="alert" className="ice-media-controls__error">The requested source frame is unavailable; no changes were saved.</span> : null}
  </div>;
}
