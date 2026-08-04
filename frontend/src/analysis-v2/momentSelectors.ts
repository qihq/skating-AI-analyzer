import type { EventMomentSetV2, ExperienceEvent, KeyMomentV2, KnownActionProfile, ProfileMomentKey } from "./contracts";
import type { MediaMarker } from "../media/types";

export const PROFILE_MOMENT_ORDER: Record<KnownActionProfile, ProfileMomentKey[]> = {
  jump: ["takeoff", "apex", "landing"],
  spin: ["spin_entry", "spin_main", "spin_exit"],
  spiral: ["spiral_entry", "spiral_hold", "spiral_exit"],
  step: ["step_sequence_interval", "step_representative_1", "step_representative_2", "step_representative_3"],
};

export const MOMENT_LABELS: Record<ProfileMomentKey, string> = {
  takeoff: "起跳", apex: "最高点", landing: "落冰",
  spin_entry: "入转", spin_main: "主转", spin_exit: "出转",
  spiral_entry: "进入", spiral_hold: "保持", spiral_exit: "退出",
  step_sequence_interval: "步法区间", step_representative_1: "代表时刻 1", step_representative_2: "代表时刻 2", step_representative_3: "代表时刻 3",
};

export function orderedMoments(event: ExperienceEvent | null | undefined): KeyMomentV2[] {
  if (!event?.moments || event.profile === "unknown" || !(event.profile in PROFILE_MOMENT_ORDER)) return [];
  const byKey = new Map(event.moments.moments.map((moment) => [moment.semanticKey, moment]));
  return PROFILE_MOMENT_ORDER[event.profile as KnownActionProfile].map((key) => byKey.get(key)).filter((value): value is KeyMomentV2 => Boolean(value));
}

export function momentMarkers(set: EventMomentSetV2 | null | undefined): MediaMarker[] {
  if (!set) return [];
  return set.moments.flatMap((moment) => moment.status === "unavailable" || moment.ptsSec == null ? [] : [{ id: `v2-moment-${set.eventId}-${moment.semanticKey}`, label: MOMENT_LABELS[moment.semanticKey], timestamp: moment.ptsSec, phase: moment.semanticKey }]);
}

export function selectedMomentThumbnail(set: EventMomentSetV2 | null | undefined, semanticKey?: ProfileMomentKey): { sourceFrameIndex: number; sourcePtsSec: number; semanticKey: ProfileMomentKey } | null {
  if (!set) return null;
  const preferred = semanticKey ? [semanticKey] : set.profile === "jump" ? ["apex", "takeoff", "landing"] : set.profile === "spin" ? ["spin_main", "spin_entry", "spin_exit"] : set.profile === "spiral" ? ["spiral_hold", "spiral_entry", "spiral_exit"] : ["step_representative_1", "step_sequence_interval"];
  for (const key of preferred) { const item = set.moments.find((moment) => moment.semanticKey === key); if (item && item.status === "confirmed" && item.sourceFrameIndex != null && item.ptsSec != null) return { sourceFrameIndex: item.sourceFrameIndex, sourcePtsSec: item.ptsSec, semanticKey: item.semanticKey }; }
  return null;
}
