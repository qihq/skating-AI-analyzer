import axios from "axios";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  AnalysisChatMessage,
  AnalysisChatShareResponse,
  AnalysisCorrection,
  AnalysisDetail,
  ProviderPublic,
  applyAnalysisCorrection,
  createAnalysisCorrection,
  dismissAnalysisCorrection,
  fetchAnalysisChatMessages,
  fetchAnalysisCorrections,
  fetchProviders,
  regenerateReportFromCorrections,
  rerunVideoAIKeyframes,
  retryAnalysis,
  sendAnalysisChatMessage,
  shareAnalysisChat,
} from "../api/client";
import KeyframeEvidencePanel, { type KeyframeSyncPatch } from "./KeyframeEvidencePanel";
import {
  canvasToCompressedBlob,
  copyImageBlobToClipboard,
  createShareImagePreview,
  createShareImageResult,
  drawRoundRect,
  drawWrappedText,
  measureWrappedText,
  normalizeShareText,
  shareImageFile,
  ShareImagePreview,
} from "../utils/shareCanvas";
import RetryAnalysisConfirmSheet from "./RetryAnalysisConfirmSheet";

const QUICK_PROMPTS = [
  "我的 comments 有没有被考虑？",
  "这个动作为什么这样识别？",
  "partial semantic candidates 和最终关键帧差在哪？",
  "给我 10 分钟训练建议",
];

type ManualFormState = {
  actionType: string;
  actionSubtype: string;
  takeoffFrame: string;
  apexFrame: string;
  landingFrame: string;
  rationale: string;
};

type SuggestedFormState = ManualFormState & {
  sourceCorrectionId: string;
};

type ToolTab = "keyframes" | "form" | "corrections";

type AnalysisFollowUpPanelProps = {
  analysis: AnalysisDetail | null;
  compact?: boolean;
  variant?: "card" | "workspace";
  onAnalysisRefresh?: () => void;
  onAnalysisRetryQueued?: () => void;
  onNotice?: (message: string) => void;
};

function createDefaultManualForm(analysis: AnalysisDetail | null): ManualFormState {
  return {
    actionType: analysis?.action_type ?? "",
    actionSubtype: analysis?.action_subtype ?? "",
    takeoffFrame: "",
    apexFrame: "",
    landingFrame: "",
    rationale: "",
  };
}

function correctionTitle(correction: AnalysisCorrection) {
  if (correction.kind === "action_label") {
    return "动作识别修正";
  }
  if (correction.kind === "keyframes") {
    return "关键帧修正";
  }
  if (correction.kind === "report_regeneration") {
    return "报告已按修正重新生成";
  }
  if (correction.kind === "report_note") {
    return "报告说明修正";
  }
  return "分析修正";
}

function correctionSummary(correction: AnalysisCorrection) {
  const payload = correction.payload;
  if (correction.kind === "action_label") {
    const confirmation = payload.action_confirmation && typeof payload.action_confirmation === "object" ? payload.action_confirmation as Record<string, unknown> : {};
    return String(payload.action_subtype ?? payload.action_type ?? confirmation.confirmed_action ?? confirmation.jump_type ?? correction.rationale ?? "建议调整动作识别");
  }
  if (correction.kind === "keyframes") {
    const frames = payload.key_frames && typeof payload.key_frames === "object" ? payload.key_frames as Record<string, unknown> : {};
    const text = Object.entries(frames)
      .map(([key, value]) => `${key}: ${typeof value === "object" && value ? String((value as Record<string, unknown>).frame_id ?? (value as Record<string, unknown>).timestamp ?? "") : String(value)}`)
      .filter(Boolean)
      .join(" · ");
    return text || String(correction.rationale ?? "建议调整 T/A/L 关键帧");
  }
  if (correction.kind === "report_regeneration") {
    return "已生成新的有效报告，原始报告仍保留在修正快照里。";
  }
  return String(correction.rationale ?? "待确认修正");
}

function statusLabel(status: string) {
  if (status === "applied") {
    return "已应用";
  }
  if (status === "dismissed") {
    return "已忽略";
  }
  return "待确认";
}

function statusClass(status: string) {
  if (status === "applied") {
    return "bg-emerald-50 text-emerald-600";
  }
  if (status === "dismissed") {
    return "bg-slate-100 text-slate-500";
  }
  return "bg-amber-50 text-amber-600";
}

function currentKeyFrames(analysis: AnalysisDetail | null) {
  const keyFrames = analysis?.bio_data?.key_frames;
  if (!keyFrames) {
    return [];
  }
  return Object.entries(keyFrames).filter(([, value]) => value);
}

function frameValue(value: unknown) {
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(record.frame_id ?? record.frame ?? record.timestamp ?? "");
  }
  return value == null ? "" : String(value);
}

function extractSuggestionForm(correction: AnalysisCorrection, analysis: AnalysisDetail | null): SuggestedFormState | null {
  if (correction.status !== "proposed" || correction.source !== "chat_suggestion") {
    return null;
  }
  const payload = correction.payload;
  const base = createDefaultManualForm(analysis);
  if (correction.kind === "action_label") {
    const confirmation = payload.action_confirmation && typeof payload.action_confirmation === "object" ? payload.action_confirmation as Record<string, unknown> : {};
    const actionSubtype = String(payload.action_subtype ?? confirmation.confirmed_action ?? confirmation.jump_type ?? base.actionSubtype ?? "");
    const actionType = String(payload.action_type ?? base.actionType ?? "");
    if (!actionType && !actionSubtype) {
      return null;
    }
    return {
      ...base,
      actionType,
      actionSubtype,
      rationale: correction.rationale ?? "",
      sourceCorrectionId: correction.id,
    };
  }
  if (correction.kind === "keyframes") {
    const keyFrames = payload.key_frames && typeof payload.key_frames === "object" ? payload.key_frames as Record<string, unknown> : {};
    const takeoffFrame = frameValue(keyFrames.T);
    const apexFrame = frameValue(keyFrames.A);
    const landingFrame = frameValue(keyFrames.L);
    if (!takeoffFrame && !apexFrame && !landingFrame) {
      return null;
    }
    return {
      ...base,
      takeoffFrame,
      apexFrame,
      landingFrame,
      rationale: correction.rationale ?? "",
      sourceCorrectionId: correction.id,
    };
  }
  return null;
}

