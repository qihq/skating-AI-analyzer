import SavedJumpFrame from "./SavedJumpFrame";
import { useState } from "react";
import type { AnalysisDetail, JumpProjectionPoint } from "../api/client";
import { jumpStageSeek, formatKeyframeTimestamp } from "../utils/keyframeEvidence";

type Props = { analysis: AnalysisDetail; onSeek: (time: number) => void; canSeek?: boolean };

/** A full-image coordinate plot, never a fitted flight path or physical COM. */
export default function JumpProjection(props: Props) {
  return <ProjectionSelection key={props.analysis.id} {...props} />;
}

function ProjectionSelection({ analysis, onSeek, canSeek = true }: Props) {
  const trajectory = analysis.bio_data?.jump_measurements?.trajectory;
  const points = trajectory?.points ?? [];
  const segments = trajectory?.segments ?? [];
  const [selection, setSelection] = useState<{ frame: string; request: number } | null>(null);
  const selected = points.find(p => p.frame_id === selection?.frame) ?? points[0];
  const seek = (p: JumpProjectionPoint) => jumpStageSeek(analysis, { ...p, status: "candidate" });
  const select = (p: JumpProjectionPoint) => {
    setSelection(previous => ({ frame: p.frame_id, request: (previous?.request ?? 0) + 1 }));
  };
  const gaps = trajectory?.slots?.filter(s => s.status !== "available") ?? [];
  return <section className="mt-5 space-y-3" aria-label="髋中点投影轨迹">
    <h3 className="text-lg font-semibold">髋中点投影轨迹（未消除镜头运动）</h3>
    <p className="text-sm">参考点为左右髋中点，坐标按原始保存图像宽高归一化，x向右、y向下。缺口断开；不能据此确认腾空、物理跳高或滑行距离。</p>
    {trajectory?.status === "available" && points.length ? <>
      <p>{points.length} 个有效点 · {segments.length} 个连续段 · {gaps.length} 个不可用观测。可点击或用键盘选择保存原帧；当前图片加载成功且播放映射可靠时定位视频。</p>
      {segments.map(segment => {
        const group = segment.point_indices.map(i => points[i]).filter((p): p is JumpProjectionPoint => !!p && p.segment_id === segment.segment_id && Number.isFinite(p.x) && Number.isFinite(p.y));
        if (!group.length) return null;
        const { image_width: width, image_height: height } = group[0].geometry;
        const coordinates = group.map(p => `${p.x * width},${p.y * height}`).join(" ");
        return <svg key={segment.segment_id} viewBox={`0 0 ${width} ${height}`} className="w-full max-w-xl border border-slate-200" aria-label={`连续段 ${segment.segment_id}`}>
          {group.length > 1 ? <polyline data-testid="trajectory-segment" points={coordinates} fill="none" stroke="#2563eb" strokeWidth={width / 300} /> : null}
          {group.map(p => {
            const target = seek(p); const disabled = target.time == null || !canSeek;
            return <circle key={p.pose_index} cx={p.x * width} cy={p.y * height} r={width / 80}
              fill={disabled ? "#64748b" : "#2563eb"} role="button" tabIndex={0} aria-pressed={selected?.frame_id === p.frame_id}
              aria-label={"轨迹点 " + p.frame_id} onClick={() => select(p)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(p); } }}>
              <title>{p.frame_id} · 播放 {formatKeyframeTimestamp(p.playback_timestamp)} · {target.reason ?? "图片加载成功后定位视频"}</title>
            </circle>;
          })}
        </svg>;
      })}
      {selected ? <figure className="max-w-xl">
        <SavedJumpFrame key={JSON.stringify([selected.frame_id, selection?.request ?? 0])}
          analysisId={analysis.id} frameId={selected.frame_id} alt={"髋轨迹原帧 " + selected.frame_id}
          onReady={() => {
            const time = seek(selected).time;
            if (selection && canSeek && time != null) onSeek(time);
          }}>
          {({ status }) => <figcaption>{selected.frame_id} · 分析 {formatKeyframeTimestamp(selected.analysis_timestamp)} · 播放 {formatKeyframeTimestamp(selected.playback_timestamp)} · {status === "ready"
            ? !canSeek ? "可以查看原帧，但无法定位视频：当前为图片查看模式" : seek(selected).reason ? "可以查看原帧，但无法定位视频：" + seek(selected).reason : "可定位已有视频"
            : status === "error" ? "当前原帧不可用，无法定位此图视频" : "等待当前原帧加载，暂不定位视频"}</figcaption>}
        </SavedJumpFrame>
      </figure> : null}
    </> : <p>轨迹不可用：没有通过身份、质量、时间及原图坐标校验的髋中点。{trajectory?.reason ?? "旧记录未保存轨迹"}</p>}
    <details><summary>逐点依据与缺口原因</summary><ul>
      {points.map(p => <li key={p.pose_index}>{p.frame_id} · 连续段 {p.segment_id} · PTS {p.source_pts ?? "未知"}/{p.source_time_base ?? "未知"} · {p.geometry.image_width}×{p.geometry.image_height} · {seek(p).reason ?? "播放映射可信；仍需当前原帧加载成功"}<pre>{JSON.stringify(p, null, 2)}</pre></li>)}
      {gaps.map(s => <li key={s.pose_index}>{s.frame_id ?? s.pose_index}：{s.reason}</li>)}
    </ul></details>
  </section>;
}
