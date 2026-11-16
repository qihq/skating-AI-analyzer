import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useAppMode } from "./AppModeContext";
import PoseViewer from "./PoseViewer";
import { confirmSegmentAnchor, fetchSegmentCandidates, fetchSegmentRevision, fetchSegmentRevisionPose,
  fetchSegmentSavedImage, previewSegmentAnchor, type PoseResponse, type SegmentCandidates,
  type SegmentAnchorSelection, type SegmentPreview, type SegmentRevisionDetail } from "../api/client";

const STATUS = {submitted: "已提交", processing: "处理中", success: "辅助结果已保存", insufficient: "证据不足", failed: "处理失败"};

function confirmationKey(): string {
  const source = globalThis.crypto;
  try {
    const key = source?.randomUUID?.();
    if (key && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(key)) return key;
  } catch { /* A supported random source below can still serve HTTP clients. */ }
  if (!source?.getRandomValues) throw new Error("secure_random_unavailable");
  const bytes = source.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16), hex.slice(16,20), hex.slice(20)].join("-");
}

function SavedImage({url, pin}: {url: string; pin: string}) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let cancelled = false; let objectUrl = ""; setSrc("");
    void fetchSegmentSavedImage(url, pin).then(blob => {
      objectUrl = URL.createObjectURL(blob); if (!cancelled) setSrc(objectUrl); else URL.revokeObjectURL(objectUrl);
    }).catch(() => setSrc(""));
    return () => {cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl);};
  }, [url, pin]);
  return src ? <img src={src} alt="失锁段保存图片" className="w-full" /> : <p role="status">保存图片不可用或正在读取</p>;
}