function mergeSuggestionForm(current: ManualFormState, suggestion: SuggestedFormState): ManualFormState {
  return {
    actionType: suggestion.actionType || current.actionType,
    actionSubtype: suggestion.actionSubtype || current.actionSubtype,
    takeoffFrame: suggestion.takeoffFrame || current.takeoffFrame,
    apexFrame: suggestion.apexFrame || current.apexFrame,
    landingFrame: suggestion.landingFrame || current.landingFrame,
    rationale: suggestion.rationale || current.rationale,
  };
}

function buildSuggestedForm(corrections: AnalysisCorrection[], analysis: AnalysisDetail | null): SuggestedFormState | null {
  const suggestions = corrections
    .map((correction) => extractSuggestionForm(correction, analysis))
    .filter((suggestion): suggestion is SuggestedFormState => Boolean(suggestion));
  if (!suggestions.length) {
    return null;
  }
  const merged = suggestions.reduce<ManualFormState>(
    (current, suggestion) => mergeSuggestionForm(current, suggestion),
    createDefaultManualForm(analysis),
  );
  return {
    ...merged,
    sourceCorrectionId: suggestions[suggestions.length - 1].sourceCorrectionId,
  };
}

async function createChatShareImage(share: AnalysisChatShareResponse) {
  const canvas = document.createElement("canvas");
  const width = 1080;
  const scale = 1;
  const measureCanvas = document.createElement("canvas");
  const measureCtx = measureCanvas.getContext("2d");
  if (!measureCtx) {
    throw new Error("share_image_canvas_failed");
  }

  const payload = share.image_payload ?? {};
  const title = normalizeShareText(String(payload.title ?? share.title ?? ""), "AI追问复盘");
  const summary = normalizeShareText(String(payload.summary ?? ""), "围绕已完成分析继续追问，并记录人工确认修正。");
  const question = normalizeShareText(String(payload.question ?? ""), "本次追问");
  const answer = normalizeShareText(String(payload.answer ?? ""), "AI 基于已保存证据给出复盘回答。");
  const applied = Array.isArray(payload.applied_corrections) ? payload.applied_corrections.map((item) => String(item)) : [];
  const pending = Array.isArray(payload.pending_corrections) ? payload.pending_corrections.map((item) => String(item)) : [];
  const correctionText = [...applied.map((item) => `已应用：${item}`), ...pending.map((item) => `待确认：${item}`)].join("  ");

  const contentWidth = 856;
  const textWidth = 760;
  measureCtx.font = "800 56px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const titleHeight = measureWrappedText(measureCtx, title, 760, 64);
  measureCtx.font = "500 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const summaryHeight = measureWrappedText(measureCtx, summary, contentWidth, 44);
  measureCtx.font = "650 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const questionHeight = measureWrappedText(measureCtx, question, textWidth, 42);
  const answerHeight = measureWrappedText(measureCtx, answer, textWidth, 42);
  measureCtx.font = "600 27px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const correctionHeight = measureWrappedText(measureCtx, correctionText || "暂无已应用修正。", textWidth, 36);
  const questionBlockHeight = Math.max(154, 96 + questionHeight + 38);
  const answerBlockHeight = Math.max(184, 96 + answerHeight + 38);
  const correctionBlockHeight = Math.max(118, 82 + correctionHeight + 30);
  const height = Math.min(
    6000,
    Math.max(980, 112 + 42 + 54 + titleHeight + 42 + summaryHeight + 74 + questionBlockHeight + 32 + answerBlockHeight + 32 + correctionBlockHeight + 126),
  );

  canvas.width = width * scale;
  canvas.height = height * scale;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("share_image_canvas_failed");
  }
  ctx.scale(scale, scale);

  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#F8FBFF");
  gradient.addColorStop(0.52, "#F0FDF4");
  gradient.addColorStop(1, "#FFF7ED");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "rgba(255,255,255,0.9)";
  drawRoundRect(ctx, 64, 64, width - 128, height - 128, 44);
  ctx.fill();
  ctx.strokeStyle = "rgba(148,163,184,0.32)";
  ctx.lineWidth = 2;
  ctx.stroke();

  let y = 142;
  ctx.fillStyle = "#0F766E";
  ctx.font = "800 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("IceBuddy AI 追问", 112, y);

  y += 84;
  ctx.fillStyle = "#0F172A";
  ctx.font = "800 56px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  y += drawWrappedText(ctx, title, 112, y, 760, 64) + 42;

  ctx.fillStyle = "#475569";
  ctx.font = "500 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  y += drawWrappedText(ctx, summary, 112, y, contentWidth, 44) + 54;

  const blocks = [
    { label: "追问", text: question, bg: "#EFF6FF", color: "#2563EB", height: questionBlockHeight },
    { label: "回答", text: answer, bg: "#ECFDF5", color: "#059669", height: answerBlockHeight },
  ];
  blocks.forEach((block) => {
    ctx.fillStyle = block.bg;
    drawRoundRect(ctx, 112, y, contentWidth, block.height, 28);
    ctx.fill();
    ctx.fillStyle = block.color;
    ctx.font = "800 25px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.fillText(block.label, 152, y + 50);
    ctx.fillStyle = "#0F172A";
    ctx.font = "650 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    drawWrappedText(ctx, block.text, 152, y + 100, textWidth, 42);
    y += block.height + 32;
  });

  ctx.fillStyle = "#FFF7ED";
  drawRoundRect(ctx, 112, y, contentWidth, correctionBlockHeight, 28);
  ctx.fill();
  ctx.fillStyle = "#EA580C";
  ctx.font = "800 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("修正记录", 152, y + 50);
  ctx.fillStyle = "#334155";
  ctx.font = "600 27px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, correctionText || "暂无已应用修正。", 152, y + 92, textWidth, 36);
  y += correctionBlockHeight + 64;

  ctx.fillStyle = "#94A3B8";
  ctx.font = "500 22px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("修正需人工确认后才会进入系统有效数据", 112, Math.min(y, height - 92));

  const blob = await canvasToCompressedBlob(canvas, { type: "image/jpeg", quality: 0.82, maxBytes: 1_500_000 });
  const filename = `icebuddy-chat-${String(payload.analysis_id ?? "share").slice(0, 8)}.jpg`;
  return createShareImageResult(blob, filename);
}

