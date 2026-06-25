import { useMemo, useRef, useState } from "react";

import { AnalysisDetail, SelectedSemanticFrame } from "../api/client";

type KeyframeKey = "T" | "A" | "L";
export type KeyframeSyncPatch = Partial<Record<KeyframeKey, string>>;

type DraftKeyframes = Record<KeyframeKey, string>;
type SourceId = "current" | "selected" | "partial" | "draft";

type FrameRef = {
  value: string;
  frameId: string | null;
  timestamp: number | null;
};

type KeyframeEvidenceItem = {
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

type KeyframeEvidenceSource = {
  id: SourceId;
  label: string;
  items: KeyframeEvidenceItem[];
};

type KeyframeEvidencePanelProps = {
  analysis: AnalysisDetail;
  draftKeyframes: DraftKeyframes;
  onSyncFrames: (patch: KeyframeSyncPatch, sourceLabel: string) => void;
};

const KEYFRAME_ORDER: KeyframeKey[] = ["T", "A", "L"];
const KEYFRAME_LABELS: Record<KeyframeKey, string> = {
  T: "起跳",
  A: "腾空",
  L: "落冰",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
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

function frameRefFromUnknown(value: unknown): FrameRef {
  const record = asRecord(value);
  if (record) {
    const frameId = cleanString(record.frame_id) ?? cleanString(record.frame) ?? cleanString(record.filename);
    const timestamp = numberValue(record.timestamp) ?? numberValue(record.timestamp_sec) ?? numberValue(record.time_sec);
    const fallback = cleanString(record.value);
    return {
      value: frameId ?? (timestamp != null ? String(timestamp) : fallback ?? ""),
      frameId: frameId ? stripImageExtension(frameId) : null,
      timestamp,
    };
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    return { value: String(value), frameId: null, timestamp: value };
  }

  const text = cleanString(value);
  if (!text) {
    return { value: "", frameId: null, timestamp: null };
  }
  const timestamp = numberValue(text);
  const looksLikeFrameId = /^(frame|semantic|partial_semantic)_/i.test(stripImageExtension(text));
  return {
    value: text,
    frameId: looksLikeFrameId ? stripImageExtension(text) : null,
    timestamp: looksLikeFrameId ? null : timestamp,
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
    if (value === "l" || value.includes("landing") || value.includes("land") || value.includes("落冰") || value.includes("着陆") || value.includes("落地")) {
      return "L";
    }
  }

  return fallbackIndex != null && fallbackIndex < KEYFRAME_ORDER.length ? KEYFRAME_ORDER[fallbackIndex] : null;
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

  const frameId = cleanString(record.frame_id) ?? cleanString(record.frame) ?? cleanString(record.filename);
  const timestamp = numberValue(record.timestamp) ?? numberValue(record.timestamp_sec) ?? numberValue(record.time_sec);
  if (frameId && timestamp != null) {
    output.set(normalizedFrameKey(frameId), timestamp);
  }

  Object.values(record).forEach((item) => collectTimestampByFrame(item, output, depth + 1));
  return output;
}

function resolveImageUrl(analysis: AnalysisDetail, frameId: string | null) {
  if (!frameId) {
    return null;
  }
  if (/^https?:\/\//i.test(frameId) || frameId.startsWith("/api/")) {
    return frameId;
  }

  const urls = analysis.pose_data?.frame_urls ?? {};
  const stem = stripImageExtension(frameId);
  const directCandidates = [frameId, `${frameId}.jpg`, stem, `${stem}.jpg`];
  for (const candidate of directCandidates) {
    if (urls[candidate]) {
      return urls[candidate];
    }
  }

  const normalized = normalizedFrameKey(frameId);
  const matched = Object.entries(urls).find(([key]) => normalizedFrameKey(key) === normalized);
  if (matched) {
    return matched[1];
  }

  return `/api/frames/${encodeURIComponent(analysis.id)}/${encodeURIComponent(`${stem}.jpg`)}`;
}

function formatTimestamp(value: number | null) {
  return value == null ? "--" : `${value.toFixed(3).replace(/0+$/u, "").replace(/\.$/u, "")}s`;
}

function confidenceLabel(value: number | null) {
  return value == null ? null : `${Math.round(value * 100)}%`;
}

function itemFromRef(
  analysis: AnalysisDetail,
  key: KeyframeKey,
  ref: FrameRef,
  source: string,
  timestampByFrame: Map<string, number>,
  extras?: {
    status?: string | null;
    confidence?: number | null;
    reason?: string | null;
    fallbackTimestamp?: number | null;
  },
): KeyframeEvidenceItem {
  const timestamp = ref.timestamp ?? extras?.fallbackTimestamp ?? (ref.frameId ? timestampByFrame.get(normalizedFrameKey(ref.frameId)) ?? null : null);
  return {
    key,
    label: KEYFRAME_LABELS[key],
    value: ref.value,
    frameId: ref.frameId,
    imageUrl: resolveImageUrl(analysis, ref.frameId),
    timestamp,
    source,
    status: extras?.status ?? null,
    confidence: extras?.confidence ?? null,
    reason: extras?.reason ?? null,
  };
}

function emptyItem(analysis: AnalysisDetail, key: KeyframeKey, source: string): KeyframeEvidenceItem {
  return itemFromRef(analysis, key, { value: "", frameId: null, timestamp: null }, source, new Map());
}

function semanticItems(
  analysis: AnalysisDetail,
  records: SelectedSemanticFrame[],
  source: string,
  timestampByFrame: Map<string, number>,
) {
  const byKey = new Map<KeyframeKey, KeyframeEvidenceItem>();
  records.forEach((item, index) => {
    const record = item as SelectedSemanticFrame & Record<string, unknown>;
    const key = phaseKeyFromRecord(record, index);
    if (!key || byKey.has(key)) {
      return;
    }
    const ref = frameRefFromUnknown(record);
    const status = cleanString(record.selection_status) ?? cleanString(record.refinement_method) ?? cleanString(record.phase_label);
    byKey.set(
      key,
      itemFromRef(analysis, key, ref, source, timestampByFrame, {
        status,
        confidence: numberValue(record.confidence),
        reason: cleanString(record.selection_reason),
      }),
    );
  });

  return KEYFRAME_ORDER.map((key) => byKey.get(key) ?? emptyItem(analysis, key, source));
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

function bioTimestampForKey(analysis: AnalysisDetail, key: KeyframeKey) {
  const bioData = asRecord(analysis.bio_data);
  const timestamps = asRecord(bioData?.key_frame_timestamps);
  const corrected = asRecord(bioData?.corrected_key_frames);
  const correctedItem = asRecord(corrected?.[key]);
  return numberValue(timestamps?.[key]) ?? numberValue(correctedItem?.timestamp);
}

function currentItems(
  analysis: AnalysisDetail,
  timestampByFrame: Map<string, number>,
  semanticMatches: ReturnType<typeof semanticLookup>,
) {
  const bioData = asRecord(analysis.bio_data);
  const keyFrames = asRecord(bioData?.key_frames);
  return KEYFRAME_ORDER.map((key) => {
    const ref = frameRefFromUnknown(keyFrames?.[key]);
    const semanticMatch = ref.frameId ? semanticMatches.byFrame.get(normalizedFrameKey(ref.frameId)) : semanticMatches.byKey.get(key);
    return itemFromRef(analysis, key, ref, "当前有效", timestampByFrame, {
      fallbackTimestamp: bioTimestampForKey(analysis, key) ?? numberValue(semanticMatch?.timestamp),
      status: cleanString(semanticMatch?.selection_status) ?? cleanString(semanticMatch?.phase_label),
      confidence: numberValue(semanticMatch?.confidence),
      reason: cleanString(semanticMatch?.selection_reason),
    });
  });
}

function draftItems(
  analysis: AnalysisDetail,
  draftKeyframes: DraftKeyframes,
  timestampByFrame: Map<string, number>,
  semanticMatches: ReturnType<typeof semanticLookup>,
) {
  return KEYFRAME_ORDER.map((key) => {
    const ref = frameRefFromUnknown(draftKeyframes[key]);
    const semanticMatch = ref.frameId ? semanticMatches.byFrame.get(normalizedFrameKey(ref.frameId)) : semanticMatches.byKey.get(key);
    return itemFromRef(analysis, key, ref, "待确认草稿", timestampByFrame, {
      fallbackTimestamp: numberValue(semanticMatch?.timestamp),
      status: cleanString(semanticMatch?.selection_status) ?? cleanString(semanticMatch?.phase_label),
      confidence: numberValue(semanticMatch?.confidence),
      reason: cleanString(semanticMatch?.selection_reason),
    });
  });
}

export default function KeyframeEvidencePanel({ analysis, draftKeyframes, onSyncFrames }: KeyframeEvidencePanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [activeSourceId, setActiveSourceId] = useState<SourceId>("current");
  const [imageErrors, setImageErrors] = useState<Record<string, boolean>>({});
  const [videoError, setVideoError] = useState(false);

  const sources = useMemo<KeyframeEvidenceSource[]>(() => {
    const selected = analysis.video_temporal_diagnostics?.selected_semantic_frames ?? [];
    const partial = analysis.video_temporal_diagnostics?.partial_semantic_frames ?? [];
    const timestampByFrame = collectTimestampByFrame({
      frame_motion_scores: analysis.frame_motion_scores,
      pose_data: analysis.pose_data,
      bio_data: analysis.bio_data,
      selected,
      partial,
    });
    const matches = semanticLookup([...selected, ...partial]);
    return [
      { id: "current", label: "当前有效", items: currentItems(analysis, timestampByFrame, matches) },
      { id: "selected", label: "AI 语义候选", items: semanticItems(analysis, selected, "AI 语义候选", timestampByFrame) },
      { id: "partial", label: "Partial 候选", items: semanticItems(analysis, partial, "Partial 候选", timestampByFrame) },
      { id: "draft", label: "待确认草稿", items: draftItems(analysis, draftKeyframes, timestampByFrame, matches) },
    ];
  }, [analysis, draftKeyframes]);

  const activeSource = sources.find((source) => source.id === activeSourceId) ?? sources[0];
  const availableCount = activeSource.items.filter((item) => item.value).length;
  const videoSrc = `/api/analysis/${encodeURIComponent(analysis.id)}/video`;

  const seekTo = (timestamp: number | null) => {
    if (timestamp == null || !videoRef.current) {
      return;
    }
    videoRef.current.currentTime = Math.max(0, timestamp);
  };

  const syncItem = (item: KeyframeEvidenceItem) => {
    if (!item.value) {
      return;
    }
    seekTo(item.timestamp);
    onSyncFrames({ [item.key]: item.value }, `${activeSource.label} ${item.key}`);
  };

  const syncAll = () => {
    const patch = activeSource.items.reduce<KeyframeSyncPatch>((current, item) => {
      if (item.value) {
        current[item.key] = item.value;
      }
      return current;
    }, {});
    if (Object.keys(patch).length) {
      onSyncFrames(patch, activeSource.label);
    }
  };

  return (
    <section className="rounded-[24px] border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-3 phone:flex-row phone:items-start phone:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">关键帧核对台</h3>
          <p className="mt-1 text-xs text-slate-500">{activeSource.label} · {availableCount}/3</p>
        </div>
        <button
          type="button"
          onClick={syncAll}
          disabled={!availableCount}
          className="min-h-[36px] rounded-full border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          同步三帧到 form
        </button>
      </div>

      <div className="mt-4 overflow-hidden rounded-[18px] bg-slate-950">
        {videoError ? (
          <div className="flex aspect-video items-center justify-center px-4 text-center text-xs leading-6 text-slate-300">
            视频暂不可用
          </div>
        ) : (
          <video
            ref={videoRef}
            src={videoSrc}
            controls
            preload="metadata"
            playsInline
            onError={() => setVideoError(true)}
            className="aspect-video w-full bg-slate-950 object-contain"
          />
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 tablet:grid-cols-4 xl:grid-cols-2 wide:grid-cols-4">
        {sources.map((source) => {
          const selected = source.id === activeSource.id;
          return (
            <button
              key={source.id}
              type="button"
              onClick={() => setActiveSourceId(source.id)}
              className={`min-h-[38px] rounded-full border px-3 py-1 text-xs font-semibold transition ${
                selected ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-white"
              }`}
            >
              {source.label}
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex snap-x gap-3 overflow-x-auto pb-1 tablet:grid tablet:grid-cols-3 tablet:overflow-visible xl:grid-cols-1 wide:grid-cols-3">
        {activeSource.items.map((item) => {
          const imageKey = `${activeSource.id}-${item.key}-${item.frameId ?? item.value}`;
          const imageUnavailable = !item.imageUrl || imageErrors[imageKey];
          const confidence = confidenceLabel(item.confidence);
          return (
            <article key={item.key} className="min-w-[190px] snap-start rounded-[20px] border border-slate-200 bg-slate-50 p-3">
              <button
                type="button"
                onClick={() => syncItem(item)}
                disabled={!item.value}
                className="group block w-full overflow-hidden rounded-[16px] bg-slate-950 text-left disabled:cursor-not-allowed"
              >
                <div className="relative aspect-video">
                  {!imageUnavailable ? (
                    <img
                      src={item.imageUrl ?? ""}
                      alt={`${item.key} ${item.value}`}
                      loading="lazy"
                      onError={() => setImageErrors((current) => ({ ...current, [imageKey]: true }))}
                      className="h-full w-full object-contain"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center px-3 text-center text-xs leading-5 text-slate-400">
                      {item.value || "暂无帧图"}
                    </div>
                  )}
                  <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-1 text-xs font-bold text-slate-900 shadow-sm">
                    {item.key}
                  </span>
                  {item.timestamp != null ? (
                    <span className="absolute bottom-2 right-2 rounded-full bg-slate-950/78 px-2 py-1 text-[11px] font-semibold text-white">
                      {formatTimestamp(item.timestamp)}
                    </span>
                  ) : null}
                </div>
              </button>

              <div className="mt-3 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                    <p className="mt-1 truncate text-xs font-medium text-slate-500">{item.value || "--"}</p>
                  </div>
                  {confidence ? <span className="shrink-0 rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-slate-500">{confidence}</span> : null}
                </div>
                <div className="mt-2 flex flex-wrap gap-1 text-[11px] text-slate-500">
                  <span className="rounded-full bg-white px-2 py-1">{formatTimestamp(item.timestamp)}</span>
                  {item.status ? <span className="rounded-full bg-white px-2 py-1">{item.status}</span> : null}
                </div>
                {item.reason ? <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-slate-500">{item.reason}</p> : null}
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => syncItem(item)}
                    disabled={!item.value}
                    className="min-h-[34px] flex-1 rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:bg-teal-50 hover:text-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    同步 {item.key}
                  </button>
                  <button
                    type="button"
                    onClick={() => seekTo(item.timestamp)}
                    disabled={item.timestamp == null || videoError}
                    className="min-h-[34px] rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    定位
                  </button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
