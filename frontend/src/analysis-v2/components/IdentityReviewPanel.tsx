import { useEffect, useState } from "react";

import { confirmIdentityAnchorRevision, fetchIdentityTimeline, previewIdentityAnchorRevision } from "../api";
import type { IdentityRevisionPreview, IdentityTimeline } from "../contracts";

type Props = { analysisId: string; parentPin: string };

export default function IdentityReviewPanel({ analysisId, parentPin }: Props) {
  const [timeline, setTimeline] = useState<IdentityTimeline | null>(null);
  const [frame, setFrame] = useState("0");
  const [pts, setPts] = useState("0");
  const [quality, setQuality] = useState("0.9");
  const [interval, setInterval] = useState("");
  const [preview, setPreview] = useState<IdentityRevisionPreview | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchIdentityTimeline(parentPin, analysisId).then((value) => { if (active) setTimeline(value); }).catch(() => { if (active) setMessage("身份时间线暂时无法读取，请稍后重试。"); });
    return () => { active = false; };
  }, [analysisId, parentPin]);

  const makePreview = async () => {
    const [x, y, width, height] = [0.1, 0.1, 0.2, 0.5] as const;
    const parsedInterval = interval.split(",").map(Number);
    try {
      const next = await previewIdentityAnchorRevision(parentPin, analysisId, { source_frame_index: Number(frame), pts_sec: Number(pts), bbox: [x, y, width, height], annotator: "parent-review", quality_score: Number(quality), expected_revision: timeline?.anchor_revisions.slice(-1)[0]?.revision ?? 1, invalidated_interval: parsedInterval.length === 2 && parsedInterval.every(Number.isFinite) ? [parsedInterval[0], parsedInterval[1]] : null });
      setPreview(next); setMessage("已生成重算预览；只有因果影响区间会被重算，历史 revision 保留。");
    } catch { setMessage("重算范围或锚点信息无效，请检查后重试。"); }
  };

  const confirmPreview = async () => {
    if (!preview) return;
    const parsedInterval = interval.split(",").map(Number);
    try {
      await confirmIdentityAnchorRevision(parentPin, analysisId, { source_frame_index: preview.anchor.source_frame_index, pts_sec: preview.anchor.pts_sec, bbox: preview.anchor.bbox, annotator: "parent-review", quality_score: preview.anchor.quality_score, expected_revision: preview.current_revision, preview_revision: preview.next_revision, confirmation: "confirm_identity_anchor_revision", invalidated_interval: parsedInterval.length === 2 && parsedInterval.every(Number.isFinite) ? [parsedInterval[0], parsedInterval[1]] : null });
      setMessage("身份锚点已确认并记录 revision；旧时间线与 legacy 结果未被静默修改。 ");
      setTimeline(await fetchIdentityTimeline(parentPin, analysisId));
    } catch { setMessage("身份锚点确认失败，可能是 revision 冲突；请重新加载后再试。"); }
  };

  return <section className="app-card mt-6 p-5" aria-labelledby="identity-review-heading">
    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-600">家长复核 · Shadow only</p>
    <h2 id="identity-review-heading" className="mt-2 text-xl font-semibold text-slate-900">确认主滑手</h2>
    <p className="mt-2 text-sm leading-6 text-slate-600">只有确认身份的片段才会授权姿态和技术结论。低把握、交叉或重新锁定期间会显示“需要确认”，不会用旧框补成确认。</p>
    {timeline ? <dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><div><dt className="text-slate-500">当前状态</dt><dd className="font-semibold">{timeline.state === "confirmed" ? "已确认" : timeline.state === "uncertain" ? "需要确认" : "这段没有跟清楚"}</dd></div><div><dt className="text-slate-500">已确认覆盖</dt><dd className="font-semibold">{Math.round(timeline.confirmed_coverage * 100)}%</dd></div><div><dt className="text-slate-500">冲突区间</dt><dd className="font-semibold">{timeline.conflicts.length}</dd></div><div><dt className="text-slate-500">锚点 revision</dt><dd className="font-semibold">{timeline.anchor_revisions.slice(-1)[0]?.revision ?? 1}</dd></div></dl> : <p className="mt-4 text-sm text-slate-500">还没有可复核的身份时间线。</p>}
    <div className="mt-4 grid gap-3 tablet:grid-cols-3"><label className="text-sm">源帧<input className="mt-1 w-full rounded-xl border p-2" value={frame} onChange={(event) => setFrame(event.target.value)} inputMode="numeric" /></label><label className="text-sm">PTS（秒）<input className="mt-1 w-full rounded-xl border p-2" value={pts} onChange={(event) => setPts(event.target.value)} inputMode="decimal" /></label><label className="text-sm">锚点质量<input className="mt-1 w-full rounded-xl border p-2" value={quality} onChange={(event) => setQuality(event.target.value)} inputMode="decimal" /></label></div>
    <label className="mt-3 block text-sm">预览重算范围（开始秒,结束秒）<input className="mt-1 w-full rounded-xl border p-2" value={interval} onChange={(event) => setInterval(event.target.value)} placeholder="例如 1.2,2.4" /></label>
    <button type="button" className="mt-4 rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white" onClick={() => void makePreview()}>预览锚点重算</button>
    {preview ? <div className="mt-3 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800"><p>revision {preview.next_revision} · 将影响 {preview.invalidated_intervals.length ? preview.invalidated_intervals.map((range) => range.join("–")).join(", ") : "当前锚点附近"} 秒</p><button type="button" className="mt-2 rounded-full bg-emerald-700 px-3 py-1.5 font-semibold text-white" onClick={() => void confirmPreview()}>明确确认这个主滑手锚点</button></div> : null}
    {message ? <p className="mt-3 text-sm text-slate-600" role="status">{message}</p> : null}
  </section>;
}
