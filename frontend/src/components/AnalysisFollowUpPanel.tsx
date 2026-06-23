import axios from "axios";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  AnalysisChatMessage,
  AnalysisChatShareResponse,
  AnalysisCorrection,
  AnalysisDetail,
  applyAnalysisCorrection,
  createAnalysisCorrection,
  dismissAnalysisCorrection,
  fetchAnalysisChatMessages,
  fetchAnalysisCorrections,
  regenerateReportFromCorrections,
  sendAnalysisChatMessage,
  shareAnalysisChat,
} from "../api/client";
import { canvasToBlob, copyImageBlobToClipboard, drawRoundRect, drawWrappedText, ShareImagePreview } from "../utils/shareCanvas";

const QUICK_PROMPTS = [
  "我的 comments 有没有被考虑？",
  "这个动作为什么这样识别？",
  "partial semantic candidates 和最终关键帧差在哪？",
  "给我 10 分钟训练建议",
];

type ManualFormState = {
  actionSubtype: string;
  takeoffFrame: string;
  apexFrame: string;
  landingFrame: string;
  rationale: string;
};

type AnalysisFollowUpPanelProps = {
  analysis: AnalysisDetail | null;
  compact?: boolean;
  onAnalysisRefresh?: () => void;
  onNotice?: (message: string) => void;
};

