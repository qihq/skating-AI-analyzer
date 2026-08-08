import type {
  AnalysisExperienceV2,
  ExperienceClaim,
  ExperienceEvent,
  ExperienceReviewTask,
  ExperienceStatus,
  ProfileMomentKey,
} from "./contracts";
import { MOMENT_LABELS, orderedMoments } from "./momentSelectors";
import { actionFamilyLabel } from "./profilePresentation";

const INTERNAL_TERMS = /\b(?:path\s*[ab]|reid|identity margin|pipeline hash|optical[- ]flow aliasing)\b/gi;
const SUMMARY_TYPES = ["report_summary", "analysis_summary", "summary"];
const NEXT_ACTION_TYPES = ["next_action", "review_action", "training_focus"];
const OBSERVATION_TYPES = new Set(["visible_observation", "technique_observation", "observation", "positive_observation"]);

export type FamilyClaimState = "confirmed" | "needs_review" | "unobservable";

export interface FamilyClaimView {
  claim: ExperienceClaim;
  title: string;
  text: string;
  state: FamilyClaimState;
  note: string | null;
}

export interface FamilyEventView {
  event: ExperienceEvent;
  label: string;
  interval: string | null;
  state: FamilyClaimState;
  stateLabel: string;
  summary: string;
  observations: FamilyClaimView[];
  nextAction: FamilyClaimView | null;
}

export interface FamilyAnalysisView {
  authorityLabel: string;
  summary: string;
  state: FamilyClaimState;
  stateLabel: string;
  events: FamilyEventView[];
  selectedEvent: FamilyEventView | null;
  observations: FamilyClaimView[];
  nextAction: FamilyClaimView | null;
  reviewTask: ExperienceReviewTask | null;
  reviewActionLabel: string | null;
  excludedClaimCount: number;
  exclusionLabel: string | null;
  poseSummary: string;
  confirmedClaimCount: number;
  compatibilityGroups: string[];
  /** Family-safe score projection. Raw report/bio fields never cross this boundary. */
  forceScore: number | null;
  profile: string | null;
}

export interface FamilyComparisonDelta {
  key: string;
  label: string;
  before: number;
  after: number;
  delta: number;
  unit: string | null;
  claimType: string;
  definitionVersion: string;
  compatibilityGroup: string | null;
}

export interface FamilyComparisonView {
  compatible: boolean;
  reason: string | null;
  crossDefinition: boolean;
  scoreBefore: number | null;
  scoreAfter: number | null;
  scoreDelta: number | null;
  deltas: FamilyComparisonDelta[];
  excludedCount: number;
  momentChips: FamilyComparisonMoment[];
}

export interface FamilyComparisonMoment {
  key: ProfileMomentKey;
  label: string;
  beforePtsSec: number;
  afterPtsSec: number;
  definitionVersion: string;
}