export function SegmentReanchorSelection() {
  const {id} = useParams(); const {parentPin} = useAppMode(); const navigate = useNavigate();
  const [data, setData] = useState<SegmentCandidates | null>(null);
  const [observation, setObservation] = useState<number | null>(null);
  const [segment, setSegment] = useState<number | null>(null);
  const [selection, setSelection] = useState<SegmentAnchorSelection | null>(null);
  const [preview, setPreview] = useState<SegmentPreview | null>(null);
  const [key, setKey] = useState(""); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const generation = useRef(0); const confirming = useRef(false);
  useEffect(() => {
    generation.current++;
    let active = true; setData(null); setSelection(null); setPreview(null); setKey("");
    if (id && parentPin) void fetchSegmentCandidates(id, parentPin).then(d => {if (active) setData(d);})
      .catch(() => {if (active) setMessage("保存候选不可用，请重新读取或检查家长权限。");});
    return () => {active = false; generation.current++;};
  }, [id, parentPin]);
  const current = data?.observations.find(r => r.observation_index === observation && r.segment === segment);
  const reset = () => {generation.current++;setSelection(null); setPreview(null); setKey(""); setMessage("");};
  return <section aria-label="失锁段重新选定目标" className="app-card p-6">
    <h2>失锁段重新选定目标</h2>
    <p>人工选择仅指定本段目标。自动结果保留；连续三帧和逐帧检查通过后才产生辅助骨架，确认前帧不回填。</p>
    {!parentPin ? <p role="status">请先进入家长模式。</p> : null}
    <label>失锁段<select aria-label="失锁段" disabled={busy} value={segment ?? ""} onChange={e => {setSegment(Number(e.target.value)); setObservation(null); reset();}}>
      <option value="" disabled>选择失锁段</option>
      {Array.from(new Set(data?.observations.map(r => r.segment))).map(s => <option key={s} value={s}>段 {s}</option>)}
    </select></label>
    <label>保存观测<select aria-label="保存观测" disabled={busy} value={observation ?? ""} onChange={e => {setObservation(Number(e.target.value)); reset();}}>
      <option value="" disabled>选择保存图片</option>
      {data?.observations.filter(r => r.segment === segment).map(r => <option key={r.observation_index} value={r.observation_index}>观测 {r.observation_index} · 播放 {r.timestamp.toFixed(3)} 秒</option>)}
    </select></label>
    {current ? <>
      <div style={{position: "relative", maxWidth: 720}}>
        <SavedImage url={current.image_url} pin={parentPin ?? ""}/>
        <svg aria-label="全部原候选框" viewBox={`0 0 ${current.canvas.width} ${current.canvas.height}`} style={{position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none"}}>
          {current.candidates.map(c => <g key={c.index}><rect x={c.bbox[0]} y={c.bbox[1]} width={c.bbox[2]-c.bbox[0]} height={c.bbox[3]-c.bbox[1]} fill="none" stroke={selection?.candidate_index === c.index ? "#10b981" : "#f97316"} strokeWidth={2}/><text x={c.bbox[0]} y={Math.max(12, c.bbox[1])} fill="white">候选 {c.index + 1}</text></g>)}
        </svg>
      </div>
      <div role="listbox" aria-label="全部原候选">{current.candidates.map(c => <button type="button" role="option" aria-selected={selection?.candidate_index === c.index} key={c.index} disabled={busy} onClick={() => {if (selection !== c.selection) {reset(); setSelection(c.selection);}}}>候选 {c.index + 1} · 检测 {(100*c.confidence).toFixed(0)}%</button>)}</div>
      {!current.candidates.length ? <p>原回执中无人可选。</p> : null}
    </> : null}
    <button type="button" disabled={!selection || busy} onClick={async () => {
      if (!id || !selection || !parentPin) return;
      const version = generation.current; setBusy(true); setMessage("");
      try {
        const p = await previewSegmentAnchor(id, selection, parentPin);
        if (version !== generation.current) return;
        try {
          const nextKey = preview?.preview_digest === p.preview_digest && key ? key : confirmationKey();
          setKey(nextKey); setPreview(p);
        } catch {
          setPreview(null); setKey("");
          setMessage("无法提交：浏览器没有可用的安全随机源，请使用支持安全随机数的浏览器后重试预览。");
        }
      } catch {
        if (version === generation.current) {setPreview(null); setKey(""); setMessage("预览失败：候选证据或版本已改变，请重新进入选择。");}
      } finally {if (version === generation.current) setBusy(false);}
    }}>预览影响</button>
    {preview && key ? <div role="status">辅助修订 {preview.revision}，局部观测 {preview.local_range.join("、")}。{preview.note}
      <p>原自动版本保留；同段旧辅助结果失效。仅显示保存图，视频叠加不启用。</p>
      <button type="button" disabled={busy || !key} onClick={async () => {
        if (!id || !selection || !parentPin || !key || confirming.current) return; confirming.current = true; setBusy(true); setMessage("正在提交辅助修订");
        try {const r = await confirmSegmentAnchor(id, selection, preview, key, parentPin); navigate(`/analysis/${id}?aux=${r.revision}`);}
        catch {setMessage("提交未成功。可以用相同选择再次提交；版本冲突时请重新读取候选。");} finally {confirming.current = false; setBusy(false);}
      }}>确认本段目标并处理</button>
    </div> : null}
    {data?.unavailable.length ? <details><summary>不可用的保存证据（{data.unavailable.length}）</summary>{data.unavailable.map((r, i) => <p key={i}>观测 {r.observation_index ?? "?"}：{r.reason}</p>)}</details> : null}
    {message ? <p role="status">{message}</p> : null}
    <Link to={`/analysis/${id}`}>回到原自动结果</Link>
  </section>;
}

export function SegmentRevisionChooser({id}: {id: string}) {
  const {parentPin} = useAppMode(); const [params, setParams] = useSearchParams();
  const [data, setData] = useState<SegmentCandidates | null>(null);
  useEffect(() => {let active = true; if (parentPin) void fetchSegmentCandidates(id, parentPin).then(d => {if (active) setData(d);}).catch(() => {}); return () => {active = false;};}, [id, parentPin, params.get("aux")]);
  if (!parentPin) return null;
  return <section aria-label="身份辅助修订"><label>结果版本<select aria-label="结果版本" value={params.get("aux") ?? "automatic"} onChange={e => {
    // Drop old event/seek/frame state when changing versions.
    setParams(e.target.value === "automatic" ? {} : {aux: e.target.value});
  }}><option value="automatic">原自动结果</option>{data?.revisions.map(r => <option key={r.revision} value={r.revision}>辅助修订 {r.revision} · {STATUS[r.status]}{r.superseded ? " · 已失效（历史）" : ""}</option>)}</select></label>
    <Link to={`/report/${id}/target?reanchor=1`}>在失锁段重新选定目标</Link>
  </section>;
}

export function SegmentRevisionReplay({id, revision}: {id: string; revision: number}) {
  const {parentPin} = useAppMode(); const [detail, setDetail] = useState<SegmentRevisionDetail | null>(null);
  const [pose, setPose] = useState<PoseResponse | null>(null); const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false; let timer: ReturnType<typeof setTimeout>; const urls: string[] = [];
    setPose(null); setDetail(null); setError("");
    async function read() {
      if (!parentPin) return;
      try {
        const d = await fetchSegmentRevision(id, revision, parentPin); if (cancelled) return; setDetail(d);
        if (d.status === "submitted" || d.status === "processing") {timer = setTimeout(() => void read(), 1000); return;}
        const p = await fetchSegmentRevisionPose(id, revision, parentPin);
        const bound: Record<string, string> = {};
        await Promise.all(Object.entries(p.frame_urls).map(async ([name, url]) => {
          try {const blob = await fetchSegmentSavedImage(url, parentPin); const local = URL.createObjectURL(blob); urls.push(local); bound[name] = local;}
          catch {bound[name] = "";}
        }));
        if (!cancelled) setPose({...p, frame_urls: bound}); else urls.forEach(URL.revokeObjectURL);
      } catch {if (!cancelled) setError("辅助修订读取失败，请检查权限或保存记录。");}
    }
    void read(); return () => {cancelled = true; clearTimeout(timer); urls.forEach(URL.revokeObjectURL);};
  }, [id, revision, parentPin]);
  if (!parentPin) return <p role="status">请先进入家长模式读取辅助修订。</p>;
  return <section aria-label="辅助修订回看">
    <h2>辅助修订 {revision}</h2><p>身份来源：用户在保存图片中重新选定。本段辅助结果不证明自动跨缺口同人或跳跃成立。</p>
    <p role="status">{error || (detail ? STATUS[detail.status] : "正在读取辅助修订")}</p>
    {detail?.superseded ? <p>本段锚点已更改，此结果已失效，仅供历史回看。</p> : null}
    {detail?.error ? <p>{detail.error}</p> : null}
    {detail?.report ? <p>{detail.report.summary} {detail.report.profile_warning}</p> : null}
    {pose?.frames.length ? <PoseViewer key={`${id}:${revision}`} pose={pose} variant="debug"/> : null}
  </section>;
}
