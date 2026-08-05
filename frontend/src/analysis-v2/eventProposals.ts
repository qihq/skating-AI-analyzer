import type { AnalysisExperienceV2, ExperienceEvent, ExperienceReviewTask } from "./contracts";

export type ProposalSelection = { eventId: string | null; event: ExperienceEvent | null };

export function orderedProposalEvents(experience: AnalysisExperienceV2): ExperienceEvent[] {
  return [...experience.events].sort((left, right) => (left.startPts ?? Number.POSITIVE_INFINITY) - (right.startPts ?? Number.POSITIVE_INFINITY) || left.eventId.localeCompare(right.eventId));
}

export function selectProposalEvent(experience: AnalysisExperienceV2, eventId: string | null | undefined): ProposalSelection {
  const events = orderedProposalEvents(experience);
  const event = events.find((item) => item.eventId === eventId) ?? events[0] ?? null;
  return { eventId: event?.eventId ?? null, event };
}

export function proposalDeepLink(analysisId: string, eventId: string): string {
  return `/analysis/${encodeURIComponent(analysisId)}?event=${encodeURIComponent(eventId)}`;
}

export function rotationReviewDeepLink(analysisId: string, task: Pick<ExperienceReviewTask, "eventId" | "startPts">): string {
  if (!task.eventId || task.startPts == null || !Number.isFinite(task.startPts)) throw new Error("rotation review task requires exact event and source PTS");
  return `/analysis/${encodeURIComponent(analysisId)}?view=moments&event=${encodeURIComponent(task.eventId)}&t=${task.startPts}`;
}

export function proposalTimelineMarkers(experience: AnalysisExperienceV2): Array<{ id: string; timestamp: number; label: string }> {
  return orderedProposalEvents(experience).flatMap((event, index) => {
    const markers: Array<{ id: string; timestamp: number; label: string }> = [];
    if (event.startPts != null) markers.push({ id: `${event.eventId}:start`, timestamp: event.startPts, label: `Event ${index + 1} start` });
    if (event.endPts != null) markers.push({ id: `${event.eventId}:end`, timestamp: event.endPts, label: `Event ${index + 1} end` });
    return markers;
  });
}
