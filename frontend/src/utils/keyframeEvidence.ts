import type { AnalysisDetail, SelectedSemanticFrame } from "../api/client";
import type { AnalysisExperienceV2, ExperienceEvent, KeyMomentV2, ProfileMomentKey } from "../analysis-v2/contracts";
import { MOMENT_LABELS, orderedMoments } from "../analysis-v2/momentSelectors";

export type KeyframeKey =
  | "T"
  | "A"
  | "L"
  | "spin_entry"
  | "spin_main"
  | "spin_exit"
  | "spiral_hold"
  | "step_sequence"
  | ProfileMomentKey;
export type KeyframeSyncPatch = Partial<Record<KeyframeKey, string>>;

type FrameRef = {
  value: string;
  frameId: string | null;
  imageUrl: string | null;
  timestamp: number | null;
};

export type KeyframeEvidenceItem = {
  key: KeyframeKey;
  label: string;
  value: string;
  frameId: string | null;
  imageUrl: string | null;
  timestamp: number | null;
  source: string;
  status: string | null;
  confidence: number | null;
  reason: string | null;
};

type EvidenceBuildContext = {
  timestampByFrame: Map<string, number>;
  semanticMatches: ReturnType<typeof semanticLookup>;
};

export const KEYFRAME_ORDER: KeyframeKey[] = ["T", "A", "L"];
export const SPIN_KEYFRAME_ORDER: KeyframeKey[] = ["spin_entry", "spin_main", "spin_exit"];
export const SPIRAL_KEYFRAME_ORDER: KeyframeKey[] = ["spiral_hold"];
export const STEP_KEYFRAME_ORDER: KeyframeKey[] = ["step_sequence"];
export const KEYFRAME_LABELS: Record<string, string> = {
  T: "起跳",
  A: "腾空",
  L: "落冰",
};

Object.assign(KEYFRAME_LABELS, {
  spin_entry: "入转",
  spin_main: "主转",
  spin_exit: "出转",
  spiral_hold: "姿态保持",
  step_sequence: "步法区间",
  takeoff: "起跳",
  apex: "最高点",
  landing: "落冰",
  spiral_entry: "进入",
  spiral_exit: "退出",
  step_sequence_interval: "步法区间",
  step_representative_1: "代表时刻 1",
  step_representative_2: "代表时刻 2",
  step_representative_3: "代表时刻 3",
});

/**
 * Build a keyframe projection directly from the V2 authority envelope.
 *
 * This is deliberately separate from the legacy evidence builders below:
 * ordinary V2 pages must never inspect bio_data or temporal diagnostics to
 * render moments.  The projection carries source PTS/frame identity only;
 * image resolution remains a parent-only concern and is therefore omitted.
 */
export function buildExperienceKeyframeEvidenceItems(
  experience: AnalysisExperienceV2,
  selectedEventId?: string | null,
): KeyframeEvidenceItem[] {
  const event = experience.events.find((item) => item.eventId === selectedEventId) ?? experience.events[0] ?? null;
  if (!event) return [];
  return orderedMoments(event).map((moment) => experienceMomentItem(moment));
}

/** Parent-review draft projection paired with a V2 event. */
export function buildExperienceDraftKeyframeEvidenceItems(
  experience: AnalysisExperienceV2,
  draftKeyframes: Partial<Record<KeyframeKey, string>>,
  selectedEventId?: string | null,
): KeyframeEvidenceItem[] {
  const event = experience.events.find((item) => item.eventId === selectedEventId) ?? experience.events[0] ?? null;
  if (!event) return [];
  return orderedMoments(event).map((moment) => {
    const item = experienceMomentItem(moment);
    const draft = cleanString(draftKeyframes[moment.semanticKey]);
    return draft ? { ...item, value: draft, frameId: draft, source: "parent review draft", status: "confirmed" } : item;
  });
}

