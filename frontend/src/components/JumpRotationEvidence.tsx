import { useState } from "react";
import type { AnalysisDetail, JumpProjectionPoint } from "../api/client";
import { formatKeyframeTimestamp, jumpStageSeek } from "../utils/keyframeEvidence";
import SavedJumpFrame from "./SavedJumpFrame";

type Props = { analysis: AnalysisDetail; canSeek: boolean; onSeek: (time: number) => void };

export default function JumpRotationEvidence(props: Props) {
  return <RotationSelection key={props.analysis.id} {...props} />;
}

function RotationSelection({ analysis, canSeek, onSeek }: Props) {
  const node = analysis.bio_data?.jump_stages?.rotation;
  const evidence = node?.evidence;
  const candidate = node?.status === "candidate";
  const sequences = candidate ? [{ support_frames: evidence?.support_frames ?? [] }] : evidence?.observation_sequences ?? [];
  const [selection, setSelection] = useState<{ analysis: string; sequence: number; frame: string } | null>(null);
  const sequence = selection?.analysis === analysis.id ? selection.sequence : 0;
  const refs = (sequences[sequence]?.support_frames ?? []).filter(p => p.image_ref?.frame_id === p.frame_id);
  const selected = selection?.analysis === analysis.id ? refs.find(p => p.frame_id === selection.frame) ?? refs[0] : refs.find(p => p.frame_id === node?.frame_id) ?? refs[0];
  const target = (p: JumpProjectionPoint) => jumpStageSeek(analysis, { ...p, status: "candidate" });
  const choose = (p: JumpProjectionPoint) => setSelection({ analysis: analysis.id, sequence, frame: p.frame_id });
  const interval = evidence?.support_interval;
  const reason = !canSeek ? "当前为图片查看模式" : selected ? target(selected).reason : null;
  return <section aria-label="旋转支持原帧" className="mt-3 space-y-2 text-sm">
    <p>{candidate ? "旋转候选：肩髋变窄或变宽与双侧面部朝向投影连续相容。" : "旋转证据不足；可用的局部片段仅表示观察到投影信号。"}</p>
    <p>这是二维投影候选，无法排除视角变化或头部转动；未确认空中旋转，不提供方向、三维角度或完整周数。</p>
    {interval ? <p>支持区间（分析时间）：{formatKeyframeTimestamp(interval.start)}–{formatKeyframeTimestamp(interval.end)}；播放时间：{formatKeyframeTimestamp(interval.playback_start ?? null)}–{formatKeyframeTimestamp(interval.playback_end ?? null)}。区间依附起落候选，不是确认腾空时段。</p> : <p>缺少相容的起落候选或连续多信号支持，未生成旋转时段。</p>}
    {!candidate && sequences.length > 0 ? <div aria-label="局部投影观察片段">{sequences.map((_,i) => <button key={i} type="button" aria-pressed={i===sequence} onClick={() => setSelection({ analysis: analysis.id, sequence:i, frame:sequences[i].support_frames[0]?.frame_id ?? "" })}>观察片段 {i+1}</button>)}</div> : null}
    <div className="flex flex-wrap gap-2">{refs.map(p => <button type="button" key={p.frame_id} aria-pressed={p.frame_id===selected?.frame_id} onClick={() => choose(p)} className="rounded border px-2 py-1">{candidate ? "旋转支持帧 " : "投影观察帧 "}{p.frame_id}{p.frame_id===node?.frame_id ? "（代表帧）" : ""}</button>)}</div>
    {selected ? <figure>
      <SavedJumpFrame key={selected.frame_id} analysisId={analysis.id} frameId={selected.frame_id} alt={"旋转支持原帧 "+selected.frame_id}>
        {({ status, isReady }) => <>
      <figcaption>{selected.frame_id} · 分析 {formatKeyframeTimestamp(selected.analysis_timestamp)} · 播放 {formatKeyframeTimestamp(selected.playback_timestamp)} · 连续段 {selected.segment_id}</figcaption>
      {status !== "ready" ? <p>{status === "error" ? "当前原帧不可用，无法定位此图视频" : "等待当前原帧加载，暂不定位视频"}</p> : reason ? <p>可以查看原帧，但无法定位视频：{reason}</p> : <button type="button" onClick={() => { const time=target(selected).time; if (isReady() && canSeek && time!=null) onSeek(time); }}>定位旋转支持帧视频</button>}
        </>}
      </SavedJumpFrame>
      <details><summary>当前帧依据</summary><p>源PTS {selected.source_pts ?? "未知"} / {selected.source_time_base ?? "未知"}；来源 {selected.time_source}；人物 {selected.identity_id ?? selected.tracker_id ?? "未知"}；事件 {selected.event_id ?? "未单列"}</p><pre>{JSON.stringify(selected.signals,null,2)}</pre></details>
    </figure> : <p>没有可查看的合法旋转支持原帧。{node?.reason ?? "旧记录未保存旋转证据"}</p>}
    <details><summary>旋转候选依据与拒绝原因</summary><p>代表帧取连续支持中多信号变化最大的区间终点；未按中间帧或固定百分位选择。</p><pre>{JSON.stringify(evidence ?? { reason:node?.reason },null,2)}</pre></details>
  </section>;
}