export default function AnalysisFollowUpPanel({ analysis, compact = false, variant = "card", onAnalysisRefresh, onAnalysisRetryQueued, onNotice }: AnalysisFollowUpPanelProps) {
  const [messages, setMessages] = useState<AnalysisChatMessage[]>([]);
  const [corrections, setCorrections] = useState<AnalysisCorrection[]>([]);
  const [providers, setProviders] = useState<ProviderPublic[]>([]);
  const [selectedProviderId, setSelectedProviderId] = useState("");
  const [input, setInput] = useState("");
  const [manualForm, setManualForm] = useState<ManualFormState>(() => createDefaultManualForm(analysis));
  const [manualFormDirty, setManualFormDirty] = useState(false);
  const [pendingSuggestion, setPendingSuggestion] = useState<SuggestedFormState | null>(null);
  const [syncedSuggestionId, setSyncedSuggestionId] = useState<string | null>(null);
  const [activeToolTab, setActiveToolTab] = useState<ToolTab>("keyframes");
  const [quickPromptsOpen, setQuickPromptsOpen] = useState(() => (typeof window !== "undefined" ? window.matchMedia("(min-width: 768px)").matches : true));
  const [error, setError] = useState<string | null>(null);
  const [shareText, setShareText] = useState("");
  const [sharePreview, setSharePreview] = useState<ShareImagePreview | null>(null);
  const [isSharePreviewOpen, setIsSharePreviewOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isRetryConfirmOpen, setIsRetryConfirmOpen] = useState(false);
  const [isRetryingAnalysis, setIsRetryingAnalysis] = useState(false);
  const [isVideoKeyframeConfirmOpen, setIsVideoKeyframeConfirmOpen] = useState(false);
  const [isRerunningVideoKeyframes, setIsRerunningVideoKeyframes] = useState(false);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  const analysisId = analysis?.id ?? "";
  const reportProviders = useMemo(() => providers.filter((provider) => provider.slot === "report"), [providers]);
  const activeCorrections = corrections.filter((correction) => correction.status !== "dismissed");
  const pendingCorrections = corrections.filter((correction) => correction.status === "proposed");
  const appliedCorrections = corrections.filter((correction) => correction.status === "applied");
  const draftKeyframes = useMemo(
    () => ({
      T: manualForm.takeoffFrame,
      A: manualForm.apexFrame,
      L: manualForm.landingFrame,
    }),
    [manualForm.apexFrame, manualForm.landingFrame, manualForm.takeoffFrame],
  );

  useEffect(() => {
    setManualForm(createDefaultManualForm(analysis));
    setManualFormDirty(false);
    setPendingSuggestion(null);
    setSyncedSuggestionId(null);
    setActiveToolTab("keyframes");
  }, [analysis?.id, analysis?.action_type, analysis?.action_subtype]);

  useEffect(() => {
    let cancelled = false;
    const loadProviders = async () => {
      try {
        const data = await fetchProviders();
        if (!cancelled) {
          setProviders(data);
        }
      } catch {
        if (!cancelled) {
          setProviders([]);
        }
      }
    };
    void loadProviders();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedProviderId || reportProviders.some((provider) => provider.id === selectedProviderId)) {
      return;
    }
    setSelectedProviderId("");
  }, [reportProviders, selectedProviderId]);

  useEffect(() => {
    return () => {
      if (sharePreview?.url) {
        URL.revokeObjectURL(sharePreview.url);
      }
    };
  }, [sharePreview?.url]);

  const reload = async () => {
    if (!analysisId || analysis?.status !== "completed") {
      setMessages([]);
      setCorrections([]);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const [messageData, correctionData] = await Promise.all([
        fetchAnalysisChatMessages(analysisId),
        fetchAnalysisCorrections(analysisId),
      ]);
      setMessages(messageData);
      setCorrections(correctionData.corrections);
    } catch {
      setError("追问记录或修正记录加载失败，请稍后刷新。");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void reload();
  }, [analysisId, analysis?.status]);

  useEffect(() => {
    const element = messageListRef.current;
    if (!element) {
      return;
    }
    element.scrollTop = element.scrollHeight;
  }, [analysisId, messages.length, isSending]);

  const showNotice = (message: string) => {
    onNotice?.(message);
  };

  const updateManualForm = (patch: Partial<ManualFormState>) => {
    setManualForm((current) => ({ ...current, ...patch }));
    setManualFormDirty(true);
  };

  const syncKeyframesToForm = (patch: KeyframeSyncPatch, sourceLabel: string) => {
    const nextPatch: Partial<ManualFormState> = {};
    if (patch.T) {
      nextPatch.takeoffFrame = patch.T;
    }
    if (patch.A) {
      nextPatch.apexFrame = patch.A;
    }
    if (patch.L) {
      nextPatch.landingFrame = patch.L;
    }
    if (!Object.keys(nextPatch).length) {
      return;
    }
    setManualForm((current) => ({ ...current, ...nextPatch }));
    setManualFormDirty(true);
    setActiveToolTab("form");
    showNotice(`${sourceLabel} 已同步到待确认 form`);
  };

  const applySuggestionToForm = (suggestion: SuggestedFormState) => {
    setManualForm((current) => mergeSuggestionForm(current, suggestion));
    setManualFormDirty(true);
    setPendingSuggestion(null);
    setSyncedSuggestionId(suggestion.sourceCorrectionId);
    setActiveToolTab("form");
  };

  useEffect(() => {
    const latestSuggestion = buildSuggestedForm(corrections, analysis);
    if (!latestSuggestion || latestSuggestion.sourceCorrectionId === syncedSuggestionId) {
      return;
    }

    if (manualFormDirty) {
      setPendingSuggestion(latestSuggestion);
      setActiveToolTab("form");
      return;
    }

    setManualForm((current) => mergeSuggestionForm(current, latestSuggestion));
    setManualFormDirty(false);
    setSyncedSuggestionId(latestSuggestion.sourceCorrectionId);
    setActiveToolTab("form");
  }, [analysis, corrections, manualFormDirty, syncedSuggestionId]);

  const submitMessage = async (rawMessage: string) => {
    const message = rawMessage.trim();
    if (!analysisId || !message || isSending) {
      return;
    }

    const optimisticId = `pending-${Date.now()}`;
    setMessages((current) => [
      ...current,
      {
        id: optimisticId,
        analysis_id: analysisId,
        role: "user",
        content: message,
        created_at: new Date().toISOString(),
      },
    ]);
    setError(null);
    setIsSending(true);
    try {
      const response = await sendAnalysisChatMessage(analysisId, message, selectedProviderId || null);
      setMessages(response.messages);
      setInput("");
      if (response.suggested_action?.kind === "full_video_reanalysis") {
        setIsRetryConfirmOpen(true);
      } else if (response.suggested_action?.kind === "video_ai_keyframe_rerun") {
        setIsVideoKeyframeConfirmOpen(true);
      }
      const correctionData = await fetchAnalysisCorrections(analysisId);
      setCorrections(correctionData.corrections);
    } catch (requestError) {
      setMessages((current) => current.filter((item) => item.id !== optimisticId));
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "AI 追问暂时没有顺利回复，请稍后再试。"));
      } else {
        setError("AI 追问暂时没有顺利回复，请稍后再试。");
      }
    } finally {
      setIsSending(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitMessage(input);
  };

  const handleConfirmFullReanalysis = async () => {
    if (!analysisId || isRetryingAnalysis) {
      return;
    }
    setIsRetryingAnalysis(true);
    setError(null);
    try {
      await retryAnalysis(analysisId, { resetTargetLock: true });
      setIsRetryConfirmOpen(false);
      showNotice("已提交完整重新分析，将重新定位主人物并重新识别关键帧。");
      onAnalysisRetryQueued?.();
      onAnalysisRefresh?.();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        if (requestError.response?.status === 404) {
          setError("原始视频已清理或不可用，请重新上传后再分析。");
          return;
        }
        setError(String(requestError.response?.data?.detail ?? "完整重新分析提交失败，请稍后重试。"));
      } else {
        setError("完整重新分析提交失败，请稍后重试。");
      }
    } finally {
      setIsRetryingAnalysis(false);
    }
  };

  const handleConfirmVideoAIKeyframeRerun = async () => {
    if (!analysisId || isRerunningVideoKeyframes) {
      return;
    }
    setIsRerunningVideoKeyframes(true);
    setError(null);
    try {
      const response = await rerunVideoAIKeyframes(analysisId);
      setCorrections(response.corrections);
      setIsVideoKeyframeConfirmOpen(false);
      setActiveToolTab("corrections");
      showNotice("已生成关键帧修正卡，确认后才会生效。");
      onAnalysisRefresh?.();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        const detail = String(requestError.response?.data?.detail ?? "");
        if (requestError.response?.status === 404) {
          setError(detail || "未找到视频 AI 重识别关键帧接口，请确认前端代理正在连接最新后端。");
          return;
        }
        setError(detail || "视频 AI 重新识别关键帧失败，请稍后重试。");
      } else {
        setError("视频 AI 重新识别关键帧失败，请稍后重试。");
      }
    } finally {
      setIsRerunningVideoKeyframes(false);
    }
  };

  const mutateCorrection = async (action: () => Promise<{ corrections: AnalysisCorrection[] }>, successMessage: string) => {
    if (!analysisId || isMutating) {
      return;
    }
    setIsMutating(true);
    setError(null);
    try {
      const response = await action();
      setCorrections(response.corrections);
      setManualFormDirty(false);
      setPendingSuggestion(null);
      showNotice(successMessage);
      onAnalysisRefresh?.();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "修正操作失败，请稍后再试。"));
      } else {
        setError("修正操作失败，请稍后再试。");
      }
    } finally {
      setIsMutating(false);
    }
  };

  const submitManualCorrection = async (kind: "action_label" | "keyframes") => {
    if (!analysisId) {
      return;
    }
    const rationale = manualForm.rationale || "手动确认修正";
    if (kind === "action_label") {
      const actionType = manualForm.actionType.trim();
      const actionSubtype = manualForm.actionSubtype.trim();
      if (!actionType && !actionSubtype) {
        setError("请先填写要修正的动作类型或动作名称。");
        return;
      }
      await mutateCorrection(
        () =>
          createAnalysisCorrection(analysisId, {
            kind: "action_label",
            source: "manual",
            status: "proposed",
            rationale,
            payload: {
              ...(actionType ? { action_type: actionType } : {}),
              ...(actionSubtype ? { action_subtype: actionSubtype } : {}),
              action_confirmation: {
                ...(actionSubtype ? { confirmed_action: actionSubtype } : {}),
                notes: rationale,
              },
            },
          }),
        "已生成动作修正卡，确认后才会生效。",
      );
      return;
    }

    const keyFrames: Record<string, string> = {};
    if (manualForm.takeoffFrame.trim()) {
      keyFrames.T = manualForm.takeoffFrame.trim();
    }
    if (manualForm.apexFrame.trim()) {
      keyFrames.A = manualForm.apexFrame.trim();
    }
    if (manualForm.landingFrame.trim()) {
      keyFrames.L = manualForm.landingFrame.trim();
    }
    if (!Object.keys(keyFrames).length) {
      setError("请至少填写一个 T/A/L 关键帧。");
      return;
    }
    await mutateCorrection(
      () =>
        createAnalysisCorrection(analysisId, {
          kind: "keyframes",
          source: "manual",
          status: "proposed",
          rationale,
          payload: {
            key_frames: keyFrames,
            source: "manual_ui",
          },
        }),
      "已生成关键帧修正卡，确认后才会生效。",
    );
  };

  const handleShare = async () => {
    if (!analysisId || isSharing) {
      return;
    }
    setIsSharing(true);
    setError(null);
    try {
      const share = await shareAnalysisChat(analysisId, { include_pending_corrections: true });
      setShareText(share.text);
      await navigator.clipboard?.writeText(share.text);
      const result = await createChatShareImage(share);
      const copiedToClipboard = await copyImageBlobToClipboard(result.blob);
      setSharePreview((current) => {
        if (current?.url) {
          URL.revokeObjectURL(current.url);
        }
        return createShareImagePreview(result, copiedToClipboard);
      });
      showNotice(copiedToClipboard ? "追问分享文字和图片已生成" : "追问分享文字已复制，图片可下载或系统分享");
    } catch {
      setError("追问分享内容生成失败，请稍后再试。");
    } finally {
      setIsSharing(false);
    }
  };

  const handleCopyShareImage = async () => {
    if (!sharePreview) {
      return;
    }
    const copied = await copyImageBlobToClipboard(sharePreview.blob);
    if (!copied) {
      setError("当前浏览器不能直接复制图片，请使用系统分享或下载。");
      return;
    }
    setSharePreview((current) => (current ? { ...current, copiedToClipboard: true } : current));
    showNotice("分享图已复制");
  };

  const handleNativeShareImage = async () => {
    if (!sharePreview) {
      return;
    }
    const shared = await shareImageFile(sharePreview.blob, sharePreview.filename, "IceBuddy AI 追问", shareText);
    if (!shared) {
      setError("当前浏览器不支持直接系统分享图片，请下载后保存或发送。");
    }
  };

  if (!analysis) {
    return (
      <section className={variant === "workspace" ? "rounded-[24px] border border-slate-200 bg-white p-6" : "app-card p-6"}>
        <p className="text-sm text-slate-500">请选择一条已完成分析开始追问。</p>
      </section>
    );
  }

  const isWorkspace = variant === "workspace";
  const toolTabs: Array<{ id: ToolTab; label: string; count?: number }> = [
    { id: "keyframes", label: "关键帧" },
    { id: "form", label: "待确认", count: pendingSuggestion ? 1 : undefined },
    { id: "corrections", label: "修正卡", count: activeCorrections.length || undefined },
  ];
  const modelSelector = (
    <div className="min-w-0">
      <label className="sr-only" htmlFor={`chat-model-${analysisId}`}>
        回复模型
      </label>
      <select
        id={`chat-model-${analysisId}`}
        value={selectedProviderId}
        onChange={(event) => setSelectedProviderId(event.target.value)}
        className="min-h-[38px] w-full rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 outline-none transition focus:border-teal-300 focus:ring-4 focus:ring-teal-100 tablet:w-[260px]"
        title="回复模型"
      >
        <option value="">默认模型</option>
        {reportProviders.map((provider) => (
          <option key={provider.id} value={provider.id}>
            {provider.name} · {provider.model_id}
          </option>
        ))}
      </select>
    </div>
  );
  const quickPromptBar = (
    <div className="rounded-[22px] border border-teal-100 bg-teal-50/70 p-2">
      <div className="flex items-center justify-between gap-3 tablet:hidden">
        <p className="text-xs font-semibold text-teal-800">快捷问题</p>
        <button
          type="button"
          onClick={() => setQuickPromptsOpen((current) => !current)}
          className="min-h-[32px] rounded-full bg-white px-3 py-1 text-xs font-semibold text-teal-700"
        >
          {quickPromptsOpen ? "收起" : "展开"}
        </button>
      </div>
      <div className={`${quickPromptsOpen ? "mt-2 tablet:mt-0" : "hidden tablet:flex"} flex gap-2 overflow-x-auto pb-1 tablet:flex-wrap tablet:overflow-visible tablet:pb-0`}>
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => void submitMessage(prompt)}
            disabled={isSending}
            className="min-h-[36px] shrink-0 rounded-full border border-teal-100 bg-white px-3 py-1.5 text-xs font-semibold leading-5 text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {prompt}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setIsVideoKeyframeConfirmOpen(true)}
          disabled={isSending || isRerunningVideoKeyframes}
          className="min-h-[36px] shrink-0 rounded-full border border-amber-200 bg-white px-3 py-1.5 text-xs font-semibold leading-5 text-amber-700 transition hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-60"
          title="不重跑主人物追踪，只生成关键帧修正卡"
        >
          视频 AI 重识别关键帧
        </button>
      </div>
    </div>
  );
  const manualFormPanel = (
    <div className="rounded-[24px] border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-slate-900">待确认数据 form</h3>
        {pendingSuggestion ? <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700">有新建议</span> : null}
      </div>
      <div className="mt-4 space-y-3">
        {pendingSuggestion ? (
          <div className="rounded-[18px] border border-amber-200 bg-amber-50 p-3">
            <p className="text-xs leading-5 text-amber-700">发现新的 AI 建议，可同步到表单后再确认。</p>
            <button
              type="button"
              onClick={() => applySuggestionToForm(pendingSuggestion)}
              className="mt-2 min-h-[34px] rounded-full bg-amber-600 px-3 py-1 text-xs font-semibold text-white"
            >
              同步到表单
            </button>
          </div>
        ) : null}
        <label className="block text-xs font-semibold text-slate-500">
          动作类型
          <input
            value={manualForm.actionType}
            onChange={(event) => updateManualForm({ actionType: event.target.value })}
            className="mt-2 w-full rounded-[18px] border border-slate-200 px-3 py-2 text-sm font-normal text-slate-700 outline-none focus:border-teal-300 focus:ring-4 focus:ring-teal-100"
            placeholder="例如 jump / spin / step"
          />
        </label>
        <label className="block text-xs font-semibold text-slate-500">
          动作名称
          <input
            value={manualForm.actionSubtype}
            onChange={(event) => updateManualForm({ actionSubtype: event.target.value })}
            className="mt-2 w-full rounded-[18px] border border-slate-200 px-3 py-2 text-sm font-normal text-slate-700 outline-none focus:border-teal-300 focus:ring-4 focus:ring-teal-100"
            placeholder="例如 Toe Loop / Salchow"
          />
        </label>
        <div className="grid grid-cols-3 gap-2">
          {[
            ["takeoffFrame", "T"],
            ["apexFrame", "A"],
            ["landingFrame", "L"],
          ].map(([key, label]) => (
            <label key={key} className="block text-xs font-semibold text-slate-500">
              {label}
              <input
                value={manualForm[key as keyof ManualFormState]}
                onChange={(event) => updateManualForm({ [key]: event.target.value } as Partial<ManualFormState>)}
                className="mt-2 w-full rounded-[18px] border border-slate-200 px-3 py-2 text-sm font-normal text-slate-700 outline-none focus:border-teal-300 focus:ring-4 focus:ring-teal-100"
                placeholder="frame id"
              />
            </label>
          ))}
        </div>
        <textarea
          value={manualForm.rationale}
          onChange={(event) => updateManualForm({ rationale: event.target.value })}
          rows={2}
          className="w-full rounded-[18px] border border-slate-200 px-3 py-2 text-sm text-slate-700 outline-none focus:border-teal-300 focus:ring-4 focus:ring-teal-100"
          placeholder="修正理由"
        />
        <div className="grid gap-2 phone:grid-cols-2 xl:grid-cols-1">
          <button
            type="button"
            onClick={() => void submitManualCorrection("action_label")}
            disabled={isMutating}
            className="min-h-[40px] rounded-full bg-teal-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            生成动作修正卡
          </button>
          <button
            type="button"
            onClick={() => void submitManualCorrection("keyframes")}
            disabled={isMutating}
            className="min-h-[40px] rounded-full border border-teal-200 bg-teal-50 px-4 py-2 text-sm font-semibold text-teal-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            生成关键帧修正卡
          </button>
        </div>
      </div>
    </div>
  );
  const correctionsPanel = (
    <div className="rounded-[24px] border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">修正卡</h3>
        <button
          type="button"
          onClick={() => void mutateCorrection(() => regenerateReportFromCorrections(analysisId), "已按修正重新生成有效报告。")}
          disabled={isMutating || !appliedCorrections.length}
          className="min-h-[36px] rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          重新生成报告
        </button>
      </div>
      <div className="mt-3 space-y-3">
        {activeCorrections.length ? (
          activeCorrections.slice().reverse().map((correction) => (
            <article key={correction.id} className="rounded-[20px] border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-900">{correctionTitle(correction)}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{correctionSummary(correction)}</p>
                </div>
                <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${statusClass(correction.status)}`}>
                  {statusLabel(correction.status)}
                </span>
              </div>
              {correction.rationale ? <p className="mt-2 text-xs leading-5 text-slate-500">理由：{correction.rationale}</p> : null}
              {correction.status === "proposed" ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void mutateCorrection(() => applyAnalysisCorrection(analysisId, correction.id), "修正已应用到有效数据。")}
                    disabled={isMutating}
                    className="min-h-[34px] rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    应用
                  </button>
                  <button
                    type="button"
                    onClick={() => void mutateCorrection(() => dismissAnalysisCorrection(analysisId, correction.id), "已忽略该修正。")}
                    disabled={isMutating}
                    className="min-h-[34px] rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    忽略
                  </button>
                </div>
              ) : null}
            </article>
          ))
        ) : (
          <p className="text-sm leading-6 text-slate-500">暂无修正卡。AI 或手动提出后，会在这里等待确认。</p>
        )}
      </div>
    </div>
  );

  return (
    <section className={`${isWorkspace ? "min-w-0" : "app-card"} min-w-0 overflow-hidden ${isWorkspace ? "p-0" : "p-4 phone:p-5 tablet:p-6"} ${compact || isWorkspace ? "" : "h-full"}`}>
      {!isWorkspace ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-600">Follow-up</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">AI 追问</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">基于已保存证据回答；修正需要人工确认后才会生效。</p>
          </div>
          <button
            type="button"
            onClick={() => void handleShare()}
            disabled={isSharing || analysis.status !== "completed"}
            className="min-h-[40px] rounded-full border border-teal-200 bg-teal-50 px-4 py-2 text-sm font-semibold text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSharing ? "生成中..." : "分享追问"}
          </button>
        </div>
      ) : null}

      {analysis.status !== "completed" ? (
        <div className="mt-5 rounded-[22px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">只有已完成分析才能继续追问。</div>
      ) : null}

      <div className={`${isWorkspace ? "mt-0" : "mt-5"} grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]`}>
        <div className="min-w-0 space-y-4">
          {isWorkspace ? (
            <div className="rounded-[24px] border border-slate-200 bg-white p-3">
              <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-slate-900">AI 追问</h2>
                  <p className="mt-1 text-xs leading-5 text-slate-500">回答会基于当前报告和已确认修正。</p>
                </div>
                <div className="flex flex-col gap-2 phone:flex-row tablet:items-center">
                  {modelSelector}
                  <button
                    type="button"
                    onClick={() => void handleShare()}
                    disabled={isSharing || analysis.status !== "completed"}
                    className="min-h-[38px] rounded-full border border-teal-200 bg-teal-50 px-4 py-1.5 text-xs font-semibold text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isSharing ? "生成中..." : "分享追问"}
                  </button>
                </div>
              </div>
              <div className="mt-3">{quickPromptBar}</div>
            </div>
          ) : null}
          <div
            ref={messageListRef}
            className="max-h-[min(64dvh,620px)] min-h-[360px] space-y-3 overflow-y-auto rounded-[24px] border border-slate-200 bg-slate-50 p-3 tablet:min-h-[440px] xl:min-h-[560px]"
          >
            {isLoading ? (
              <p className="px-2 py-8 text-center text-sm text-slate-500">正在加载追问记录...</p>
            ) : messages.length ? (
              messages.map((message) => {
                const isUser = message.role === "user";
                return (
                  <div key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                    <div
                      className={`max-w-[92%] whitespace-pre-wrap break-words rounded-[22px] px-4 py-3 text-sm leading-7 tablet:max-w-[84%] ${
                        isUser ? "bg-teal-600 text-white" : "border border-white bg-white text-slate-700 shadow-sm"
                      }`}
                    >
                      {!isUser && (message.provider_name || message.model_id) ? (
                        <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                          {message.provider_name || message.model_id}
                        </p>
                      ) : null}
                      {message.content}
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="px-2 py-6 text-sm leading-7 text-slate-500">
                <p className="font-semibold text-slate-700">围绕这条视频继续问。</p>
                <p className="mt-1">可以追问 comments、动作识别、关键帧冲突、partial candidates 和训练建议。</p>
              </div>
            )}
            {isSending ? (
              <div className="flex justify-start">
                <div className="rounded-[22px] border border-white bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">AI 正在对照证据...</div>
              </div>
            ) : null}
          </div>

          {!isWorkspace ? quickPromptBar : null}

          <form
            onSubmit={handleSubmit}
            className="sticky z-20 space-y-3 rounded-[24px] border border-slate-200 bg-white/95 p-3 shadow-[0_18px_46px_rgba(15,23,42,0.16)] backdrop-blur tablet:static tablet:border-0 tablet:bg-transparent tablet:p-0 tablet:shadow-none tablet:backdrop-blur-0"
            style={{ bottom: "calc(var(--bottom-nav-height) + env(safe-area-inset-bottom, 0px) + 12px)" }}
          >
            {!isWorkspace ? (
              <div className="grid gap-2 tablet:grid-cols-[minmax(0,1fr)_minmax(220px,320px)] tablet:items-end">
                {modelSelector}
                <p className="text-xs leading-5 text-slate-400">
                  只影响本次追问回复；视频分析模型不会被切换。
                </p>
              </div>
            ) : null}
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              rows={3}
              maxLength={4000}
              placeholder="继续问这条视频..."
              className="min-h-[92px] w-full resize-y rounded-[22px] border border-slate-200 bg-white px-4 py-3 text-sm leading-7 text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-teal-300 focus:ring-4 focus:ring-teal-100"
            />
            {error ? <p className="text-sm leading-6 text-rose-600">{error}</p> : null}
            <div className="flex flex-col gap-3 phone:flex-row phone:items-center phone:justify-between">
              <span className="text-xs text-slate-400">{input.length}/4000</span>
              <button
                type="submit"
                disabled={isSending || !input.trim() || analysis.status !== "completed"}
                className="min-h-[44px] w-full rounded-full bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 phone:w-auto"
              >
                {isSending ? "发送中..." : "发送"}
              </button>
            </div>
          </form>
        </div>

        <aside className="min-w-0 space-y-4">
          {!isWorkspace ? (
            <div className="rounded-[24px] border border-slate-200 bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-900">有效识别</h3>
                {appliedCorrections.length ? <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-600">已人工修正</span> : null}
              </div>
              <p className="mt-3 text-sm leading-6 text-slate-600">{analysis.action_subtype || analysis.action_type}</p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                {currentKeyFrames(analysis).map(([key, value]) => (
                  <span key={key} className="rounded-full bg-slate-100 px-3 py-1">{key}: {String(value)}</span>
                ))}
              </div>
            </div>
          ) : null}
          <div className="rounded-[24px] border border-slate-200 bg-white p-2">
            <div className="grid grid-cols-3 gap-2">
              {toolTabs.map((tab) => {
                const selected = activeToolTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveToolTab(tab.id)}
                    className={`min-h-[38px] rounded-full px-2 py-1 text-xs font-semibold transition ${
                      selected ? "bg-slate-900 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {tab.label}
                    {tab.count ? <span className={selected ? "ml-1 text-white/80" : "ml-1 text-slate-400"}>{tab.count}</span> : null}
                  </button>
                );
              })}
            </div>
          </div>
          {activeToolTab === "keyframes" ? (
            <KeyframeEvidencePanel
              analysis={analysis}
              draftKeyframes={draftKeyframes}
              onSyncFrames={syncKeyframesToForm}
            />
          ) : null}
          {activeToolTab === "form" ? manualFormPanel : null}
          {activeToolTab === "corrections" ? correctionsPanel : null}
        </aside>
      </div>

      {shareText ? (
        <div className="mt-4 rounded-[24px] border border-teal-200 bg-teal-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-semibold text-teal-800">分享内容</p>
            <button
              type="button"
              onClick={() => void navigator.clipboard?.writeText(shareText)}
              className="min-h-[36px] rounded-full bg-white px-3 py-1 text-xs font-semibold text-teal-700"
            >
              复制文字
            </button>
          </div>
          <pre className="mt-3 max-h-44 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-teal-900">{shareText}</pre>
          {sharePreview ? (
            <div className="mt-4 grid gap-3 tablet:grid-cols-[160px_1fr] tablet:items-center">
              <button
                type="button"
                onClick={() => setIsSharePreviewOpen(true)}
                className="w-full max-w-[180px] overflow-hidden rounded-[18px] border border-white bg-white text-left shadow-sm transition hover:scale-[1.01]"
                aria-label="打开追问分享图大图预览"
              >
                <img src={sharePreview.url} alt="追问分享图预览" className="w-full object-contain" />
              </button>
              <div className="space-y-2">
                <p className="text-xs leading-5 text-teal-700">
                  {sharePreview.copiedToClipboard ? "图片已复制到剪贴板。" : "可点缩略图预览大图，或下载/系统分享。"}
                </p>
                <p className="text-[11px] text-teal-600">{Math.max(1, Math.round(sharePreview.sizeBytes / 1024))} KB · JPEG</p>
                <a href={sharePreview.url} download={sharePreview.filename} className="inline-flex min-h-[36px] items-center rounded-full bg-teal-700 px-3 py-1 text-xs font-semibold text-white">
                  下载图片
                </a>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="sr-only" aria-live="polite">
        {pendingCorrections.length} pending corrections
      </div>
      {isRetryConfirmOpen ? (
        <RetryAnalysisConfirmSheet
          isSubmitting={isRetryingAnalysis}
          resetTargetLock
          onClose={() => {
            if (!isRetryingAnalysis) {
              setIsRetryConfirmOpen(false);
            }
          }}
          onConfirm={() => void handleConfirmFullReanalysis()}
        />
      ) : null}
      {isVideoKeyframeConfirmOpen ? (
        <RetryAnalysisConfirmSheet
          mode="video_keyframes"
          isSubmitting={isRerunningVideoKeyframes}
          onClose={() => {
            if (!isRerunningVideoKeyframes) {
              setIsVideoKeyframeConfirmOpen(false);
            }
          }}
          onConfirm={() => void handleConfirmVideoAIKeyframeRerun()}
        />
      ) : null}
      {sharePreview && isSharePreviewOpen ? (
        <div className="fixed inset-0 z-[80] grid place-items-center bg-slate-950/40 px-4 py-6 backdrop-blur-sm">
          <section className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_24px_80px_rgba(15,23,42,0.28)] tablet:p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-600">Share Image</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-900">追问分享图</h2>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  {sharePreview.canNativeShare ? "可用系统分享保存到照片或发送给别人。" : "当前浏览器不支持直接系统分享图片，可下载后保存。"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsSharePreviewOpen(false)}
                className="min-h-[40px] rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
              >
                关闭
              </button>
            </div>

            <div className="mt-5 overflow-hidden rounded-[22px] border border-slate-200 bg-slate-100">
              <img src={sharePreview.url} alt="追问分享图大图预览" className="mx-auto block max-h-[62vh] w-auto max-w-full object-contain" />
            </div>

            <div className="mt-5 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => void handleNativeShareImage()}
                disabled={!sharePreview.canNativeShare}
                className="min-h-[44px] rounded-full border border-teal-200 bg-teal-50 px-5 py-3 text-sm font-semibold text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                系统分享/保存
              </button>
              <button
                type="button"
                onClick={() => void handleCopyShareImage()}
                className="min-h-[44px] rounded-full border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
              >
                复制图片
              </button>
              <a
                href={sharePreview.url}
                download={sharePreview.filename}
                className="min-h-[44px] rounded-full bg-teal-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-teal-800"
              >
                下载图片
              </a>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