function experienceMomentItem(moment: KeyMomentV2): KeyframeEvidenceItem {
  const value = moment.sourceFrameIndex != null
    ? `source frame ${moment.sourceFrameIndex}`
    : moment.ptsSec != null
      ? formatKeyframeTimestamp(moment.ptsSec)
      : "";
  const unavailable = moment.status === "unavailable" || moment.ptsSec == null;
  return {
    key: moment.semanticKey,
    label: MOMENT_LABELS[moment.semanticKey],
    value,
    frameId: moment.sourceFrameIndex == null ? null : String(moment.sourceFrameIndex),
    imageUrl: null,
    timestamp: moment.ptsSec,
    source: "原视频时间戳",
    status: unavailable ? "unavailable" : moment.status,
    confidence: unavailable ? null : moment.confidence,
    reason: unavailable ? moment.warnings[0] ?? "evidence unavailable" : moment.warnings[0] ?? null,
  };
}

export function keyframeOrderForAnalysis(analysis: AnalysisDetail): KeyframeKey[] {
  const profile = String(analysis.analysis_profile ?? "").trim().toLowerCase();
  if (profile === "spin") {
    return SPIN_KEYFRAME_ORDER;
  }
  if (profile === "spiral") {
    return SPIRAL_KEYFRAME_ORDER;
  }
  if (profile === "step" || profile === "step_sequence") {
    return STEP_KEYFRAME_ORDER;
  }
  return KEYFRAME_ORDER;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function cleanString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function basename(value: string) {
  return value.replace(/\\/g, "/").split("/").pop() ?? value;
}

function stripImageExtension(value: string) {
  return basename(value).replace(/\.(jpe?g|png|webp)$/i, "");
}

function directImageUrl(value: string | null) {
  return value && (/^https?:\/\//i.test(value) || value.startsWith("/api/")) ? value : null;
}

function frameRefFromUnknown(value: unknown): FrameRef {
  const record = asRecord(value);
  if (record) {
    const imageUrl =
      cleanString(record.frame_url) ??
      cleanString(record.image_url) ??
      cleanString(record.url);
    const frameId =
      cleanString(record.frame_id) ??
      cleanString(record.frame) ??
      cleanString(record.filename) ??
      (imageUrl ? stripImageExtension(imageUrl) : null);
    const timestamp =
      numberValue(record.timestamp) ??
      numberValue(record.timestamp_sec) ??
      numberValue(record.time_sec);
    const fallback = cleanString(record.value);
    return {
      value: frameId ?? (timestamp != null ? String(timestamp) : fallback ?? imageUrl ?? ""),
      frameId: frameId ? stripImageExtension(frameId) : null,
      imageUrl,
      timestamp,
    };
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    return { value: String(value), frameId: null, imageUrl: null, timestamp: value };
  }

  const text = cleanString(value);
  if (!text) {
    return { value: "", frameId: null, imageUrl: null, timestamp: null };
  }
  const imageUrl = directImageUrl(text);
  const timestamp = numberValue(text);
  const looksLikeFrameId = /^(frame|semantic|partial_semantic)_/i.test(stripImageExtension(text));
  return {
    value: text,
    frameId: imageUrl || looksLikeFrameId ? stripImageExtension(text) : null,
    imageUrl,
    timestamp: imageUrl || looksLikeFrameId ? null : timestamp,
  };
}

function phaseKeyFromRecord(record: Record<string, unknown>, fallbackIndex?: number): KeyframeKey | null {
  const rawValues = [
    cleanString(record.phase_code),
    cleanString(record.key_moment),
    cleanString(record.phase_label),
  ].filter((value): value is string => Boolean(value));

  for (const rawValue of rawValues) {
    const value = rawValue.toLowerCase();
    if (value === "t" || value.includes("takeoff") || value.includes("起跳")) {
      return "T";
    }
    if (
      value === "a" ||
      value.includes("apex") ||
      value.includes("air") ||
      value.includes("peak") ||
      value.includes("flight") ||
      value.includes("腾空") ||
      value.includes("空中") ||
      value.includes("最高")
    ) {
      return "A";
    }
    if (
      value === "l" ||
      value.includes("landing") ||
      value.includes("land") ||
      value.includes("落冰") ||
      value.includes("着陆") ||
      value.includes("落地")
    ) {
      return "L";
    }
    if (value === "spin_entry" || value.includes("entry") || value.includes("入转") || value.includes("旋转入")) {
      return "spin_entry";
    }
    if (value === "spin_main" || value.includes("main") || value.includes("主转") || value.includes("旋转中")) {
      return "spin_main";
    }
    if (value === "spin_exit" || value.includes("exit") || value.includes("出转") || value.includes("旋转出")) {
      return "spin_exit";
    }
    if (value === "spiral_hold" || value.includes("spiral") || value.includes("姿态保持") || value.includes("燕式")) {
      return "spiral_hold";
    }
    if (value === "step_sequence" || value.includes("step") || value.includes("步法")) {
      return "step_sequence";
    }
  }

  return fallbackIndex != null && fallbackIndex < KEYFRAME_ORDER.length ? KEYFRAME_ORDER[fallbackIndex] : null;
}

function phaseKeyFromRecordForAnalysis(analysis: AnalysisDetail, record: Record<string, unknown>, fallbackIndex?: number): KeyframeKey | null {
  const key = phaseKeyFromRecord(record);
  if (key) {
    return key;
  }
  const order = keyframeOrderForAnalysis(analysis);
  return fallbackIndex != null && fallbackIndex < order.length ? order[fallbackIndex] : null;
}

function normalizedFrameKey(value: string | null | undefined) {
  return value ? stripImageExtension(value).toLowerCase() : "";
}

function collectTimestampByFrame(value: unknown, output = new Map<string, number>(), depth = 0) {
  if (depth > 6 || value == null) {
    return output;
  }

  if (Array.isArray(value)) {
    value.forEach((item) => collectTimestampByFrame(item, output, depth + 1));
    return output;
  }

  const record = asRecord(value);
  if (!record) {
    return output;
  }

  const frameId =
    cleanString(record.frame_id) ??
    cleanString(record.frame) ??
    cleanString(record.filename);
  const timestamp =
    numberValue(record.timestamp) ??
    numberValue(record.timestamp_sec) ??
    numberValue(record.time_sec);
  if (frameId && timestamp != null) {
    output.set(normalizedFrameKey(frameId), timestamp);
  }

  Object.values(record).forEach((item) => collectTimestampByFrame(item, output, depth + 1));
  return output;
}

function resolveImageUrl(analysis: AnalysisDetail, ref: FrameRef) {
  if (ref.imageUrl) {
    return ref.imageUrl;
  }
  if (!ref.frameId) {
    return null;
  }
  if (/^https?:\/\//i.test(ref.frameId) || ref.frameId.startsWith("/api/")) {
    return ref.frameId;
  }

  const urls = analysis.pose_data?.frame_urls ?? {};
  const stem = stripImageExtension(ref.frameId);
  const directCandidates = [ref.frameId, `${ref.frameId}.jpg`, stem, `${stem}.jpg`];
  for (const candidate of directCandidates) {
    if (urls[candidate]) {
      return urls[candidate];
    }
  }

  const normalized = normalizedFrameKey(ref.frameId);
  const matched = Object.entries(urls).find(([key]) => normalizedFrameKey(key) === normalized);
  if (matched) {
    return matched[1];
  }

  return `/api/frames/${encodeURIComponent(analysis.id)}/${encodeURIComponent(`${stem}.jpg`)}`;
}

export function formatKeyframeTimestamp(value: number | null) {
  return value == null ? "--" : `${value.toFixed(3)}s`;
}

export function keyframeConfidenceLabel(value: number | null) {
  return value == null ? null : `${Math.round(value * 100)}%`;
}

function semanticLookup(records: SelectedSemanticFrame[]) {
  const byFrame = new Map<string, SelectedSemanticFrame & Record<string, unknown>>();
  const byKey = new Map<KeyframeKey, SelectedSemanticFrame & Record<string, unknown>>();
  records.forEach((item, index) => {
    const record = item as SelectedSemanticFrame & Record<string, unknown>;
    const ref = frameRefFromUnknown(record);
    if (ref.frameId) {
      byFrame.set(normalizedFrameKey(ref.frameId), record);
    }
    const key = phaseKeyFromRecord(record, index);
    if (key && !byKey.has(key)) {
      byKey.set(key, record);
    }
  });
  return { byFrame, byKey };
}

function buildContext(analysis: AnalysisDetail): EvidenceBuildContext {
  const selected = analysis.video_temporal_diagnostics?.selected_semantic_frames ?? [];
  const partial = analysis.video_temporal_diagnostics?.partial_semantic_frames ?? [];
  const timestampByFrame = collectTimestampByFrame({
      frame_motion_scores: analysis.frame_motion_scores,
      bio_data: analysis.bio_data,
      selected,
      partial,
    });
  Object.entries(analysis.pose_data?.frame_timestamps ?? {}).forEach(([frameId, timestamp]) => {
    if (Number.isFinite(timestamp)) {
      timestampByFrame.set(normalizedFrameKey(frameId), timestamp);
    }
  });
  return {
    timestampByFrame,
    semanticMatches: semanticLookup([...selected, ...partial]),
  };
}

function bioTimestampForKey(analysis: AnalysisDetail, key: KeyframeKey) {
  const bioData = asRecord(analysis.bio_data);
  const timestamps = asRecord(bioData?.key_frame_timestamps);
  const corrected = asRecord(bioData?.corrected_key_frames);
  const correctedItem = asRecord(corrected?.[key]);
  const candidates = asRecord(bioData?.key_frame_candidates);
  const candidateItem = asRecord(candidates?.[key]);
  return (
    numberValue(timestamps?.[key]) ??
    numberValue(correctedItem?.timestamp) ??
    numberValue(candidateItem?.timestamp) ??
    numberValue(candidateItem?.timestamp_sec)
  );
}

function itemFromRef(
  analysis: AnalysisDetail,
  key: KeyframeKey,
  ref: FrameRef,
  source: string,
  context: EvidenceBuildContext,
  extras?: {
    status?: string | null;
    confidence?: number | null;
    reason?: string | null;
    fallbackTimestamp?: number | null;
  },
): KeyframeEvidenceItem {
  const timestamp =
    ref.timestamp ??
    extras?.fallbackTimestamp ??
    (ref.frameId ? context.timestampByFrame.get(normalizedFrameKey(ref.frameId)) ?? null : null);
  return {
    key,
    label: KEYFRAME_LABELS[key],
    value: ref.value,
    frameId: ref.frameId,
    imageUrl: resolveImageUrl(analysis, ref),
    timestamp,
    source,
    status: extras?.status ?? null,
    confidence: extras?.confidence ?? null,
    reason: extras?.reason ?? null,
  };
}

function emptyItem(analysis: AnalysisDetail, key: KeyframeKey, source: string, context: EvidenceBuildContext): KeyframeEvidenceItem {
  return itemFromRef(analysis, key, { value: "", frameId: null, imageUrl: null, timestamp: null }, source, context);
}

export function buildSemanticKeyframeEvidenceItems(
  analysis: AnalysisDetail,
  records: SelectedSemanticFrame[],
  source: string,
): KeyframeEvidenceItem[] {
  const context = buildContext(analysis);
  const order = keyframeOrderForAnalysis(analysis);
  const byKey = new Map<KeyframeKey, KeyframeEvidenceItem>();
  records.forEach((item, index) => {
    const record = item as SelectedSemanticFrame & Record<string, unknown>;
    const key = phaseKeyFromRecordForAnalysis(analysis, record, index);
    if (!key || byKey.has(key)) {
      return;
    }
    byKey.set(
      key,
      itemFromRef(analysis, key, frameRefFromUnknown(record), source, context, {
        status:
          cleanString(record.selection_status) ??
          cleanString(record.refinement_method) ??
          cleanString(record.phase_label),
        confidence: numberValue(record.confidence),
        reason: cleanString(record.selection_reason),
      }),
    );
  });

  return order.map((key) => byKey.get(key) ?? emptyItem(analysis, key, source, context));
}

export function buildKeyframeEvidenceItems(
  analysis: AnalysisDetail,
  keyFramesPayload: unknown,
  source = "关键帧修正",
): KeyframeEvidenceItem[] {
  const context = buildContext(analysis);
  const rawFrames = asRecord(keyFramesPayload) ?? {};
  const order = keyframeOrderForAnalysis(analysis);

  return order.map((key) => {
    const value = rawFrames[key];
    const record = asRecord(value);
    const ref = frameRefFromUnknown(value);
    const semanticMatch = ref.frameId
      ? context.semanticMatches.byFrame.get(normalizedFrameKey(ref.frameId))
      : context.semanticMatches.byKey.get(key);
    return itemFromRef(analysis, key, ref, source, context, {
      fallbackTimestamp:
        numberValue(record?.timestamp) ??
        numberValue(record?.timestamp_sec) ??
        numberValue(record?.time_sec) ??
        numberValue(semanticMatch?.timestamp),
      status:
        cleanString(record?.selection_status) ??
        cleanString(record?.status) ??
        cleanString(record?.refinement_method) ??
        cleanString(record?.phase_label) ??
        cleanString(semanticMatch?.selection_status) ??
        cleanString(semanticMatch?.phase_label),
      confidence: numberValue(record?.confidence) ?? numberValue(semanticMatch?.confidence),
      reason:
        cleanString(record?.selection_reason) ??
        cleanString(record?.reason) ??
        cleanString(semanticMatch?.selection_reason),
    });
  });
}

export function buildCurrentKeyframeEvidenceItems(analysis: AnalysisDetail): KeyframeEvidenceItem[] {
  const context = buildContext(analysis);
  const bioData = asRecord(analysis.bio_data);
  const keyFrames = asRecord(bioData?.key_frames);
  return keyframeOrderForAnalysis(analysis).map((key) => {
    const ref = frameRefFromUnknown(keyFrames?.[key]);
    const semanticMatch = ref.frameId
      ? context.semanticMatches.byFrame.get(normalizedFrameKey(ref.frameId))
      : context.semanticMatches.byKey.get(key);
    return itemFromRef(analysis, key, ref, "当前有效", context, {
      fallbackTimestamp: bioTimestampForKey(analysis, key) ?? numberValue(semanticMatch?.timestamp),
      status:
        cleanString(semanticMatch?.selection_status) ??
        cleanString(semanticMatch?.phase_label),
      confidence: numberValue(semanticMatch?.confidence),
      reason: cleanString(semanticMatch?.selection_reason),
    });
  });
}

export function buildDraftKeyframeEvidenceItems(
  analysis: AnalysisDetail,
  draftKeyframes: Partial<Record<KeyframeKey, string>>,
): KeyframeEvidenceItem[] {
  const context = buildContext(analysis);
  return keyframeOrderForAnalysis(analysis).map((key) => {
    const ref = frameRefFromUnknown(draftKeyframes[key]);
    const semanticMatch = ref.frameId
      ? context.semanticMatches.byFrame.get(normalizedFrameKey(ref.frameId))
      : context.semanticMatches.byKey.get(key);
    return itemFromRef(analysis, key, ref, "待确认草稿", context, {
      fallbackTimestamp: numberValue(semanticMatch?.timestamp),
      status:
        cleanString(semanticMatch?.selection_status) ??
        cleanString(semanticMatch?.phase_label),
      confidence: numberValue(semanticMatch?.confidence),
      reason: cleanString(semanticMatch?.selection_reason),
    });
  });
}
