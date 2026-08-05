import { useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisDetail, PoseResponse } from "../api/client";
import type { ExperienceEvent, KeyMomentV2, ProfileMomentKey } from "../analysis-v2/contracts";
import { fetchAnalysisSourceFrameImage } from "../analysis-v2/api";
import { MOMENT_LABELS, momentMarkers, orderedMoments } from "../analysis-v2/momentSelectors";
import { IceMediaPlayer, type IceMediaPlayerHandle } from "../media/IceMediaPlayer";
import { analysisMediaMarkers } from "../media/analysisMarkers";
import { buildCurrentKeyframeEvidenceItems, formatKeyframeTimestamp, keyframeConfidenceLabel } from "../utils/keyframeEvidence";
import PoseFrameCanvas from "./PoseFrameCanvas";
import RotationEstimateCard from "../analysis-v2/components/RotationEstimateCard";

type Props = {
  analysis?: AnalysisDetail | null;
  analysisId?: string;
  pose: PoseResponse | null;
  event?: ExperienceEvent | null;
  showVideo?: boolean;
  selectedMomentKey?: ProfileMomentKey | null;
  onSelectMoment?: (key: ProfileMomentKey) => void;
  parentPin?: string | null;
  initialSeekPts?: number | null;
};

type PhaseItem = {
  key: string;
  label: string;
  frameId: string | null;
  sourceFrameIndex: number | null;
  imageUrl: string | null;
  timestamp: number | null;
  endTimestamp: number | null;
  source: string;
  status: "confirmed" | "ambiguous" | "unavailable" | "legacy";
  confidence: number | null;
  reason: string | null;
  warnings: string[];
};

function frameKey(value: string) {
  return value.replace(/\.(jpe?g|png|webp)$/i, "").toLowerCase();
}

function v2Item(moment: KeyMomentV2): PhaseItem {
  return {
    key: moment.semanticKey,
    label: MOMENT_LABELS[moment.semanticKey],
    frameId: null,
    sourceFrameIndex: moment.sourceFrameIndex,
    imageUrl: null,
    timestamp: moment.ptsSec,
    endTimestamp: moment.endPtsSec,
    source: moment.provenance.includes("source_pts") ? "原视频精确帧" : "V2 技术证据",
    status: moment.status,
    confidence: moment.status === "unavailable" ? null : moment.confidence,
    reason: moment.status === "unavailable" ? moment.warnings[0] ?? "证据不足" : null,
    warnings: moment.warnings,
  };
}

