import { useMemo, useRef, useState } from "react";

import { AnalysisDetail } from "../api/client";
import {
  buildCurrentKeyframeEvidenceItems,
  buildDraftKeyframeEvidenceItems,
  buildSemanticKeyframeEvidenceItems,
  formatKeyframeTimestamp,
  keyframeConfidenceLabel,
  type KeyframeEvidenceItem,
  type KeyframeKey,
  type KeyframeSyncPatch,
} from "../utils/keyframeEvidence";

export type { KeyframeSyncPatch } from "../utils/keyframeEvidence";

type DraftKeyframes = Record<KeyframeKey, string>;
type SourceId = "current" | "selected" | "partial" | "draft";

type KeyframeEvidenceSource = {
  id: SourceId;
  label: string;
  items: KeyframeEvidenceItem[];
};

type KeyframeEvidencePanelProps = {
  analysis: AnalysisDetail;
  draftKeyframes: DraftKeyframes;
  onSyncFrames: (patch: KeyframeSyncPatch, sourceLabel: string) => void;
  layout?: "sidebar" | "wide";
};

export default function KeyframeEvidencePanel({ analysis, draftKeyframes, onSyncFrames, layout = "sidebar" }: KeyframeEvidencePanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [activeSourceId, setActiveSourceId] = useState<SourceId>("current");
  const [imageErrors, setImageErrors] = useState<Record<string, boolean>>({});
  const [videoError, setVideoError] = useState(false);

  const sources = useMemo<KeyframeEvidenceSource[]>(() => {
    const selected = analysis.video_temporal_diagnostics?.selected_semantic_frames ?? [];
    const partial = analysis.video_temporal_diagnostics?.partial_semantic_frames ?? [];
    return [
      { id: "current", label: "当前有效", items: buildCurrentKeyframeEvidenceItems(analysis) },
      { id: "selected", label: "AI 语义候选", items: buildSemanticKeyframeEvidenceItems(analysis, selected, "AI 语义候选") },
      { id: "partial", label: "Partial 候选", items: buildSemanticKeyframeEvidenceItems(analysis, partial, "Partial 候选") },
      { id: "draft", label: "待确认草稿", items: buildDraftKeyframeEvidenceItems(analysis, draftKeyframes) },
    ];
  }, [analysis, draftKeyframes]);

  const activeSource = sources.find((source) => source.id === activeSourceId) ?? sources[0];
  const availableCount = activeSource.items.filter((item) => item.value).length;
  const videoSrc = `/api/analysis/${encodeURIComponent(analysis.id)}/video`;
  const sourceTabsClass = layout === "wide"
    ? "mt-4 grid grid-cols-2 gap-2 tablet:grid-cols-4"
    : "mt-4 grid grid-cols-2 gap-2 tablet:grid-cols-4 xl:grid-cols-2 wide:grid-cols-4";
  const evidenceCardsClass = layout === "wide"
    ? "mt-4 grid gap-3 tablet:grid-cols-3"
    : "mt-4 flex snap-x gap-3 overflow-x-auto pb-1 tablet:grid tablet:grid-cols-3 tablet:overflow-visible xl:grid-cols-1 wide:grid-cols-3";

  const seekTo = (timestamp: number | null) => {
    if (timestamp == null || !videoRef.current) {
      return;
    }
    videoRef.current.currentTime = Math.max(0, timestamp);
  };

  const syncItem = (item: KeyframeEvidenceItem) => {
    if (!item.value) {
      return;
    }
    seekTo(item.timestamp);
    onSyncFrames({ [item.key]: item.value }, `${activeSource.label} ${item.key}`);
  };

  const syncAll = () => {
    const patch = activeSource.items.reduce<KeyframeSyncPatch>((current, item) => {
      if (item.value) {
        current[item.key] = item.value;
      }
      return current;
    }, {});
    if (Object.keys(patch).length) {
      onSyncFrames(patch, activeSource.label);
    }
  };

  return (
    <section className="rounded-[24px] border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-3 phone:flex-row phone:items-start phone:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">关键帧核对台</h3>
          <p className="mt-1 text-xs text-slate-500">{activeSource.label} · {availableCount}/3</p>
        </div>
        <button
          type="button"
          onClick={syncAll}
          disabled={!availableCount}
          className="min-h-[36px] rounded-full border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          同步三帧到 form
        </button>
      </div>

      <div className="mt-4 overflow-hidden rounded-[18px] bg-slate-950">
        {videoError ? (
          <div className="flex aspect-video items-center justify-center px-4 text-center text-xs leading-6 text-slate-300">
            视频暂不可用
          </div>
        ) : (
          <video
            ref={videoRef}
            src={videoSrc}
            controls
            preload="metadata"
            playsInline
            onError={() => setVideoError(true)}
            className="aspect-video w-full bg-slate-950 object-contain"
          />
        )}
      </div>

      <div className={sourceTabsClass}>
        {sources.map((source) => {
          const selected = source.id === activeSource.id;
          return (
            <button
              key={source.id}
              type="button"
              onClick={() => setActiveSourceId(source.id)}
              className={`min-h-[38px] rounded-full border px-3 py-1 text-xs font-semibold transition ${
                selected ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-white"
              }`}
            >
              {source.label}
            </button>
          );
        })}
      </div>

      <div className={evidenceCardsClass}>
        {activeSource.items.map((item) => {
          const imageKey = `${activeSource.id}-${item.key}-${item.frameId ?? item.value}`;
          const imageUnavailable = !item.imageUrl || imageErrors[imageKey];
          const confidence = keyframeConfidenceLabel(item.confidence);
          return (
            <article key={item.key} className="min-w-[190px] snap-start rounded-[20px] border border-slate-200 bg-slate-50 p-3">
              <button
                type="button"
                onClick={() => syncItem(item)}
                disabled={!item.value}
                className="group block w-full overflow-hidden rounded-[16px] bg-slate-950 text-left disabled:cursor-not-allowed"
              >
                <div className="relative aspect-video">
                  {!imageUnavailable ? (
                    <img
                      src={item.imageUrl ?? ""}
                      alt={`${item.key} ${item.value}`}
                      loading="lazy"
                      onError={() => setImageErrors((current) => ({ ...current, [imageKey]: true }))}
                      className="h-full w-full object-contain"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center px-3 text-center text-xs leading-5 text-slate-400">
                      {item.value || "暂无帧图"}
                    </div>
                  )}
                  <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-1 text-xs font-bold text-slate-900 shadow-sm">
                    {item.key}
                  </span>
                  {item.timestamp != null ? (
                    <span className="absolute bottom-2 right-2 rounded-full bg-slate-950/78 px-2 py-1 text-[11px] font-semibold text-white">
                      {formatKeyframeTimestamp(item.timestamp)}
                    </span>
                  ) : null}
                </div>
              </button>

              <div className="mt-3 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                    <p className="mt-1 truncate text-xs font-medium text-slate-500">{item.value || "--"}</p>
                  </div>
                  {confidence ? <span className="shrink-0 rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-slate-500">{confidence}</span> : null}
                </div>
                <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-slate-500">
                  <span className="rounded-full bg-white px-2 py-1">{formatKeyframeTimestamp(item.timestamp)}</span>
                  {item.status ? <span className="rounded-full bg-white px-2 py-1">{item.status}</span> : null}
                </div>
                {item.reason ? <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-slate-500">{item.reason}</p> : null}
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => syncItem(item)}
                    disabled={!item.value}
                    className="min-h-[34px] flex-1 rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:bg-teal-50 hover:text-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    同步 {item.key}
                  </button>
                  <button
                    type="button"
                    onClick={() => seekTo(item.timestamp)}
                    disabled={item.timestamp == null || videoError}
                    className="min-h-[34px] rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    定位
                  </button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
