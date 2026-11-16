import { ReactNode, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AnalysisDetail, PoseResponse, fetchAnalysis, fetchAnalysisPose, retryAnalysis } from "../api/client";
import { IceMediaPlayer } from "../media/IceMediaPlayer";
import ProfileEvidenceWarning, { resolveProfileWarning } from "./ProfileEvidenceWarning";

function LocalResult() {
  const { id } = useParams();
  const [record, setRecord] = useState<AnalysisDetail | null>(null);
  const [pose, setPose] = useState<PoseResponse | null>(null);
  const [poseError, setPoseError] = useState("");
  const [overlay, setOverlay] = useState(false);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setRecord(null);
    async function load() {
      try {
        const result = await fetchAnalysis(id!);
        if (disposed) return;
        setRecord(result); setError("");
        if (!["completed", "failed", "awaiting_target_selection"].includes(result.status)) timer = setTimeout(load, 2000);
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : "读取结果失败");
      }
    }
    if (id) void load();
    return () => { disposed = true; clearTimeout(timer); };
  }, [id, revision]);
  useEffect(() => {
    let disposed = false;
    setPose(null); setPoseError(""); setOverlay(false);
    if (id && record?.id === id && record.status === "completed") {
      fetchAnalysisPose(id).then(result => { if (!disposed) setPose(result); })
        .catch(() => { if (!disposed) setPoseError("读取保存姿态失败；视频和报告仍可用。"); });
    }
    return () => { disposed = true; };
  }, [id, record?.id, record?.status, revision]);
  async function retry() {
    if (!id || retrying) return;
    setRetrying(true); setError("");
    try { await retryAnalysis(id); setRevision(v => v + 1); }
    catch (e) { setError(e instanceof Error ? e.message : "重试失败"); }
    finally { setRetrying(false); }
  }
  const profileWarning = resolveProfileWarning(record?.report?.profile_warning, record?.bio_data?.profile_warning);
  const savedSummary = record?.report?.summary?.trim() || "";
  // Native reports append the same warning for other consumers. Show that
  // suffix once here, in the dedicated accessible warning below.
  const summary = profileWarning && savedSummary.endsWith(profileWarning)
    ? savedSummary.slice(0, -profileWarning.length).trim()
    : savedSummary;
  return <section style={{padding: 24, maxWidth: 900, margin: "auto"}}>
    <h1>本地视频分析</h1>
    <p>外部 AI 已关闭；未评分，技术结论未确认。</p>
    {error && <p role="alert">{error} <button onClick={() => setRevision(v => v + 1)}>重新读取</button></p>}
    {!record && !error && <p role="status">正在读取…</p>}
    {record && record.id === id && <>
      <p role="status">状态：{record.status === "completed" ? "本地处理结果已保存（证据不足）" : record.status === "failed" ? "处理失败" : record.status === "awaiting_target_selection" ? "等待确认目标" : "本地处理中"}</p>
      {record.status === "completed" && <div aria-label="复盘模式">
        <button aria-pressed={!overlay} onClick={() => setOverlay(false)}>视频</button>
        <button aria-pressed={overlay} onClick={() => setOverlay(true)}>骨架叠加</button>
        {poseError && <p role="alert">{poseError} <button onClick={() => setRevision(v => v + 1)}>重新读取</button></p>}
        {!pose && !poseError && <p role="status">正在读取保存姿态…</p>}
      </div>}
      <IceMediaPlayer key={record.id} manifest={record.media_manifest} pose={pose} mode={overlay ? "overlay" : "video"} fallbackSrc={`/api/analysis/${encodeURIComponent(record.id)}/video`} />
      {record.status === "awaiting_target_selection" && <Link to={`/report/${record.id}/target`}>确认主滑行者并继续</Link>}
      {record.status === "failed" && <><p>{record.error_message || record.error_detail || "处理未完成，请重试。"}</p><button disabled={retrying} onClick={() => void retry()}>{retrying ? "正在提交…" : "重试同一条记录"}</button></>}
      {record.status === "completed" && <>
        {summary ? <p>{summary}</p> : !profileWarning && <p>结果已保存，暂无可展示结论。</p>}
        <ProfileEvidenceWarning reportWarning={record.report?.profile_warning} bioWarning={record.bio_data?.profile_warning} />
      </>}
      {record.report?.local_execution && <ul>{Object.entries(record.report.local_execution).map(([key, value]) => <li key={key}>{key}：{value ? "已执行" : "未执行"}</li>)}</ul>}
      <p>记录编号：{record.id}</p>
    </>}
    <Link to="/review">返回上传</Link>
  </section>;
}
export default function LocalAnalysisRoute({children}: {children: ReactNode}) {
  const [profile, setProfile] = useState<string | null>(null);
  useEffect(() => { fetch("/api/trial").then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(t => setProfile(t.profile)).catch(() => setProfile("unavailable")); }, []);
  if (profile === null) return <p role="status">正在读取运行档位…</p>;
  if (profile === "unavailable") return <p role="alert">无法确认运行档位，请刷新重试。</p>;
  return profile === "legacy-analysis-preview" ? <LocalResult /> : <>{children}</>;
}
