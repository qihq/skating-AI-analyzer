import type { AnalysisDetail, SelectedSemanticFrame } from "../api/client";
import { buildCurrentKeyframeEvidenceItems } from "../utils/keyframeEvidence";
import type { MediaMarker } from "./types";

function semanticMarkers(frames: SelectedSemanticFrame[]): MediaMarker[] {
  return frames.flatMap((frame, index) => {
    if (typeof frame.timestamp !== "number" || !Number.isFinite(frame.timestamp)) return [];
    const label = frame.phase_label ?? frame.phase_code ?? frame.key_moment ?? `关键帧 ${index + 1}`;
    return [{ id: `semantic-${frame.frame_id ?? index}`, label, timestamp: frame.timestamp, phase: frame.phase_code ?? undefined }];
  });
}

// Keep all evidence groups visible: a semantic candidate must not erase T/A/L evidence.
export function analysisMediaMarkers(analysis: AnalysisDetail, includePartial = true): MediaMarker[] {
  const seen = new Set<string>();
  const add = (marker: MediaMarker) => {
    const key = `${marker.label}-${marker.timestamp.toFixed(3)}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [marker];
  };
  const current = buildCurrentKeyframeEvidenceItems(analysis).flatMap((item) =>
    item.timestamp == null ? [] : add({ id: `keyframe-${item.key}`, label: item.key, timestamp: item.timestamp, phase: item.key }),
  );
  const selected = semanticMarkers(analysis.video_temporal_diagnostics?.selected_semantic_frames ?? []).flatMap(add);
  const partial = includePartial
    ? semanticMarkers(analysis.video_temporal_diagnostics?.partial_semantic_frames ?? []).flatMap((marker) => add({ ...marker, id: `partial-${marker.id}`, label: `候选 ${marker.label}` }))
    : [];
  return [...current, ...selected, ...partial].sort((left, right) => left.timestamp - right.timestamp);
}