function record(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function safeText(value: unknown): string | null {
  if (typeof value === "string") {
    const text = value.replace(INTERNAL_TERMS, "内部证据").trim();
    return text || null;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  const item = record(value);
  if (!item) return null;
  for (const key of ["text", "summary", "description", "observation", "action", "label", "value"]) {
    const result = safeText(item[key]);
    if (result) return result;
  }
  return null;
}

function numericValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function comparisonMomentChips(left: AnalysisExperienceV2, right: AnalysisExperienceV2): FamilyComparisonMoment[] {
  if (left.authority !== right.authority) return [];
  const leftEvent = presentAnalysisExperience(left).selectedEvent?.event ?? null;
  const rightEvent = presentAnalysisExperience(right).selectedEvent?.event ?? null;
  if (!leftEvent || !rightEvent || leftEvent.profile !== rightEvent.profile) return [];
  if (leftEvent.definitionVersion && rightEvent.definitionVersion && leftEvent.definitionVersion !== rightEvent.definitionVersion) return [];
  const rightMoments = new Map(orderedMoments(rightEvent).map((moment) => [moment.semanticKey, moment]));
  return orderedMoments(leftEvent).flatMap((leftMoment) => {
    const rightMoment = rightMoments.get(leftMoment.semanticKey);
    if (!rightMoment || leftMoment.status !== "confirmed" || rightMoment.status !== "confirmed") return [];
    if (leftMoment.observability !== "observed" || rightMoment.observability !== "observed") return [];
    if (leftMoment.ptsSec == null || rightMoment.ptsSec == null) return [];
    if (leftMoment.definitionVersion !== rightMoment.definitionVersion) return [];
    return [{ key: leftMoment.semanticKey, label: MOMENT_LABELS[leftMoment.semanticKey], beforePtsSec: leftMoment.ptsSec, afterPtsSec: rightMoment.ptsSec, definitionVersion: leftMoment.definitionVersion }];
  });
}

function claimCanCompare(claim: ExperienceClaim): boolean {
  return claim.status === "confirmed" && claim.observability === "observable" && claim.value != null && claim.permissions?.comparison !== false;
}

function claimLabel(claimType: string): string {
  const labels: Record<string, string> = {
    force_score: "综合评分",
    quality_score: "综合评分",
    score: "综合评分",
    metric_air_time_seconds: "腾空时间",
    metric_estimated_height_cm: "高度参考",
    metric_takeoff_speed_mps: "起跳速度",
    metric_rotation_rps: "旋转速度",
    metric_estimated_rotations: "旋转圈数参考",
  };
  return labels[claimType] ?? claimType.replace(/^metric_/, "").replace(/_/g, " ");
}

function claimTitle(type: string): string {
  const labels: Record<string, string> = {
    action_family: "动作大类", stage_range: "动作阶段", visible_observation: "画面观察",
    technique_observation: "技术观察", rotation: "转体观察", moment: "关键时刻",
    next_action: "下一步", review_action: "下一步", training_focus: "练习重点",
    report_summary: "本次总结", analysis_summary: "本次总结", summary: "本次总结",
  };
  return labels[type] ?? "复盘观察";
}

function claimState(claim: ExperienceClaim): FamilyClaimState {
  if (claim.status === "unobservable" || claim.observability === "unobservable" || claim.value == null) return "unobservable";
  if (claim.status === "uncertain" || claim.observability === "partially_observable" || Boolean(claim.conflicts?.length)) return "needs_review";
  return "confirmed";
}

function statusLabel(state: FamilyClaimState): string {
  if (state === "confirmed") return "已确认";
  if (state === "needs_review") return "需要确认";
  return "画面不足，暂不判断";
}

function statusNote(claim: ExperienceClaim, state: FamilyClaimState): string | null {
  if (state === "unobservable") return "这项内容没有足够画面证据，因此不会补入旧结论。";
  if (claim.conflicts?.length) return "可用证据之间不一致，暂时保留分歧，不显示精确结论。";
  if (state === "needs_review") return "当前只显示画面能够支持的有限结论。";
  return null;
}

function claimForFamily(claim: ExperienceClaim): FamilyClaimView | null {
  const state = claimState(claim);
  if (state === "unobservable") {
    return { claim, title: claimTitle(claim.claimType), text: "画面不足，暂不判断", state, note: statusNote(claim, state) };
  }
  const text = safeText(claim.value);
  if (!text) return null;
  if (claim.conflicts?.length && (claim.claimType === "rotation" || claim.claimType === "moment")) {
    return { claim, title: claimTitle(claim.claimType), text: "存在不同证据，暂不显示精确结果", state: "needs_review", note: statusNote(claim, "needs_review") };
  }
  return { claim, title: claimTitle(claim.claimType), text, state, note: statusNote(claim, state) };
}

function claimsForScope(experience: AnalysisExperienceV2, eventId: string | null): ExperienceClaim[] {
  return experience.claims.filter((claim) => claim.eventId == null || claim.eventId === eventId);
}

function firstClaim(claims: ExperienceClaim[], types: string[]): FamilyClaimView | null {
  for (const type of types) {
    const views = claims.filter((claim) => claim.claimType === type).map(claimForFamily).filter((item): item is FamilyClaimView => Boolean(item));
    const confirmed = views.find((item) => item.state === "confirmed");
    if (confirmed) return confirmed;
    if (views[0]) return views[0];
  }
  return null;
}

function eventState(event: ExperienceEvent, claims: ExperienceClaim[]): FamilyClaimState {
  if (event.status === "unobservable" || event.observability === "unobservable") return "unobservable";
  if (event.status === "uncertain" || event.observability === "partially_observable" || event.state === "ambiguous" || event.state === "unknown" || claims.some((claim) => claimState(claim) === "needs_review")) return "needs_review";
  return "confirmed";
}

function interval(event: ExperienceEvent): string | null {
  if (event.startPts == null || event.endPts == null) return null;
  return `${event.startPts.toFixed(2)}–${event.endPts.toFixed(2)} 秒`;
}

function eventSummary(event: ExperienceEvent, claims: ExperienceClaim[], state: FamilyClaimState): string {
  const summary = firstClaim(claims.filter((claim) => claim.eventId === event.eventId), SUMMARY_TYPES);
  if (summary && summary.state !== "unobservable") return summary.text;
  if (state === "unobservable") return "这段画面不足，暂时不判断动作细节。";
  if (state === "needs_review") return `已找到${actionFamilyLabel(event.profile)}片段，但部分结论仍需要确认。`;
  return `已确认一段${actionFamilyLabel(event.profile)}动作，可继续查看关键时刻和身体观察。`;
}

function reviewAction(task: ExperienceReviewTask | null): string | null {
  if (!task) return null;
  const labels: Record<string, string> = {
    confirm_main_skater_anchor: "确认这段视频中的主滑行者",
    confirm_action_profile: "确认这段动作的大类",
    confirm_event_window: "确认这段动作的开始和结束",
    confirm_event_moment: "确认存在分歧的关键时刻",
    confirm_rotation: "逐帧确认转体区间",
  };
  const direct = labels[task.kind];
  if (direct) return direct;
  if (task.kind.includes("identity") || task.kind.includes("skater")) return "确认这段视频中的主滑行者";
  if (task.kind.includes("moment") || task.kind.includes("timing")) return "确认存在分歧的关键时刻";
  if (task.kind.includes("action") || task.kind.includes("profile")) return "确认这段动作的大类";
  return "打开家长复核，确认这项不确定内容";
}

function poseLanguage(experience: AnalysisExperienceV2, selected?: ExperienceEvent | null): string {
  const pose = selected?.pose ?? experience.pose;
  if (!pose || pose.status === "unavailable") return "身体与姿态证据暂不可用，不会用历史姿态数据补齐。";
  if (pose.status === "blocked" || pose.identity_blocked_frame_count > 0) return "部分画面没有确认到同一位滑行者，因此相关身体结论已隐藏。";
  if (pose.status === "partial" || pose.interpolated_display_only_count > 0 || pose.missing_joint_count > 0) return `姿态证据仅部分可用：${pose.authoritative_frame_count}/${pose.frame_count} 帧可用于技术解释；插值只用于画面连贯。`;
  return `姿态证据可用：${pose.authoritative_frame_count}/${pose.frame_count} 帧来自可追踪的测量或平滑结果。`;
}

export function presentAnalysisExperience(experience: AnalysisExperienceV2, selectedEventId?: string | null): FamilyAnalysisView {
  if (experience.claims.some((claim) => claim.authority !== experience.authority || claim.sourcePipelineFingerprint !== experience.sourcePipelineFingerprint)) throw new Error("mixed analysis authority");
  const events = experience.events.map((event): FamilyEventView => {
    const scoped = claimsForScope(experience, event.eventId);
    const state = eventState(event, scoped);
    return {
      event, label: `${actionFamilyLabel(event.profile)}${event.subtype ? ` · ${event.subtype}` : ""}`, interval: interval(event),
      state, stateLabel: statusLabel(state), summary: eventSummary(event, scoped, state),
      observations: scoped.filter((claim) => claim.eventId === event.eventId && OBSERVATION_TYPES.has(claim.claimType)).map(claimForFamily).filter((item): item is FamilyClaimView => Boolean(item)),
      nextAction: firstClaim(scoped.filter((claim) => claim.eventId === event.eventId), NEXT_ACTION_TYPES),
    };
  });
  const selectedEvent = events.find((event) => event.event.eventId === selectedEventId) ?? events[0] ?? null;
  const scoped = claimsForScope(experience, selectedEvent?.event.eventId ?? null);
  const topSummary = firstClaim(scoped, SUMMARY_TYPES);
  const observations = scoped.filter((claim) => OBSERVATION_TYPES.has(claim.claimType)).map(claimForFamily).filter((item): item is FamilyClaimView => Boolean(item));
  const state: FamilyClaimState = experience.familyUsable === false ? "needs_review" : selectedEvent?.state ?? (scoped.some((claim) => claimState(claim) === "unobservable") ? "unobservable" : scoped.some((claim) => claimState(claim) === "needs_review") ? "needs_review" : "confirmed");
  const reviewTask = experience.reviewTasks[0] ?? null;
  const excludedClaimCount = experience.claims.filter((claim) => claimState(claim) !== "confirmed").length;
  const scoreClaim = experience.claims.find((claim) => ["force_score", "quality_score", "score"].includes(claim.claimType) && claimCanCompare(claim));
  return {
    authorityLabel: experience.authority === "legacy" ? "历史完整记录" : "当前证据复盘",
    summary: topSummary && topSummary.state !== "unobservable" ? topSummary.text : selectedEvent?.summary ?? (state === "unobservable" ? "画面不足，暂不判断技术细节。" : "本次复盘已整理完成。"),
    state, stateLabel: statusLabel(state), events, selectedEvent, observations,
    nextAction: firstClaim(scoped, NEXT_ACTION_TYPES) ?? selectedEvent?.nextAction ?? null,
    reviewTask, reviewActionLabel: reviewAction(reviewTask), excludedClaimCount,
    exclusionLabel: excludedClaimCount ? `${excludedClaimCount} 项不确定、冲突或不可观察内容未进入确定结论。` : null,
    poseSummary: poseLanguage(experience, selectedEvent?.event),
    confirmedClaimCount: experience.claims.filter((claim) => claimState(claim) === "confirmed").length,
    compatibilityGroups: [...new Set(experience.claims.flatMap((claim) => claim.compatibilityGroup ? [claim.compatibilityGroup] : []))],
    forceScore: scoreClaim ? numericValue(scoreClaim.value) : null,
    profile: selectedEvent?.event.profile && selectedEvent.event.profile !== "unknown" ? selectedEvent.event.profile : null,
  };
}

export function canCompareExperiences(left: AnalysisExperienceV2, right: AnalysisExperienceV2): { compatible: boolean; reason: string | null; crossDefinition: boolean } {
  const leftView = presentAnalysisExperience(left);
  const rightView = presentAnalysisExperience(right);
  const a = leftView.selectedEvent;
  const b = rightView.selectedEvent;
  const incompatible = (reason: string, crossDefinition = false) => ({ compatible: false, reason, crossDefinition });
  if (!a || !b) return incompatible("至少一份复盘没有可匹配的动作事件。");
  const legacyProfileConfirmed = (experience: AnalysisExperienceV2, event: FamilyEventView) => experience.authority === "legacy" && ["jump", "spin", "step", "spiral"].includes(event.event.profile) && experience.claims.some((claim) => claim.eventId === event.event.eventId && ["action_profile", "action_family"].includes(claim.claimType) && claimCanCompare(claim));
  if ((a.state !== "confirmed" && !legacyProfileConfirmed(left, a)) || (b.state !== "confirmed" && !legacyProfileConfirmed(right, b))) return incompatible("只比较两边都已确认且可观察的动作事件。");
  if (a.event.profile !== b.event.profile) return incompatible("两次复盘的动作大类不同，不能计算技术变化。");
  if (a.event.definitionVersion && b.event.definitionVersion && a.event.definitionVersion !== b.event.definitionVersion) return incompatible("两次复盘使用了不同的动作定义，已拒绝无效差值。", true);
  const leftGroups = new Set(leftView.compatibilityGroups);
  const sharedGroup = rightView.compatibilityGroups.some((group) => leftGroups.has(group));
  if (leftView.compatibilityGroups.length && rightView.compatibilityGroups.length && !sharedGroup) return incompatible("两次复盘的技术定义不兼容，已拒绝无效差值。", true);
  return { compatible: true, reason: null, crossDefinition: left.authority !== right.authority };
}

/** Build a family-safe comparison projection from the two authority envelopes. */
export function presentComparison(left: AnalysisExperienceV2, right: AnalysisExperienceV2): FamilyComparisonView {
  if (left.authority !== right.authority) {
    return { compatible: false, reason: "两次复盘来源不一致，不能计算技术变化。", crossDefinition: true, scoreBefore: null, scoreAfter: null, scoreDelta: null, deltas: [], excludedCount: left.claims.length + right.claims.length, momentChips: [] };
  }
  const compatibility = canCompareExperiences(left, right);
  const leftView = presentAnalysisExperience(left);
  const rightView = presentAnalysisExperience(right);
  if (!compatibility.compatible) {
    return { ...compatibility, scoreBefore: leftView.forceScore, scoreAfter: rightView.forceScore, scoreDelta: null, deltas: [], excludedCount: left.claims.length + right.claims.length, momentChips: [] };
  }
  const rightByKey = new Map<string, ExperienceClaim>();
  right.claims.filter(claimCanCompare).forEach((claim) => rightByKey.set(`${claim.claimType}\u001f${claim.compatibilityGroup ?? ""}`, claim));
  const deltas: FamilyComparisonDelta[] = [];
  let excludedCount = 0;
  left.claims.filter(claimCanCompare).forEach((claim) => {
    const before = numericValue(claim.value);
    const afterClaim = rightByKey.get(`${claim.claimType}\u001f${claim.compatibilityGroup ?? ""}`);
    const after = afterClaim ? numericValue(afterClaim.value) : null;
    if (before == null || after == null || claim.definitionVersion !== afterClaim?.definitionVersion || claim.unit !== afterClaim?.unit || claim.convention !== afterClaim?.convention) {
      excludedCount += 1;
      return;
    }
    deltas.push({ key: claim.claimType, label: claimLabel(claim.claimType), before, after: after as number, delta: (after as number) - before, unit: claim.unit ?? null, claimType: claim.claimType, definitionVersion: claim.definitionVersion, compatibilityGroup: claim.compatibilityGroup ?? null });
  });
  const scoreBefore = leftView.forceScore;
  const scoreAfter = rightView.forceScore;
  return { ...compatibility, scoreBefore, scoreAfter, scoreDelta: scoreBefore != null && scoreAfter != null ? scoreAfter - scoreBefore : null, deltas, excludedCount, momentChips: comparisonMomentChips(left, right) };
}

export function claimStatusForFamily(status: ExperienceStatus, observability: ExperienceClaim["observability"]): FamilyClaimState {
  return status === "unobservable" || observability === "unobservable" ? "unobservable" : status === "uncertain" || observability === "partially_observable" ? "needs_review" : "confirmed";
}
