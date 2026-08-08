import axios from "axios";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import { fetchAnalysisMedia, type MediaManifest } from "../../api/client";
import { IceMediaPlayer, type IceMediaPlayerHandle } from "../../media/IceMediaPlayer";
import type { MediaMarker, SourceFrameIdentity } from "../../media/types";
import {
  addShadowNote,
  cleanupShadowRun,
  createShadowRun,
  fetchShadowArtifact,
  fetchShadowDiff,
  fetchShadowReviewDecisions,
  fetchShadowRuns,
  recoverShadowRun,
  retryShadowRun,
  submitShadowReviewDecision,
} from "../api";
import type { ShadowArtifactResponse, ShadowDiffResponse, ShadowReviewDecision, ShadowRunRecord, ShadowStage } from "../shadow-contracts";
import { SHADOW_STAGES } from "../shadow-contracts";
import IslandIcon from "../../modern/IslandIcon";
import { IslandButton, IslandCard, IslandPageHeader, IslandTitle } from "../../modern/IslandSurface";

const stageLabels: Record<ShadowStage, string> = {
  timebase: "Timebase",
  observations: "Observations",
  candidates: "Candidate coverage",
  identity: "Identity",
  pose: "Pose provenance",
  events: "Events",
  moments: "Key moments",
  rotation: "Rotation",
  path_reviews: "Path A/B reviews",
  claims: "Claims",
};

function formatStatus(status: string) {
  return status.split("_").join(" ");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is Record<string, unknown> => Boolean(item)) : [];
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

type EvidenceMarker = MediaMarker & { stage: ShadowStage; sourceFrameIndex?: number };

type EvidenceSummary = {
  markers: EvidenceMarker[];
  lines: string[];
  timing: "exact" | "approximate" | "unavailable";
};

function summarizeArtifact(stage: ShadowStage, content: Record<string, unknown> | null): EvidenceSummary {
  if (!content) return { markers: [], lines: ["Artifact 内容不可用；仅显示 hash-only 引用。"], timing: "unavailable" };
  const markers: EvidenceMarker[] = [];
  const lines: string[] = [];
  const addMarker = (id: string, timestamp: unknown, label: string, sourceFrameIndex?: unknown) => {
    const pts = numberValue(timestamp);
    if (pts == null) return;
    const frame = numberValue(sourceFrameIndex);
    markers.push({ id, timestamp: Math.max(0, pts), label, stage, ...(frame == null ? {} : { sourceFrameIndex: frame }) });
  };

  if (stage === "timebase") {
    const index = asRecord(content.source_index);
    const status = String(index?.timestamp_status ?? "");
    const fingerprint = String(index?.fingerprint ?? "");
    lines.push(`时间轴状态：${status || "unavailable"}`);
    if (fingerprint) lines.push(`Source timeline fingerprint：${fingerprint}`);
    const frames = asRecords(index?.frames);
    if (frames.length) {
      addMarker("timebase:first", frames[0].pts_sec, "首帧", frames[0].source_frame_index);
      addMarker("timebase:last", frames[frames.length - 1].pts_sec, "末帧", frames[frames.length - 1].source_frame_index);
    }
    return { markers, lines, timing: status === "available" ? "exact" : status ? "approximate" : "unavailable" };
  }

  if (stage === "identity") {
    const timeline = asRecord(content.timeline);
    const segments = asRecords(content.segments ?? timeline?.segments);
    const conflicts = segments.filter((item) => item.conflict === true || String(item.state ?? "") !== "confirmed");
    lines.push(`Identity segments：${segments.length}`);
    lines.push(`Identity conflict / uncertain intervals：${conflicts.length}`);
    conflicts.slice(0, 80).forEach((item, index) => addMarker(`identity:${index}`, item.pts_sec, `Identity ${String(item.state ?? "conflict")}`, item.source_frame_index));
  } else if (stage === "pose") {
    const observations = asRecords(content.observations);
    const methods = [...new Set(observations.map((item) => String(item.source_method ?? item.provenance ?? "unknown")))];
    lines.push(`Pose observations：${observations.length}`);
    lines.push(`Pose provenance：${methods.filter(Boolean).join(", ") || "unavailable"}`);
    observations.slice(0, 80).forEach((item, index) => addMarker(`pose:${index}`, item.pts_sec, "Pose evidence", item.source_frame_index));
  } else if (stage === "events") {
    const events = asRecords(content.events ?? content.scopes);
    lines.push(`Events：${events.length}`);
    events.forEach((item, index) => {
      const label = `Event ${String(item.profile ?? "unknown")}`;
      addMarker(`event:${index}:start`, item.start_pts_sec ?? item.start_pts, `${label} start`, item.anchor_start_frame);
      addMarker(`event:${index}:end`, item.end_pts_sec ?? item.end_pts, `${label} end`, item.anchor_end_frame);
    });
  } else if (stage === "moments") {
    const sets = asRecords(content.sets);
    const moments = sets.flatMap((set) => asRecords(set.moments));
    lines.push(`Moment sets：${sets.length}`);
    lines.push(`Moments：${moments.length}`);
    moments.forEach((item, index) => addMarker(`moment:${index}`, item.pts_sec, `Moment ${String(item.semantic_key ?? item.kind ?? "evidence")}`, item.source_frame_index));
  } else if (stage === "rotation") {
    const estimates = asRecords(content.estimates);
    lines.push(`Rotation estimates：${estimates.length}`);
    estimates.forEach((item, index) => addMarker(`rotation:${index}`, item.event_start_pts ?? item.start_pts_sec, `Rotation ${String(item.profile ?? "estimate")}`));
  } else if (stage === "path_reviews") {
    const claims = asRecords(content.claims ?? [...asRecords(content.path_a_claims), ...asRecords(content.path_b_claims)]);
    lines.push(`Path review claims：${claims.length}`);
    claims.slice(0, 80).forEach((item, index) => addMarker(`path:${index}`, item.start_pts_sec ?? item.pts_sec, `Claim ${String(item.claim_type ?? "evidence")}`));
  } else if (stage === "claims") {
    const claims = asRecords(content.claims);
    const conflicts = asRecords(content.conflicts);
    lines.push(`Fused claims：${claims.length}`);
    lines.push(`Claim conflicts：${conflicts.length}`);
    claims.slice(0, 80).forEach((item, index) => addMarker(`claim:${index}`, item.start_pts_sec ?? item.pts_sec, `Claim ${String(item.claim_type ?? "evidence")}`));
  } else {
    lines.push(`Artifact schema：${String(content.schema_version ?? "unavailable")}`);
    lines.push("该 stage 没有可视化时间字段；可用 hash 和 diff 定位。");
  }
  return { markers, lines, timing: markers.length ? "exact" : "unavailable" };
}

