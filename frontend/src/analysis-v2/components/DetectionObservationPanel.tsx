import { useEffect, useState } from "react";
import axios from "axios";
import { useAppMode } from "../../components/AppModeContext";
import { IslandCard, IslandTitle } from "../../modern/IslandSurface";
import { fetchDetectionObservations, fetchPilot12DetectionDiagnostics } from "../api";
import { DetectionProposalDiagnostics } from "../contracts";

export default function DetectionObservationPanel({ analysisId }: { analysisId?: string }) {
  const { isParentMode, parentPin, enterParentMode } = useAppMode();
  const [data, setData] = useState<DetectionProposalDiagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!isParentMode || !parentPin) return;
    if (!analysisId) {
      void fetchPilot12DetectionDiagnostics(parentPin).then((next) => setData({ ...next, schema_version: "detection-proposal-diagnostics.v1", status: next.status === "unavailable" ? "unavailable" : "complete", provider: "pilot-12-fixture", detector: "yolo", tracker: "bytetrack", model_source: "legacy-fixture", model_hash: null, dependency_ready: false, candidates: [], short_tracks: [], camera: [], anchor_suggestions: [], candidate_recall: null, diagnostics_fingerprint: String(next.result_fingerprint ?? "unavailable"), invalidation_scope: "shadow_diagnostics_only", ds918_compatible: true, candidate_recall_counts: (next.candidate_recall_counts as Record<string, number> | undefined) ?? {} } as DetectionProposalDiagnostics)).catch((e: unknown) => setError(axios.isAxiosError(e) ? "诊断暂时不可用" : "读取失败"));
      return;
    }
    void fetchDetectionObservations(parentPin, analysisId).then(setData).catch((e: unknown) => setError(axios.isAxiosError(e) ? "诊断暂时不可用" : "读取失败"));
  }, [analysisId, isParentMode, parentPin]);
  if (!isParentMode) return <IslandCard tone="sun"><IslandTitle>Detection observations</IslandTitle><p>仅家长可见。</p><button className="island-button island-button--primary" onClick={() => void enterParentMode()}>进入家长模式</button></IslandCard>;
  if (!analysisId && !data) return <IslandCard><div aria-live="polite"><p>正在读取 12-video candidate recall…</p></div></IslandCard>;
  if (error) return <IslandCard tone="sun"><div role="alert"><IslandTitle>Detection observations</IslandTitle><p>{error}</p></div></IslandCard>;
  if (!data) return <IslandCard><div aria-live="polite"><p>正在读取候选轨迹…</p></div></IslandCard>;
  return <IslandCard tone={data.status === "complete" ? "mint" : "sun"}><IslandTitle>Detection observations</IslandTitle><h2>{data.status}</h2><dl className="modern-runtime-status"><div><dt>候选 / short tracks</dt><dd>{data.candidates.length} / {data.short_tracks.length}{!analysisId && data.candidate_recall_counts ? ` · 12 条视频 / ${data.candidate_recall_counts.candidate_tracks ?? 0} tracks` : ""}</dd></div><div><dt>Camera reliability</dt><dd>{data.camera.length ? Math.round((Number(data.camera[0].reliability ?? 0)) * 100) + "%" : "未运行"}</dd></div><div><dt>Anchor suggestions</dt><dd>{data.anchor_suggestions.length}</dd></div><div><dt>Detector / tracker</dt><dd>{data.detector} / {data.tracker}</dd></div></dl><p>仅诊断建议，不会修改 identity 或 Golden label。</p></IslandCard>;
}