export default function ActionPhaseStrip({ analysis, analysisId, pose, event, showVideo = true, selectedMomentKey, onSelectMoment, parentPin, initialSeekPts = null }: Props) {
  const playerRef = useRef<IceMediaPlayerHandle | null>(null);
  const items = useMemo<PhaseItem[]>(() => {
    if (event) return orderedMoments(event).map(v2Item);
    if (!analysis) return [];
    return buildCurrentKeyframeEvidenceItems(analysis).map((item) => ({ ...item, sourceFrameIndex: null, endTimestamp: null, status: "legacy", warnings: item.reason ? [item.reason] : [] }));
  }, [analysis, event]);
  const frames = pose?.frames ?? [];
  const markers = event ? momentMarkers(event.moments) : analysis ? analysisMediaMarkers(analysis) : [];
  const resolvedAnalysisId = analysis?.id ?? analysisId;
  const isV2 = Boolean(event);
  const [sourceFrameUrls, setSourceFrameUrls] = useState<Record<number, string>>({});
  useEffect(() => {
    if (!isV2 || !parentPin || !resolvedAnalysisId) { setSourceFrameUrls({}); return; }
    let cancelled = false;
    const indexes = [...new Set(items.flatMap((item) => item.sourceFrameIndex == null ? [] : [item.sourceFrameIndex]))];
    const urls: string[] = [];
    void Promise.all(indexes.map(async (index) => { const url = await fetchAnalysisSourceFrameImage(parentPin, resolvedAnalysisId, index); urls.push(url); return [index, url] as const; }))
      .then((entries) => { if (!cancelled) setSourceFrameUrls(Object.fromEntries(entries)); })
      .catch(() => { if (!cancelled) setSourceFrameUrls({}); });
    return () => { cancelled = true; urls.forEach((url) => URL.revokeObjectURL(url)); };
  }, [isV2, items, parentPin, resolvedAnalysisId]);

  return (
    <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-6" aria-labelledby="action-phase-title" aria-busy={event != null && !event.moments}>
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Key Moments</p>
        <h2 id="action-phase-title" className="mt-2 text-2xl font-semibold text-slate-900">关键技术时刻</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">{isV2 ? "所有标记都来自原视频 source PTS；语义关键帧只用于复核，不会直接成为时间真值。" : "历史分析按原有 T/A/L 快照显示，不改写旧定义。"}</p>
        {event?.moments ? <p className="mt-2 text-xs text-slate-500" role="status">完整性：{event.moments.completeness} · 定义 {event.moments.definitionVersion}</p> : event ? <p className="mt-2 text-sm text-amber-700" role="status">此事件尚无可用的 V2 技术时刻，不使用历史关键帧补齐。</p> : null}
      </div>
      {event?.rotation ? <div className="mt-4"><RotationEstimateCard rotation={event.rotation} /></div> : null}
      {showVideo && resolvedAnalysisId ? (
        <div className="mt-5 overflow-hidden rounded-[22px] bg-slate-950">
          <IceMediaPlayer ref={playerRef} manifest={analysis?.media_manifest} fallbackSrc={`/api/analysis/${resolvedAnalysisId}/video`} markers={markers} seekTime={initialSeekPts} />
        </div>
      ) : null}
      <div className="mt-5 flex snap-x gap-4 overflow-x-auto pb-2 tablet:grid tablet:grid-cols-3 tablet:overflow-visible">
        {items.map((item) => {
          const frame = item.frameId ? frames.find((candidate) => frameKey(candidate.frame) === frameKey(item.frameId!)) ?? null : null;
          const frameUrl = frame && pose ? pose.frame_urls[frame.frame] ?? item.imageUrl : item.imageUrl ?? (item.sourceFrameIndex != null ? sourceFrameUrls[item.sourceFrameIndex] ?? null : null);
          const timestampLabel = item.timestamp == null ? "不可用" : item.endTimestamp != null ? `${formatKeyframeTimestamp(item.timestamp)}–${formatKeyframeTimestamp(item.endTimestamp)}` : formatKeyframeTimestamp(item.timestamp);
          const unavailable = item.status === "unavailable" || item.timestamp == null;
          return (
            <article key={item.key} aria-current={selectedMomentKey === item.key ? "true" : undefined} className="min-w-[82%] snap-start overflow-hidden rounded-[22px] border border-slate-200 bg-white phone:min-w-[68%] tablet:min-w-0">
              <PoseFrameCanvas frame={frame} frameUrl={frameUrl} connections={pose?.connections ?? []} alt={`${item.label}关键帧`} />
              <div className="p-4">
                <h3 className="text-lg font-semibold text-slate-900">{item.label}</h3>
                {unavailable ? <p className="mt-2 text-sm text-amber-700">不可用：{item.reason ?? "当前画面无法可靠定位"}</p> : <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500"><span>{timestampLabel}</span><span>{item.source}</span><span>{keyframeConfidenceLabel(item.confidence) ?? "置信度暂无"}</span>{item.sourceFrameIndex != null ? <span>源帧 {item.sourceFrameIndex}</span> : null}</div>}
                {item.status === "ambiguous" ? <p className="mt-2 text-xs text-amber-700">存在相近候选，需要家长确认后才能用于下游媒体。</p> : null}
                <button
                  type="button"
                  aria-label={`查看${item.label} ${timestampLabel}`}
                  disabled={unavailable || !showVideo}
                  onClick={() => {
                    if (item.timestamp != null) playerRef.current?.seek(item.timestamp, { play: true });
                    if (isV2) onSelectMoment?.(item.key as ProfileMomentKey);
                  }}
                  className="mt-3 min-h-[44px] w-full rounded-full bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-600 disabled:opacity-45"
                >
                  {unavailable ? "此阶段不可定位" : "跳到这一刻"}
                </button>
              </div>
            </article>
          );
        })}
        {!items.length ? <p className="min-h-[88px] rounded-[22px] border border-dashed border-slate-300 p-4 text-sm text-slate-500">关键时刻不可用；未生成任何合成 marker。</p> : null}
      </div>
    </section>
  );
}
