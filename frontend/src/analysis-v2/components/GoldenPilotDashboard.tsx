import { useEffect, useMemo, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import { IslandButton, IslandCard, IslandTitle } from "../../modern/IslandSurface";
import { fetchPilotEvaluatorResult, fetchPilotEvaluatorStatus, fetchPilotEventDiagnostic, fetchPilotProgress } from "../api";
import type { MetricRate, PilotEvaluatorStatus, PilotProgress, PilotSanitizedResult } from "../golden-contracts";

type DashboardState = "loading" | "ready" | "error";
type DrillDownState =
  | { alias: string; status: "loading" | "error"; detail: null }
  | { alias: string; status: "ready"; detail: { eventId: string; pts: number } };

function RateView({ label, metric }: { label: string; metric: MetricRate }) {
  const interval = metric.confidence_interval_95;
  return <div><dt>{label}</dt><dd>{metric.numerator}/{metric.denominator}{metric.rate === null ? "" : ` (${(metric.rate * 100).toFixed(1)}%)`}{interval ? `, 95% CI ${(interval[0] * 100).toFixed(1)}-${(interval[1] * 100).toFixed(1)}%` : ""}</dd></div>;
}

function isRate(value: unknown): value is MetricRate {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.numerator === "number" && typeof item.denominator === "number" && (typeof item.rate === "number" || item.rate === null);
}

function metricRates(result: PilotSanitizedResult | null) {
  if (!result) return [];
  const rows: Array<{ label: string; metric: MetricRate }> = [];
  for (const [section, rawSection] of Object.entries(result.aggregate)) {
    if (!rawSection || typeof rawSection !== "object" || section === "strata") continue;
    for (const [name, value] of Object.entries(rawSection as Record<string, unknown>)) {
      if (isRate(value)) rows.push({ label: `${section} / ${name}`, metric: value });
    }
  }
  return rows;
}

export default function GoldenPilotDashboard() {
  const { parentPin } = useAppMode();
  const [state, setState] = useState<DashboardState>("loading");
  const [status, setStatus] = useState<PilotEvaluatorStatus | null>(null);
  const [progress, setProgress] = useState<PilotProgress | null>(null);
  const [result, setResult] = useState<PilotSanitizedResult | null>(null);
  const [drillDown, setDrillDown] = useState<DrillDownState | null>(null);
  const rates = useMemo(() => metricRates(result), [result]);

  const load = async () => {
    if (!parentPin) return;
    setState("loading");
    try {
      const [nextProgress, nextStatus, nextResult] = await Promise.all([fetchPilotProgress(parentPin), fetchPilotEvaluatorStatus(parentPin), fetchPilotEvaluatorResult(parentPin)]);
      setProgress(nextProgress); setStatus(nextStatus); setResult(nextResult); setState("ready");
    } catch { setState("error"); }
  };
  useEffect(() => { void load(); }, [parentPin]);
  const openDiagnostic = async (alias: string) => {
    if (!parentPin) return;
    setDrillDown({ alias, status: "loading", detail: null });
    try {
      const detail = await fetchPilotEventDiagnostic(parentPin, alias);
      if (typeof detail.event_id !== "string" || typeof detail.source_pts !== "number") throw new Error("Invalid private diagnostic response");
      setDrillDown({ alias, status: "ready", detail: { eventId: detail.event_id, pts: detail.source_pts } });
    } catch {
      setDrillDown({ alias, status: "error", detail: null });
    }
  };

  if (state === "loading") return <IslandCard className="modern-me-panel" aria-live="polite"><p>Loading Golden pilot progress and evaluator state...</p></IslandCard>;
  if (state === "error" || !progress || !status) return <IslandCard className="modern-me-panel" tone="sun"><div role="alert"><h2>Pilot dashboard unavailable</h2><p>No labels or metrics were changed. Retry this parent-only view.</p></div></IslandCard>;
  const waiting = progress.status === "waiting_for_owner_labels";
  const req = progress.requirements;
  const evaluatorPolicyLabel = result ? (result.gate_policy_version === "golden-gate-policy.v2" ? result.gate_policy_version : "golden-gate-policy.v1 (legacy evidence)") : null;
  return <section className="golden-pilot" aria-labelledby="golden-pilot-heading">
    <IslandCard className="modern-me-panel" tone={waiting ? "sun" : "mint"}><IslandTitle>Animal Island Golden pilot</IslandTitle><h2 id="golden-pilot-heading">{waiting ? "Waiting for owner labels" : "Ready for pilot evaluation"}</h2><p>This is {progress.gate_policy_version} limited_sample evidence and remains diagnostic only. It is never a release dataset or accuracy claim.</p>{evaluatorPolicyLabel ? <p>Evaluator evidence: {evaluatorPolicyLabel}</p> : null}<dl className="modern-runtime-status"><div><dt>Evaluator</dt><dd>{status.status}</dd></div><div><dt>Videos</dt><dd>{req.source_video_count?.count ?? 0}/{req.source_video_count?.target ?? 0}</dd></div><div><dt>Events</dt><dd>{req.event_count?.count ?? 0}/{req.event_count?.target ?? 0}</dd></div><div><dt>Sessions</dt><dd>{req.recording_sessions?.count ?? 0}/{req.recording_sessions?.target ?? 0}</dd></div><div><dt>Schema-valid</dt><dd>{req.schema_valid?.count ?? 0}/{req.schema_valid?.target ?? 0}</dd></div><div><dt>Delayed review</dt><dd>{req.delayed_review?.count ?? 0}/{req.delayed_review?.target ?? 0}</dd></div></dl>{progress.next_actions.length ? <ul>{progress.next_actions.map((action) => <li key={action}>{action}</li>)}</ul> : null}</IslandCard>
    <div className="golden-pilot__grid"><IslandCard className="modern-me-panel"><IslandTitle>Profile gaps</IslandTitle><dl className="modern-runtime-status">{progress.profiles.map((item) => <div key={item.key}><dt>{item.key}</dt><dd>{item.count}/{item.target} · missing {item.missing}</dd></div>)}</dl></IslandCard><IslandCard className="modern-me-panel"><IslandTitle>Scene strata gaps</IslandTitle><dl className="modern-runtime-status">{progress.scenes.map((item) => <div key={item.key}><dt>{item.key}</dt><dd>{item.count}/{item.target} · missing {item.missing}</dd></div>)}</dl></IslandCard></div>
    {waiting && progress.next_best_videos.length ? <IslandCard className="modern-me-panel"><IslandTitle>Best next videos</IslandTitle><p>Use the private source browser and annotation form on this page. Prioritize: {progress.next_best_videos.join(", ")}.</p><p>Use distinct real actions and recording sessions. Do not reuse historic debug media, duplicate clips, or algorithm suggestions as Ground Truth.</p></IslandCard> : null}
    <IslandCard className="modern-me-panel"><IslandTitle>Denominators, coverage, refusal, and confidence</IslandTitle>{result ? <dl className="modern-runtime-status">{rates.length ? rates.map((row) => <RateView key={row.label} {...row}/>) : <div><dt>Metrics</dt><dd>No evaluated denominators</dd></div>}</dl> : <p>No diagnostic result has run for this dataset fingerprint.</p>}</IslandCard>
    <IslandCard className="modern-me-panel"><IslandTitle>Strata and confusion</IslandTitle>{result ? <pre className="golden-pilot__matrix" aria-label="Sanitized strata and confusion metrics">{JSON.stringify({ strata: result.aggregate.strata, action: result.aggregate.action }, null, 2)}</pre> : <p>Strata metrics appear only after a valid run and always include raw counts.</p>}</IslandCard>
    <IslandCard className="modern-me-panel"><IslandTitle>Failed-event review</IslandTitle>{result?.failed_events.length ? <ul>{result.failed_events.map((item) => <li key={item.alias}><button type="button" className="golden-pilot__drill" onClick={() => void openDiagnostic(item.alias)}>{item.alias}: {item.failure_codes.join(", ")}</button></li>)}</ul> : <p>{result ? "No failed event in the latest diagnostic run." : "No run yet. Labels cannot be changed from this dashboard."}</p>}{drillDown ? <p role="status">{drillDown.status === "ready" ? <a href={`/golden?event=${encodeURIComponent(drillDown.detail.eventId)}&pts=${drillDown.detail.pts}`}>Open {drillDown.alias} at exact source PTS {drillDown.detail.pts.toFixed(6)}</a> : drillDown.status === "error" ? `Private source PTS for ${drillDown.alias} is unavailable. Retry the event link.` : `Loading private source PTS for ${drillDown.alias}...`} Review here never mutates Ground Truth.</p> : null}</IslandCard>
    <IslandButton variant="secondary" onClick={() => void load()}>Refresh pilot status</IslandButton>
  </section>;
}
