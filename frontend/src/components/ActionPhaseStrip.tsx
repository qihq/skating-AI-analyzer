import JumpRotationEvidence from "./JumpRotationEvidence";
import JumpProjection from "./JumpProjection";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisDetail, PoseResponse } from "../api/client";
import type { ExperienceEvent, KeyMomentV2, ProfileMomentKey } from "../analysis-v2/contracts";
import { fetchAnalysisSourceFrameImage } from "../analysis-v2/api";
import { MOMENT_LABELS, momentMarkers, orderedMoments } from "../analysis-v2/momentSelectors";
import { IceMediaPlayer, type IceMediaPlayerHandle } from "../media/IceMediaPlayer";
import { analysisMediaMarkers } from "../media/analysisMarkers";
import { buildCurrentKeyframeEvidenceItems, hasCurrentJumpStages, formatKeyframeTimestamp, keyframeConfidenceLabel } from "../utils/keyframeEvidence";
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
  status: string | null;
  playbackTimestamp?: number | null;
  seekTimestamp?: number | null;
  seekReason?: string | null;
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
    source: moment.provenance.includes("source_pts") ? "原视频精确帧" : "当前复盘证据",
    status: moment.status,
    confidence: moment.status === "unavailable" ? null : moment.confidence,
    reason: moment.status === "unavailable" ? moment.warnings[0] ?? "证据不足" : null,
    warnings: moment.warnings,
  };
}