function createDefaultManualForm(analysis: AnalysisDetail | null): ManualFormState {
  return {
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

function semanticCandidates(analysis: AnalysisDetail | null) {
  const diagnostics = analysis?.video_temporal_diagnostics;
  return {
    selected: diagnostics?.selected_semantic_frames ?? [],
    partial: diagnostics?.partial_semantic_frames ?? [],
  };
}

async function createChatShareImage(share: AnalysisChatShareResponse) {
  const canvas = document.createElement("canvas");
  const width = 1080;
  const height = 1440;
  const scale = window.devicePixelRatio > 1 ? 2 : 1;
  canvas.width = width * scale;
  canvas.height = height * scale;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("share_image_canvas_failed");
  }
  ctx.scale(scale, scale);

  const payload = share.image_payload ?? {};
  const title = String(payload.title ?? share.title ?? "AI追问复盘");
  const summary = String(payload.summary ?? "围绕已完成分析继续追问，并记录人工确认修正。");
  const question = String(payload.question ?? "本次追问");
  const answer = String(payload.answer ?? "AI 基于已保存证据给出复盘回答。");
  const applied = Array.isArray(payload.applied_corrections) ? payload.applied_corrections : [];
  const pending = Array.isArray(payload.pending_corrections) ? payload.pending_corrections : [];

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

  ctx.fillStyle = "#0F766E";
  ctx.font = "800 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("IceBuddy AI 追问", 112, 142);

  ctx.fillStyle = "#0F172A";
  ctx.font = "800 56px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, title, 112, 226, 760, 64, 2);

  ctx.fillStyle = "#475569";
  ctx.font = "500 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, summary, 112, 380, 856, 44, 3);

  const blocks = [
    { label: "追问", text: question, bg: "#EFF6FF", color: "#2563EB", lines: 3 },
    { label: "回答", text: answer, bg: "#ECFDF5", color: "#059669", lines: 5 },
  ];
  let y = 566;
  blocks.forEach((block) => {
    ctx.fillStyle = block.bg;
    drawRoundRect(ctx, 112, y, 856, block.lines === 5 ? 260 : 190, 28);
    ctx.fill();
    ctx.fillStyle = block.color;
    ctx.font = "800 25px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.fillText(block.label, 152, y + 50);
    ctx.fillStyle = "#0F172A";
    ctx.font = "650 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    drawWrappedText(ctx, block.text, 152, y + 100, 760, 42, block.lines);
    y += block.lines === 5 ? 292 : 222;
  });

  const correctionText = [...applied.map((item) => `已应用：${item}`), ...pending.map((item) => `待确认：${item}`)].join("  ");
  ctx.fillStyle = "#FFF7ED";
  drawRoundRect(ctx, 112, 1110, 856, 132, 28);
  ctx.fill();
  ctx.fillStyle = "#EA580C";
  ctx.font = "800 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("修正记录", 152, 1160);
  ctx.fillStyle = "#334155";
  ctx.font = "600 27px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, correctionText || "暂无已应用修正。", 152, 1202, 760, 36, 2);

  ctx.fillStyle = "#94A3B8";
  ctx.font = "500 22px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText("修正需人工确认后才会进入系统有效数据", 112, 1348);

  const blob = await canvasToBlob(canvas);
  const filename = `icebuddy-chat-${String(payload.analysis_id ?? "share").slice(0, 8)}.png`;
  return { blob, filename };
}

export default function AnalysisFollowUpPanel({ analysis, compact = false, onAnalysisRefresh, onNotice }: AnalysisFollowUpPanelProps) {
  const [messages, setMessages] = useState<AnalysisChatMessage[]>([]);
  const [corrections, setCorrections] = useState<AnalysisCorrection[]>([]);
  const [input, setInput] = useState("");
  const [manualForm, setManualForm] = useState<ManualFormState>(() => createDefaultManualForm(analysis));
  const [detailsOpenByDefault] = useState(() => (typeof window !== "undefined" ? window.matchMedia("(min-width: 1024px)").matches : false));
  const [manualDetailsOpen, setManualDetailsOpen] = useState(() => !compact && detailsOpenByDefault);
  const [evidenceDetailsOpen, setEvidenceDetailsOpen] = useState(() => !compact && detailsOpenByDefault);
  const [error, setError] = useState<string | null>(null);
  const [shareText, setShareText] = useState("");
  const [sharePreview, setSharePreview] = useState<ShareImagePreview | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [isSharing, setIsSharing] = useState(false);

  const analysisId = analysis?.id ?? "";
  const candidates = useMemo(() => semanticCandidates(analysis), [analysis]);
  const activeCorrections = corrections.filter((correction) => correction.status !== "dismissed");
  const pendingCorrections = corrections.filter((correction) => correction.status === "proposed");
  const appliedCorrections = corrections.filter((correction) => correction.status === "applied");

  useEffect(() => {
    setManualForm(createDefaultManualForm(analysis));
  }, [analysis?.id, analysis?.action_subtype]);

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

  const showNotice = (message: string) => {
    onNotice?.(message);
  };

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
      const response = await sendAnalysisChatMessage(analysisId, message);
      setMessages(response.messages);
      setInput("");
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

  const mutateCorrection = async (action: () => Promise<{ corrections: AnalysisCorrection[] }>, successMessage: string) => {
    if (!analysisId || isMutating) {
      return;
    }
    setIsMutating(true);
    setError(null);
    try {
      const response = await action();
      setCorrections(response.corrections);
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
      const actionSubtype = manualForm.actionSubtype.trim();
      if (!actionSubtype) {
        setError("请先填写要修正的动作名称。");
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
              action_subtype: actionSubtype,
              action_confirmation: {
                confirmed_action: actionSubtype,
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
      const { blob, filename } = await createChatShareImage(share);
      const copiedToClipboard = await copyImageBlobToClipboard(blob);
      const url = URL.createObjectURL(blob);
      setSharePreview({ url, blob, filename, copiedToClipboard });
      showNotice(copiedToClipboard ? "追问分享文字和图片已生成" : "追问分享文字已复制，图片可下载");
    } catch {
      setError("追问分享内容生成失败，请稍后再试。");
    } finally {
      setIsSharing(false);
    }
  };

  if (!analysis) {
    return (
      <section className="app-card p-6">
        <p className="text-sm text-slate-500">请选择一条已完成分析开始追问。</p>
      </section>
    );
  }

  return (
    <section className={`app-card min-w-0 overflow-hidden p-4 phone:p-5 tablet:p-6 ${compact ? "" : "h-full"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
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

      {analysis.status !== "completed" ? (
        <div className="mt-5 rounded-[22px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">只有已完成分析才能继续追问。</div>
      ) : null}

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(260px,0.54fr)]">
        <div className="min-w-0 space-y-4">
          <div className="max-h-[min(58dvh,520px)] min-h-[260px] space-y-3 overflow-y-auto rounded-[24px] border border-slate-200 bg-slate-50 p-3 tablet:min-h-[340px]">
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

          <div className="grid grid-cols-1 gap-2 phone:grid-cols-2 tablet:flex tablet:flex-wrap">
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => void submitMessage(prompt)}
                disabled={isSending}
                className="min-h-[40px] rounded-full border border-teal-100 bg-teal-50 px-3 py-2 text-left text-xs font-semibold leading-5 text-teal-700 transition hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-60 tablet:text-center"
              >
                {prompt}
              </button>
            ))}
          </div>

          <form
            onSubmit={handleSubmit}
            className="sticky z-20 space-y-3 rounded-[24px] border border-slate-200 bg-white/95 p-3 shadow-[0_18px_46px_rgba(15,23,42,0.16)] backdrop-blur tablet:static tablet:border-0 tablet:bg-transparent tablet:p-0 tablet:shadow-none tablet:backdrop-blur-0"
            style={{ bottom: "calc(var(--bottom-nav-height) + env(safe-area-inset-bottom, 0px) + 12px)" }}
          >
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

          <details
            className="rounded-[24px] border border-slate-200 bg-white p-4"
            open={manualDetailsOpen}
            onToggle={(event) => setManualDetailsOpen(event.currentTarget.open)}
          >
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">手动提出修正</summary>
            <div className="mt-4 space-y-3">
              <label className="block text-xs font-semibold text-slate-500">
                动作名称
                <input
                  value={manualForm.actionSubtype}
                  onChange={(event) => setManualForm((current) => ({ ...current, actionSubtype: event.target.value }))}
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
                      onChange={(event) => setManualForm((current) => ({ ...current, [key]: event.target.value }))}
                      className="mt-2 w-full rounded-[18px] border border-slate-200 px-3 py-2 text-sm font-normal text-slate-700 outline-none focus:border-teal-300 focus:ring-4 focus:ring-teal-100"
                      placeholder="frame id"
                    />
                  </label>
                ))}
              </div>
              <textarea
                value={manualForm.rationale}
                onChange={(event) => setManualForm((current) => ({ ...current, rationale: event.target.value }))}
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
          </details>

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

          <details
            className="rounded-[24px] border border-slate-200 bg-white p-4"
            open={evidenceDetailsOpen}
            onToggle={(event) => setEvidenceDetailsOpen(event.currentTarget.open)}
          >
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">证据候选</summary>
            <div className="mt-4 space-y-3 text-xs leading-5 text-slate-500">
              <div>
                <p className="font-semibold text-slate-700">最终关键帧</p>
                {candidates.selected.length ? candidates.selected.slice(0, 4).map((item, index) => (
                  <p key={`${item.frame_id}-${index}`} className="mt-1 rounded-[16px] bg-slate-50 px-3 py-2">{item.phase_code ?? item.key_moment ?? "?"}: {item.frame_id ?? item.timestamp}</p>
                )) : <p className="mt-1">暂无</p>}
              </div>
              <div>
                <p className="font-semibold text-slate-700">Partial semantic candidates</p>
                {candidates.partial.length ? candidates.partial.slice(0, 5).map((item, index) => (
                  <p key={`${item.frame_id}-${index}`} className="mt-1 rounded-[16px] bg-amber-50 px-3 py-2 text-amber-700">{item.phase_code ?? item.key_moment ?? "?"}: {item.frame_id ?? item.timestamp}</p>
                )) : <p className="mt-1">暂无</p>}
              </div>
            </div>
          </details>
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
              <img src={sharePreview.url} alt="追问分享图预览" className="w-full max-w-[180px] rounded-[18px] border border-white object-contain" />
              <div className="space-y-2">
                <p className="text-xs leading-5 text-teal-700">{sharePreview.copiedToClipboard ? "图片已复制到剪贴板。" : "当前浏览器未开放图片剪贴板，可下载后分享。"}</p>
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
    </section>
  );
}
