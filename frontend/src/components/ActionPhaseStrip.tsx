import { useMemo, useRef, useState } from "react";
import type { AnalysisDetail, PoseResponse } from "../api/client";
import { buildCurrentKeyframeEvidenceItems, formatKeyframeTimestamp, keyframeConfidenceLabel } from "../utils/keyframeEvidence";
import PoseFrameCanvas from "./PoseFrameCanvas";

type Props = {
  analysis: AnalysisDetail;
  pose: PoseResponse | null;
  showVideo?: boolean;
};

function frameKey(value: string) {
  return value.replace(/\.(jpe?g|png|webp)$/i, "").toLowerCase();
}

export default function ActionPhaseStrip({ analysis, pose, showVideo = true }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [draftTime, setDraftTime] = useState<number | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const items = useMemo(() => buildCurrentKeyframeEvidenceItems(analysis), [analysis]);
  const frames = pose?.frames ?? [];
  const displayedTime = draftTime ?? currentTime;

  const commitSeek = (time: number) => {
    const video = videoRef.current;
    if (video) {
      video.currentTime = time;
    }
    setCurrentTime(time);
    setDraftTime(null);
  };

  return (
    <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-6" aria-labelledby="action-phase-title">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Key Moments</p>
        <h2 id="action-phase-title" className="mt-2 text-2xl font-semibold text-slate-900">关键动作阶段</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">这里展示实际姿态证据，不代表标准动作判定。</p>
      </div>
      {showVideo ? (
        <div className="mt-5 overflow-hidden rounded-[22px] bg-slate-950">
          <video
            ref={videoRef}
            data-testid="phase-video"
            playsInline
            preload="metadata"
            src={`/api/analysis/${analysis.id}/video`}
            onLoadedMetadata={(event) => setDuration(event.currentTarget.duration || 0)}
            onTimeUpdate={(event) => {
              if (draftTime == null) setCurrentTime(event.currentTarget.currentTime);
            }}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            className="aspect-video w-full bg-slate-950 object-contain"
          />
          <div className="grid gap-3 border-t border-white/10 bg-slate-900 px-4 py-3 tablet:grid-cols-[auto_minmax(0,1fr)_auto] tablet:items-center">
            <button
              type="button"
              onClick={() => {
                const video = videoRef.current;
                if (!video) return;
                if (video.paused) void video.play().catch(() => undefined);
                else video.pause();
              }}
              className="min-h-[38px] rounded-full bg-white/10 px-4 text-sm font-semibold text-white hover:bg-white/15"
            >
              {isPlaying ? "暂停" : "播放"}
            </button>
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.01}
              value={Math.min(displayedTime, duration || displayedTime)}
              aria-label="视频播放进度"
              onPointerDown={(event) => setDraftTime(Number(event.currentTarget.value))}
              onChange={(event) => setDraftTime(Number(event.currentTarget.value))}
              onPointerUp={(event) => commitSeek(Number(event.currentTarget.value))}
              onPointerCancel={() => setDraftTime(null)}
              onKeyUp={(event) => commitSeek(Number(event.currentTarget.value))}
              className="min-w-0 w-full accent-blue-400"
            />
            <span className="text-sm font-medium text-slate-300 tablet:min-w-[108px] tablet:text-right">
              {displayedTime.toFixed(2)}s / {duration ? duration.toFixed(2) : "--"}s
            </span>
          </div>
        </div>
      ) : null}
      <div className="mt-5 flex snap-x gap-4 overflow-x-auto pb-2 tablet:grid tablet:grid-cols-3 tablet:overflow-visible">
        {items.map((item) => {
          const frame = item.frameId ? frames.find((candidate) => frameKey(candidate.frame) === frameKey(item.frameId!)) ?? null : null;
          const frameUrl = frame && pose ? pose.frame_urls[frame.frame] ?? item.imageUrl : item.imageUrl;
          const timestampLabel = formatKeyframeTimestamp(item.timestamp);
          return (
            <article key={item.key} className="min-w-[82%] snap-start overflow-hidden rounded-[22px] border border-slate-200 bg-white phone:min-w-[68%] tablet:min-w-0">
              <PoseFrameCanvas frame={frame} frameUrl={frameUrl} connections={pose?.connections ?? []} alt={`${item.label}关键帧`} />
              <div className="p-4">
                <h3 className="text-lg font-semibold text-slate-900">{item.label}</h3>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span>{timestampLabel}</span>
                  <span>{item.source}</span>
                  <span>{keyframeConfidenceLabel(item.confidence) ?? "置信度暂无"}</span>
                </div>
                <button
                  type="button"
                  aria-label={`查看${item.label} ${timestampLabel}`}
                  disabled={item.timestamp == null || !showVideo}
                  onClick={() => {
                    if (videoRef.current && item.timestamp != null) {
                      videoRef.current.currentTime = item.timestamp;
                      const playback = videoRef.current.play();
                      if (playback && typeof playback.catch === "function") {
                        void playback.catch(() => undefined);
                      }
                    }
                  }}
                  className="mt-3 min-h-[40px] w-full rounded-full bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-600 disabled:opacity-45"
                >
                  跳到这一刻
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
