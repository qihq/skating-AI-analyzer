import { useEffect, useState } from "react";
import { fetchAnalysis, fetchAnalysisPose, type AnalysisDetail } from "../api/client";
import { hasCurrentJumpStages } from "../utils/keyframeEvidence";
import type { AnalysisExperienceV2 } from "./contracts";

/** Only the ordinary whole-analysis legacy event owns this TAL contract.
 * Independent V2 moments, shadow diagnostics and other selected events keep
 * their existing authority, even if old bio data also exists on the row.
 */
export function savedJumpReplayScope(experience: AnalysisExperienceV2 | null, selectedEventId: string | null): boolean {
  return !!experience && experience.authority === "legacy" && experience.pipelineMode === "legacy"
    && experience.familyUsable && !experience.diagnosticOnly && experience.events.length === 1
    && selectedEventId === experience.analysisId + ":event:0"
    && experience.events[0].eventId === selectedEventId && !experience.events[0].moments;
}
export function useSavedJumpReplay(experience: AnalysisExperienceV2 | null, selectedEventId: string | null, enabled = true) {
  const eligible = enabled && savedJumpReplayScope(experience, selectedEventId);
  const key = eligible ? experience!.analysisId + ":" + experience!.sourcePipelineFingerprint + ":" + selectedEventId : null;
  const [saved, setSaved] = useState<{key:string; analysis:AnalysisDetail} | null>(null);
  useEffect(() => {
    if (!key || !experience) { setSaved(null); return; }
    let cancelled=false;
    setSaved(null);
    void fetchAnalysis(experience.analysisId).then(async analysis => {
      if (analysis.id !== experience.analysisId || (analysis.facts_authority === "v2" || analysis.bio_data?.jump_stage_contract !== "tal-evidence.v1")) return;
      // A failed pose read may not resurrect old pose or another result's state.
      const pose = await fetchAnalysisPose(analysis.id).catch(() => null);
      if (!cancelled) setSaved({key, analysis:{...analysis, pose_data:pose}});
    }).catch(() => { if (!cancelled) setSaved(null); });
    return () => { cancelled=true; };
  }, [key]);
  return saved?.key === key ? saved?.analysis ?? null : null;
}