export default function ActionPhaseStrip({ analysis, analysisId, pose, event, showVideo = true, selectedMomentKey, onSelectMoment, parentPin, initialSeekPts = null }: Props) {
  const isStageReplay = !event && !!analysis && hasCurrentJumpStages(analysis);
  const [showSkeleton, setShowSkeleton] = useState(true);
  const playerRef = useRef<IceMediaPlayerHandle | null>(null);
  const items = useMemo<PhaseItem[]>(() => {
    if (event) return orderedMoments(event).map(v2Item);
    if (!analysis || analysis.facts_authority === "v2") return [];
    return buildCurrentKeyframeEvidenceItems(analysis).map((item) => ({ ...item, sourceFrameIndex: null, endTimestamp: null, status: isStageReplay ? item.status : "legacy", warnings: item.reason ? [item.reason] : [] }));
  }, [analysis, event, isStageReplay]);
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
        <p className="mt-2 text-sm leading-6 text-slate-500">{isStageReplay ? "五节点按保存状态和证据显示；可用的起跳、最高点和落冰仍是候选，未确认接触。缺失、不适用和尚未实现的节点分别标注。" : isV2 ? "所有标记都来自原视频时间戳；候选画面只用于复核，不会直接成为准确时刻。" : "按当前动作类型展示已有关键帧与时间标记。"}</p>
        {event?.moments ? <p className="mt-2 text-xs text-slate-500" role="status">证据覆盖：{event.moments.completeness} · 口径 {event.moments.definitionVersion}</p> : event ? <p className="mt-2 text-sm text-amber-700" role="status">这段动作尚无可用的技术时刻，也不会用历史关键帧补齐。</p> : null}
      </div>
      {isStageReplay ? <label className="mt-3 block text-sm"><input type="checkbox" checked={showSkeleton} onChange={e => setShowSkeleton(e.target.checked)} /> 显示已有骨架（保留质量与坐标标记）</label> : null}
      {event?.rotation ? <div className="mt-4"><RotationEstimateCard rotation={event.rotation} /></div> : null}
      {showVideo && resolvedAnalysisId ? (
        <div className="mt-5 overflow-hidden rounded-[22px] bg-slate-950">
          <IceMediaPlayer ref={playerRef} manifest={analysis?.media_manifest} fallbackSrc={`/api/analysis/${resolvedAnalysisId}/video`} markers={markers} seekTime={initialSeekPts != null && Number.isFinite(initialSeekPts) ? Math.max(0, Math.min(initialSeekPts, analysis?.source_duration_sec ?? analysis?.media_manifest?.source_timeline?.duration_sec ?? Infinity)) : null} />
        </div>
      ) : null}
      <div className="mt-5 flex snap-x gap-4 overflow-x-auto pb-2 tablet:grid tablet:grid-cols-3 tablet:overflow-visible">
        {items.map((item) => {
          const frame = item.frameId ? frames.find((candidate) => frameKey(candidate.frame) === frameKey(item.frameId!)) ?? null : null;
          const frameUrl = analysis?.bio_data?.jump_stage_contract === "tal-evidence.v1" ? item.imageUrl : frame && pose ? pose.frame_urls[frame.frame] ?? item.imageUrl : item.imageUrl ?? (item.sourceFrameIndex != null ? sourceFrameUrls[item.sourceFrameIndex] ?? null : null);
          const timestampLabel = item.timestamp == null ? "不可用" : item.endTimestamp != null ? `${formatKeyframeTimestamp(item.timestamp)}–${formatKeyframeTimestamp(item.endTimestamp)}` : formatKeyframeTimestamp(item.timestamp);
          const seekTime = isStageReplay ? item.seekTimestamp ?? null : item.timestamp;
          const unavailable = isStageReplay ? seekTime == null : item.status === "unavailable" || item.timestamp == null;
          return (
            <article key={item.key} aria-current={selectedMomentKey === item.key ? "true" : undefined} className="min-w-[82%] snap-start overflow-hidden rounded-[22px] border border-slate-200 bg-white phone:min-w-[68%] tablet:min-w-0">
              <PoseFrameCanvas frame={isStageReplay && !showSkeleton ? null : frame} frameUrl={frameUrl} unavailableLabel={isStageReplay ? "原帧不可用" : undefined} connections={pose?.connections ?? []} alt={`${item.label}关键帧`} />
              <div className="p-4">
                <h3 className="text-lg font-semibold text-slate-900">{item.label}</h3>
                {isStageReplay ? <div className="mt-2 space-y-1 text-xs text-slate-600">
                  <p>{stageStatusLabel(item.status)}</p>
                  <p>分析时间：{timestampLabel} · 视频播放时间：{formatKeyframeTimestamp(item.playbackTimestamp ?? null)}</p>
                  <p>{stageReason(item.reason)}</p>
                  {item.seekReason ? <p>{item.seekReason}</p> : null}
                  <details><summary>保存依据</summary>{item.reason} · {item.frameId ?? "无原帧引用"} · {item.source}</details>
                </div> : unavailable ? <p className="mt-2 text-sm text-amber-700">不可用：{item.reason ?? "当前画面无法可靠定位"}</p> : <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500"><span>{timestampLabel}</span><span>{item.source}</span><span>{keyframeConfidenceLabel(item.confidence) ?? "置信度暂无"}</span>{item.sourceFrameIndex != null ? <span>源帧 {item.sourceFrameIndex}</span> : null}</div>}
                {isStageReplay && item.key === "rotation" && analysis ? <JumpRotationEvidence key={analysis.id} analysis={analysis} canSeek={showVideo} onSeek={time => playerRef.current?.seek(time, { play: true })} /> : null}
                {item.status === "ambiguous" ? <p className="mt-2 text-xs text-amber-700">存在相近候选，需要家长确认后才能用于下游媒体。</p> : null}
                <button
                  type="button"
                  aria-label={`查看${item.label} ${timestampLabel}`}
                  disabled={unavailable || !showVideo}
                  onClick={() => {
                    if (seekTime != null) playerRef.current?.seek(seekTime, { play: true });
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
      {isStageReplay && analysis ? <><JumpMeasurements analysis={analysis} /><JumpProjection analysis={analysis} canSeek={showVideo} onSeek={time => playerRef.current?.seek(time, { play: true })} /></> : null}
    </section>
  );
}

function stageStatusLabel(status: string | null) {
  return ({candidate:"候选，未确认接触",unavailable:"证据不足",not_implemented:"尚未实现",not_applicable:"不适用"} as Record<string,string>)[status ?? ""] ?? "证据不足";
}
function stageReason(reason: string | null) {
  if (!reason) return "阶段证据不足";
  if (reason.includes("not_applicable_for_profile")) return "当前动作类型不适用跳跃节点";
  if (reason.includes("not_implemented")) return "对应证据提取器尚未实现";
  if (reason.includes("multicue_projected_turn")) return "肩髋与面部方向投影的旋转候选；视角歧义保留，未确认空中旋转";
  if (reason.includes("no_continuous_multicue")) return "缺少连续、相容的肩髋和面部方向投影支持";
  if (reason.includes("projected_arm_contraction")) return "双臂向躯干轴靠拢的二维投影候选；不代表已确认空中或全身收紧";
  if (reason.includes("no_sustained")) return "缺少连续、双侧有效的投影收拢变化";
  if (reason.includes("not_confirmed_contact")) return "几何候选，缺少独立起落接触依据";
  if (reason.includes("support") || reason.includes("bound_time")) return "支持帧或时间核验未通过";
  return reason;
}
function JumpMeasurements({analysis}:{analysis:AnalysisDetail}) {
  const labels:Record<string,string>={candidate_interval:"起落候选区间",air_time:"确认腾空时间",projected_rise:"投影上升量",physical_height:"物理高度",horizontal_distance:"水平距离",rotation_count:"完整旋转周数"};
  const reasons:Record<string,string>={candidate_interval:"需要可比较的阶段时间与速度依据",air_time:"缺少独立接触边界与速度依据",projected_rise:"缺少可比较坐标支持与相机控制",physical_height:"缺少物理标定、参考平面和测量方法",horizontal_distance:"缺少地面映射、尺度与相机控制",rotation_count:"缺少连续且无歧义的旋转证据"};
  return <div className="mt-4 text-sm" aria-label="跳跃测量可用性"><p>起落候选区间使用分析时间，不是确认腾空时间；视频播放时间另列。</p><ul>{Object.entries(labels).map(([key,label])=>{
    const value=analysis.bio_data?.jump_measurements?.[key];
    const available=key==="candidate_interval" && value?.status==="candidate" && typeof value.value==="number" && Number.isFinite(value.value);
    return <li key={key}>{label}：{available ? formatKeyframeTimestamp(value!.value) + "（候选）" : value?.status==="not_applicable" ? "不适用" : "不可用"} · {available ? "候选间隔，不能作为腾空时长" : reasons[key]}<details><summary>测量依据</summary>{value?.reason ?? "测量证据未保存"}</details></li>;
  })}</ul></div>;
}