function shortHash(value: string | null | undefined) {
  if (!value) return "unavailable";
  return value.length > 28 ? `${value.slice(0, 12)}…${value.slice(-10)}` : value;
}

function GateEvidence({ selected, firstDivergence }: { selected: ShadowRunRecord; firstDivergence: ShadowStage | null }) {
  const rows = [
    ["G11 fixed-fingerprint repeatability", "unavailable", "Shadow API 没有提交的 G11 evidence；未运行不代表通过。"],
    ["First divergent stage", firstDivergence ? "evidence present" : "unavailable", firstDivergence ? `首个分歧：${stageLabels[firstDivergence]}（仍需解释原因）。` : "没有可用的 stage diff baseline。"],
    ["Contamination sentinel", "unavailable", "未提供本 run 的全域 sentinel 证据；不在 UI 伪造通过。"],
    ["Legacy public API regression", "unavailable", "需要独立测试/ledger evidence，不由单次 Shadow run 推断。"],
  ] as const;
  return <IslandCard tone="sky"><IslandTitle>Fingerprints & gate evidence</IslandTitle><dl className="modern-runtime-status"><div><dt>Pipeline</dt><dd className="font-mono text-xs">{shortHash(selected.pipeline_fingerprint)}</dd></div><div><dt>Source</dt><dd className="font-mono text-xs">{shortHash(selected.source_fingerprint)}</dd></div><div><dt>Source video hash</dt><dd className="font-mono text-xs">{shortHash(selected.source_video_hash)}</dd></div><div><dt>Model</dt><dd className="font-mono text-xs">{shortHash(selected.model_fingerprint)}</dd></div><div><dt>Config</dt><dd className="font-mono text-xs">{shortHash(selected.config_fingerprint)}</dd></div><div><dt>Prompt</dt><dd className="font-mono text-xs">{shortHash(selected.prompt_fingerprint)}</dd></div><div><dt>Contract</dt><dd className="font-mono text-xs">{shortHash(selected.contract_fingerprint)}</dd></div></dl><div className="mt-4 grid gap-2 md:grid-cols-2">{rows.map(([label, status, reason]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-3"><div className="flex items-center justify-between gap-2"><strong className="text-xs">{label}</strong><span className="rounded-full bg-amber-50 px-2 py-1 text-[11px] font-bold text-amber-800">{status}</span></div><p className="mt-1 text-xs leading-5 text-slate-600">{reason}</p></div>)}</div></IslandCard>;
}

function ShadowEvidenceInspector({ parentPin, selected, artifact }: { parentPin: string; selected: ShadowRunRecord; artifact: ShadowArtifactResponse | null }) {
  const playerRef = useRef<IceMediaPlayerHandle | null>(null);
  const [media, setMedia] = useState<MediaManifest | null>(null);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [currentPts, setCurrentPts] = useState(0);
  const summary = useMemo(() => summarizeArtifact(artifact?.artifact.stage ?? "timebase", artifact?.content ?? null), [artifact]);
  const sourceFrame: SourceFrameIdentity | null = useMemo(() => {
    const marker = summary.markers.find((item) => Math.abs(item.timestamp - currentPts) < 0.03 && item.sourceFrameIndex != null);
    return marker?.sourceFrameIndex == null ? null : { sourceFrameIndex: marker.sourceFrameIndex, pts: marker.timestamp, duration: null, status: summary.timing };
  }, [currentPts, summary]);
  const loadMedia = async () => {
    setMediaLoading(true); setMediaError(null);
    try { setMedia(await fetchAnalysisMedia(selected.analysis_id)); } catch { setMediaError("Legacy source media 不可用；仍可查看时间 marker 和 artifact evidence。"); } finally { setMediaLoading(false); }
  };
  return <IslandCard tone="cream"><div className="flex flex-wrap items-start justify-between gap-3"><div><IslandTitle>Exact-time evidence inspector</IslandTitle><p className="text-xs font-semibold text-slate-600">Legacy 与 V2 使用同一 source PTS；这里只提供只读共享 seek/marker，不生成第二份 authority。</p></div><IslandButton type="button" variant="secondary" onClick={() => void loadMedia()} disabled={mediaLoading}>{mediaLoading ? "正在加载 source…" : media ? "重新加载 source" : "加载 legacy source"}</IslandButton></div>{mediaError ? <p role="status" className="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{mediaError}</p> : null}<div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(260px,.8fr)]"><div className="min-w-0">{media ? <IceMediaPlayer ref={playerRef} manifest={media} fallbackSrc={`/api/analysis/${encodeURIComponent(selected.analysis_id)}/video`} markers={summary.markers} onTimeChange={setCurrentPts} sourceFrame={sourceFrame} /> : <div className="flex aspect-video items-center justify-center rounded-xl bg-slate-950 p-6 text-center text-sm text-slate-400">加载 parent-authorized legacy source 后，可在这里按同一 PTS 回放。</div>}<div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-600"><span>当前 source PTS：{currentPts.toFixed(6)}s</span><span>Timing：{summary.timing}</span><span>Stage：{artifact ? stageLabels[artifact.artifact.stage] : "unavailable"}</span></div></div><div className="min-w-0 rounded-xl border border-slate-200 bg-white p-3"><h3 className="text-sm font-bold">V2 evidence lane</h3>{summary.lines.map((line) => <p key={line} className="mt-2 text-xs leading-5 text-slate-700">{line}</p>)}{summary.markers.length ? <div className="mt-3 max-h-64 space-y-1 overflow-y-auto" role="list" aria-label="Shadow evidence markers">{summary.markers.map((marker) => <button key={marker.id} type="button" role="listitem" className="block w-full rounded-lg border border-slate-100 px-2 py-1 text-left text-xs hover:border-teal-300" onClick={() => { setCurrentPts(marker.timestamp); playerRef.current?.seek(marker.timestamp); }}>{marker.timestamp.toFixed(6)}s · {marker.label}</button>)}</div> : <p className="mt-3 text-xs text-slate-500">暂无可定位的时间 marker。</p>}</div></div><p className="mt-3 text-[11px] leading-5 text-slate-500">Parent PIN 仅用于读取隔离 artifact；播放器读取 legacy media endpoint，Shadow artifact 不会写入普通报告。</p></IslandCard>;
}

export default function ShadowWorkspace({ analysisId }: { analysisId?: string }) {
  const { isParentMode, parentPin, enterParentMode } = useAppMode();
  const [analysis, setAnalysis] = useState(analysisId ?? "");
  const [runs, setRuns] = useState<ShadowRunRecord[]>([]);
  const [selected, setSelected] = useState<ShadowRunRecord | null>(null);
  const [diff, setDiff] = useState<ShadowDiffResponse | null>(null);
  const [decisions, setDecisions] = useState<ShadowReviewDecision[]>([]);
  const [artifact, setArtifact] = useState<ShadowArtifactResponse | null>(null);
  const [artifactId, setArtifactId] = useState("");
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [decisionNote, setDecisionNote] = useState("");
  const [retryReason, setRetryReason] = useState("");

  const hydrate = async (run: ShadowRunRecord) => {
    if (!parentPin) return;
    setSelected(run);
    setArtifact(null);
    const nextArtifact = run.artifacts.find((item) => item.stage === (run.first_divergent_stage ?? "timebase")) ?? run.artifacts[0];
    setArtifactId(nextArtifact?.artifact_id ?? "");
    const [nextDiff, nextDecisions] = await Promise.all([
      fetchShadowDiff(parentPin, run.run_id).catch(() => null),
      fetchShadowReviewDecisions(parentPin, run.run_id).catch(() => run.review_decisions ?? []),
    ]);
    setDiff(nextDiff);
    setDecisions(nextDecisions ?? []);
    if (nextArtifact) {
      setArtifactLoading(true);
      try { setArtifact(await fetchShadowArtifact(parentPin, run.run_id, nextArtifact.artifact_id)); } catch { setArtifact(null); }
      finally { setArtifactLoading(false); }
    }
  };

  const loadRuns = async (id = analysis) => {
    if (!parentPin || !id.trim()) return;
    setLoading(true); setError(null);
    try { const response = await fetchShadowRuns(parentPin, id.trim()); setRuns(response.runs); if (response.runs[0]) await hydrate(response.runs[0]); else { setSelected(null); setDiff(null); setDecisions([]); } }
    catch (requestError: unknown) { setError(axios.isAxiosError(requestError) ? String(requestError.response?.data?.detail ?? "Shadow 暂时不可用") : "Shadow 暂时不可用"); }
    finally { setLoading(false); }
  };

  useEffect(() => { if (isParentMode && parentPin && analysisId) void loadRuns(analysisId); }, [analysisId, isParentMode, parentPin]);

  const chooseRun = async (run: ShadowRunRecord) => { try { await hydrate(run); } catch { setDiff(null); setDecisions(run.review_decisions ?? []); } };

  const startRun = async (event: FormEvent) => {
    event.preventDefault(); if (!parentPin || !analysis.trim()) return;
    if (typeof window !== "undefined" && !window.confirm("创建 parent-authorized Shadow run？legacy report 仍保持唯一权威。")) return;
    setLoading(true); setError(null);
    try { await createShadowRun(parentPin, { analysis_id: analysis.trim(), note: "Parent-authorized Shadow run" }); await loadRuns(analysis.trim()); }
    catch (requestError: unknown) { setError(axios.isAxiosError(requestError) ? String(requestError.response?.data?.detail ?? "无法创建 Shadow run") : "无法创建 Shadow run"); }
    finally { setLoading(false); }
  };

  const retry = async (stage?: ShadowStage) => {
    if (!parentPin || !selected) return;
    const reason = retryReason.trim() || "resume from invalid stage";
    if (typeof window !== "undefined" && !window.confirm(`确认重试 Shadow（${stage ? stageLabels[stage] : "首个无效 stage"}）？原因：${reason}`)) return;
    setLoading(true); setError(null);
    try { const response = await retryShadowRun(parentPin, selected.run_id, { stage: stage ?? null, reason, confirmation: "confirm_shadow_retry" }); await hydrate(response.run); await loadRuns(response.run.analysis_id); setRetryReason(""); }
    catch (requestError: unknown) { setError(axios.isAxiosError(requestError) ? String(requestError.response?.data?.detail ?? "重试失败") : "重试失败"); }
    finally { setLoading(false); }
  };

  const recover = async () => {
    if (!parentPin || !selected) return;
    if (typeof window !== "undefined" && !window.confirm("确认恢复 parent-only Shadow？系统将从首个无效或未完成 stage 继续。")) return;
    setLoading(true); setError(null);
    try { const response = await recoverShadowRun(parentPin, selected.run_id); await hydrate(response.run); await loadRuns(response.run.analysis_id); }
    catch (requestError: unknown) { setError(axios.isAxiosError(requestError) ? String(requestError.response?.data?.detail ?? "恢复 Shadow 失败") : "恢复 Shadow 失败"); }
    finally { setLoading(false); }
  };

  const cleanup = async () => {
    if (!parentPin || !selected) return;
    if (typeof window !== "undefined" && !window.confirm("只删除可重建的 Shadow artifacts，保留视频、Golden labels、reviews 和审计。继续？")) return;
    setLoading(true); setError(null);
    try { await cleanupShadowRun(parentPin, selected.run_id); await loadRuns(selected.analysis_id); }
    catch (requestError: unknown) { setError(axios.isAxiosError(requestError) ? String(requestError.response?.data?.detail ?? "清理 Shadow artifacts 失败") : "清理 Shadow artifacts 失败"); }
    finally { setLoading(false); }
  };

  const selectArtifact = async (id: string) => {
    setArtifactId(id); if (!parentPin || !selected || !id) return;
    setArtifactLoading(true);
    try { setArtifact(await fetchShadowArtifact(parentPin, selected.run_id, id)); } catch { setArtifact(null); setError("Artifact 内容暂时不可用；仍保留 hash-only 诊断。"); }
    finally { setArtifactLoading(false); }
  };

  const saveNote = async () => { if (!parentPin || !selected || !note.trim()) return; try { const response = await addShadowNote(parentPin, selected.run_id, note.trim()); setSelected({ ...selected, notes: response.notes }); setNote(""); } catch { setError("备注保存失败"); } };

  const saveDecision = async (decision: "accept_shadow" | "reject_shadow" | "defer") => {
    if (!parentPin || !selected) return;
    if (typeof window !== "undefined" && !window.confirm(`确认记录 Shadow review decision：${decision}？不会改写 legacy report。`)) return;
    try { await submitShadowReviewDecision(parentPin, selected.run_id, { stage: selected.first_divergent_stage ?? "claims", decision, reviewer: "parent", note: decisionNote.trim() || null, confirmation: "confirm_shadow_review_decision" }); setDecisionNote(""); await loadRuns(selected.analysis_id); }
    catch (requestError: unknown) { setError(axios.isAxiosError(requestError) ? String(requestError.response?.data?.detail ?? "复核决定保存失败") : "复核决定保存失败"); }
  };

  const firstDivergence = diff?.first_divergent_stage ?? selected?.first_divergent_stage ?? null;
  const stageMap = useMemo(() => new Map((selected?.stages ?? []).map((stage) => [stage.stage, stage])), [selected]);

  if (!isParentMode) return <IslandCard className="modern-me-panel modern-lock-panel" tone="sun"><IslandIcon name="lock"/><IslandTitle>Shadow 工作台仅家长可见</IslandTitle><p>这里显示隔离的 V2 诊断、差异和审计记录，不会改变普通复盘。</p><IslandButton onClick={() => void enterParentMode()}>进入家长模式</IslandButton></IslandCard>;
  if (!parentPin) return <IslandCard tone="sun"><IslandTitle>请重新验证家长 PIN</IslandTitle><IslandButton onClick={() => void enterParentMode()}>验证 PIN</IslandButton></IslandCard>;

  return <div className="modern-space" data-testid="shadow-workspace">
    <IslandPageHeader title="Shadow 复核工作台" description="Resident Services · legacy 与 V2 并排诊断。所有候选均保持 Shadow authority，普通报告始终使用 legacy。" />
    <IslandCard tone="sky"><form onSubmit={startRun} className="flex flex-wrap items-end gap-3"><label className="min-w-[240px] flex-1"><span className="block text-sm font-bold">Analysis ID</span><input value={analysis} onChange={(event) => setAnalysis(event.target.value)} placeholder="输入已 Golden 的 analysis id" className="mt-1 w-full rounded-xl border-2 border-slate-200 px-3 py-2" /></label><IslandButton type="submit" disabled={loading || !analysis.trim()}>运行 / 合并 Shadow</IslandButton><IslandButton type="button" variant="secondary" onClick={() => void loadRuns()} disabled={loading || !analysis.trim()}>刷新</IslandButton></form><p className="mt-3 text-xs font-semibold text-slate-600">只读取 parent-authorized Shadow API；不会请求普通页面的 raw Shadow 字段。</p></IslandCard>
    {error ? <IslandCard tone="sun"><div role="alert"><IslandTitle>暂时无法读取</IslandTitle><p>{error}</p></div></IslandCard> : null}
    {loading ? <IslandCard aria-live="polite"><p>正在读取 Shadow checkpoints…</p></IslandCard> : null}
    {runs.length ? <IslandCard><IslandTitle>Runs</IslandTitle><div className="flex flex-wrap gap-2" role="list">{runs.map((run) => <button key={run.run_id} type="button" role="listitem" className={`rounded-xl border-2 px-3 py-2 text-left ${selected?.run_id === run.run_id ? "border-teal-500 bg-teal-50" : "border-slate-200 bg-white"}`} onClick={() => void chooseRun(run)}><strong className="block text-xs">{run.run_id.slice(0, 18)}</strong><span className="text-xs">{formatStatus(run.status)} · {run.coalesced ? "coalesced" : "new"}</span></button>)}</div></IslandCard> : null}
    {selected ? <>
      <div className="grid gap-4 lg:grid-cols-2"><IslandCard tone="cream"><IslandTitle>Legacy authority</IslandTitle><p className="text-sm font-semibold">Committed report remains authoritative and complete.</p><dl className="modern-runtime-status"><div><dt>Authority</dt><dd>{selected.authority}</dd></div><div><dt>Family writes</dt><dd>none</dd></div><div><dt>Run status</dt><dd>{formatStatus(selected.status)}</dd></div></dl></IslandCard><IslandCard tone="mint"><IslandTitle>V2 Shadow diagnostics</IslandTitle><p className="text-sm font-semibold">Diagnostic-only artifacts are isolated and rebuildable.</p><dl className="modern-runtime-status"><div><dt>First divergence</dt><dd>{firstDivergence ? stageLabels[firstDivergence] : "未发现"}</dd></div><div><dt>Artifacts</dt><dd>{selected.artifacts.length} references</dd></div></dl><div className="mt-3 flex flex-wrap gap-2"><IslandButton type="button" variant="secondary" onClick={() => void recover()} disabled={loading || !["partial", "failed", "invalid", "cancelled"].includes(selected.status)}>恢复 / 从首个无效 stage 继续</IslandButton><IslandButton type="button" variant="quiet" onClick={() => void cleanup()} disabled={loading || selected.artifacts.length === 0}>清理可重建 artifacts</IslandButton></div></IslandCard></div>
      <GateEvidence selected={selected} firstDivergence={firstDivergence} />
      <IslandCard><IslandTitle>Stage checkpoints & diff</IslandTitle><div className="mb-3 flex flex-wrap items-center gap-2"><label className="text-xs font-semibold">Retry reason<input value={retryReason} onChange={(event) => setRetryReason(event.target.value)} placeholder="说明本次 parent 重试原因" className="ml-2 rounded-lg border border-slate-200 px-2 py-1" /></label></div><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Stage</th><th className="p-2">Status</th><th className="p-2">Input / output</th><th className="p-2">Diff</th><th className="p-2">Action</th></tr></thead><tbody>{SHADOW_STAGES.map((stage) => { const state = stageMap.get(stage); const stageDiff = diff?.stages.find((item) => item.stage === stage); return <tr key={stage} className={stage === firstDivergence ? "bg-amber-50" : "border-t border-slate-100"}><td className="p-2 font-bold">{stageLabels[stage]}</td><td className="p-2">{formatStatus(state?.status ?? "unavailable")}</td><td className="p-2 font-mono text-xs">{shortHash(state?.input_hash)} → {shortHash(state?.output_hash)}<br/><span className="text-slate-500">deps {Object.keys(state?.dependency_hashes ?? {}).length}</span></td><td className="p-2">{stageDiff ? formatStatus(stageDiff.status) : "unavailable"}{stageDiff?.summary ? ` · ${stageDiff.summary}` : ""}</td><td className="p-2">{state?.status === "failed" || state?.status === "invalid" ? <button type="button" className="text-teal-700 underline" onClick={() => void retry(stage)}>retry</button> : null}</td></tr>; })}</tbody></table></div></IslandCard>
      <IslandCard><IslandTitle>Fingerprint baseline</IslandTitle><div className="grid gap-3 md:grid-cols-2">{SHADOW_STAGES.map((stage) => <div key={stage} className="rounded-lg border border-slate-100 p-2 text-xs"><strong>{stage}</strong><p className="mt-1 font-mono">{shortHash(selected.legacy_stage_fingerprints?.[stage])}</p></div>)}</div></IslandCard>
      <IslandCard><IslandTitle>Shadow artifact references</IslandTitle><p className="text-xs font-semibold text-slate-600">仅展示 versioned、隔离、可重建引用；不会把 raw Shadow 填入普通报告。</p>{selected.artifacts.length ? <><label className="mt-2 block text-xs font-semibold">查看 artifact 内容<select value={artifactId} onChange={(event) => void selectArtifact(event.target.value)} className="ml-2 rounded-lg border border-slate-200 px-2 py-1"><option value="">选择 stage</option>{selected.artifacts.map((item) => <option key={item.artifact_id} value={item.artifact_id}>{stageLabels[item.stage]} · {item.artifact_id}</option>)}</select></label><ul className="mt-2 space-y-1 text-sm">{selected.artifacts.map((item) => <li key={item.artifact_id} className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 py-2"><span><strong>{stageLabels[item.stage]}</strong> · <span className="font-mono text-xs">{item.artifact_id}</span></span><span className="text-xs font-semibold">{item.status} · {item.relative_path}</span></li>)}</ul>{artifactLoading ? <p className="mt-2 text-xs" aria-live="polite">正在读取 artifact 内容…</p> : null}</> : <p className="mt-2 text-sm">暂无 artifact reference（可恢复运行）。</p>}</IslandCard>
      <ShadowEvidenceInspector parentPin={parentPin} selected={selected} artifact={artifact} />
      <div className="grid gap-4 lg:grid-cols-2"><IslandCard><IslandTitle>Downstream dry-run</IslandTitle><ul className="space-y-2 text-sm">{(diff?.downstream ?? selected.downstream).map((item) => <li key={item.consumer} className="flex items-center justify-between gap-2"><span>{item.consumer}</span><span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-bold">{item.status}</span></li>)}</ul></IslandCard><IslandCard><IslandTitle>Reviewer decisions</IslandTitle><p className="text-xs font-semibold text-slate-600">默认只读；决定只写 isolated Shadow audit，不重写 legacy report。</p><div className="mt-2 space-y-1">{decisions.length ? decisions.map((decision) => <div key={decision.decision_id} className="rounded-lg border border-slate-100 p-2 text-xs"><strong>{decision.decision}</strong> · {decision.stage} · {decision.reviewer}<br/><span>{decision.note || "无备注"}</span></div>) : <p className="text-xs text-slate-500">暂无已审计决定。</p>}</div><textarea value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} placeholder="复核备注（可选）" className="mt-2 w-full rounded-xl border-2 border-slate-200 p-2 text-sm" rows={2}/><div className="mt-2 flex flex-wrap gap-2"><IslandButton type="button" variant="secondary" onClick={() => void saveDecision("accept_shadow")}>接受诊断</IslandButton><IslandButton type="button" variant="secondary" onClick={() => void saveDecision("reject_shadow")}>拒绝候选</IslandButton><IslandButton type="button" variant="quiet" onClick={() => void saveDecision("defer")}>稍后复核</IslandButton></div></IslandCard></div>
      <IslandCard><IslandTitle>Reviewer notes</IslandTitle><div className="flex gap-2"><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录这次 Shadow 复核" className="min-w-0 flex-1 rounded-xl border-2 border-slate-200 px-3 py-2"/><IslandButton type="button" onClick={() => void saveNote()} disabled={!note.trim()}>保存备注</IslandButton></div><ul className="mt-3 space-y-1 text-sm">{selected.notes.map((item, index) => <li key={`${item.created_at}-${index}`}><strong>{item.author}</strong> · {item.note}</li>)}</ul></IslandCard>
    </> : <IslandCard><p>输入 analysis ID 后查看 legacy / V2 side-by-side checkpoints。</p></IslandCard>}
  </div>;
}
