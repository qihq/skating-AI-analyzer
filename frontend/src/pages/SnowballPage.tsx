import axios from "axios";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import {
  applyMemorySuggestions,
  chatWithSnowball,
  createMemory,
  deleteMemory,
  dismissMemorySuggestion,
  fetchMemories,
  fetchMemorySuggestions,
  fetchSkaters,
  MemorySuggestion,
  MemoryExpiryPreset,
  SnowballChatMessage,
  SnowballMemory,
  toggleMemoryPin,
  updateMemory,
  Skater,
} from "../api/client";
import { useAppMode } from "../components/AppModeContext";
import ZodiacAvatar from "../components/ZodiacAvatar";
import { childViewFromSkater, pickSkaterIdForChildView } from "../utils/childView";

const WELCOME_MESSAGE = "嗨！我是冰宝（IceBuddy） ☃️ 今天想练什么？";
const CATEGORY_OPTIONS = ["目标", "偏好", "总结", "卡点", "其他"] as const;
const EXPIRY_OPTIONS: Array<{ label: string; value: MemoryExpiryPreset }> = [
  { label: "1个月", value: "1m" },
  { label: "3个月", value: "3m" },
  { label: "永不过期", value: "never" },
];

type DraftMemory = {
  title: string;
  content: string;
  category: string;
  is_pinned: boolean;
  expires_at: MemoryExpiryPreset;
};

type SuggestionCard = {
  suggestionId: string;
  index: number;
  action: "add" | "update" | "expire";
  title: string;
  content: string;
  category?: string;
};

const EMPTY_MEMORY: DraftMemory = {
  title: "",
  content: "",
  category: "其他",
  is_pinned: false,
  expires_at: "never",
};

function ChatMessageBody({ content }: { content: string }) {
  const blocks = content
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

  return (
    <div className="space-y-3">
      {blocks.map((block, blockIndex) => {
        const lines = block
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        const isList = lines.every((line) => /^([-*•]|\d+\.)\s+/.test(line));

        if (isList) {
          return (
            <div key={blockIndex} className="space-y-2">
              {lines.map((line, lineIndex) => (
                <div key={`${blockIndex}-${lineIndex}`} className="flex items-start gap-2">
                  <span className="mt-[2px] text-blue-500">{line.match(/^(\d+\.)/) ? line.match(/^(\d+\.)/)?.[1] : "•"}</span>
                  <span className="flex-1">{line.replace(/^([-*•]|\d+\.)\s+/, "")}</span>
                </div>
              ))}
            </div>
          );
        }

        const headingMatch = block.match(/^([^：:]{2,20})[：:]\s*(.+)$/);
        if (headingMatch) {
          return (
            <div key={blockIndex} className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{headingMatch[1]}</p>
              <p>{headingMatch[2]}</p>
            </div>
          );
        }

        return (
          <p key={blockIndex} className="whitespace-pre-wrap">
            {block}
          </p>
        );
      })}
    </div>
  );
}

function getExpiryPreset(memory: SnowballMemory): MemoryExpiryPreset {
  if (!memory.expires_at) {
    return "never";
  }
  const diffDays = Math.round((new Date(memory.expires_at).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
  if (diffDays <= 40) {
    return "1m";
  }
  return "3m";
}

function toExpiryPayload(value: MemoryExpiryPreset): string | null {
  return value === "never" ? null : value;
}

function formatExpireText(value: string | null) {
  if (!value) {
    return "永不过期";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).format(new Date(value));
}

function flattenSuggestions(items: MemorySuggestion[]): SuggestionCard[] {
  const cards: SuggestionCard[] = [];
  items.forEach((item) => {
    item.suggestions.forEach((raw, index) => {
      const action = String(raw.action ?? "").toLowerCase();
      if (action === "add") {
        cards.push({
          suggestionId: item.id,
          index,
          action: "add",
          title: String(raw.title ?? "新增记忆"),
          content: String(raw.content ?? ""),
          category: String(raw.category ?? "其他"),
        });
        return;
      }
      if (action === "update") {
        cards.push({
          suggestionId: item.id,
          index,
          action: "update",
          title: String(raw.title ?? "建议更新记忆"),
          content: String(raw.new_content ?? ""),
          category: raw.category ? String(raw.category) : undefined,
        });
        return;
      }
      if (action === "expire") {
        cards.push({
          suggestionId: item.id,
          index,
          action: "expire",
          title: "建议设为过期",
          content: String(raw.reason ?? "目标似乎已完成，建议设为过期"),
        });
      }
    });
  });
  return cards;
}

export default function SnowballPage() {
  const location = useLocation();
  const { isParentMode, childView, setChildView, enterParentMode } = useAppMode();
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState("");
  const [messages, setMessages] = useState<SnowballChatMessage[]>([{ role: "assistant", content: WELCOME_MESSAGE }]);
  const [input, setInput] = useState("");
  const [memories, setMemories] = useState<SnowballMemory[]>([]);
  const [suggestions, setSuggestions] = useState<MemorySuggestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isChatting, setIsChatting] = useState(false);
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);
  const [isLoadingSuggestions, setIsLoadingSuggestions] = useState(false);
  const [isMutatingSuggestion, setIsMutatingSuggestion] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSavingMemory, setIsSavingMemory] = useState(false);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [draftMemory, setDraftMemory] = useState<DraftMemory>(EMPTY_MEMORY);
  const historyRef = useRef<HTMLDivElement | null>(null);
  const suggestionAnchorRef = useRef<HTMLDivElement | null>(null);
  const focusSkaterId = (location.state as { focusSkaterId?: string; focusSuggestions?: boolean } | null)?.focusSkaterId;
  const shouldFocusSuggestions = Boolean((location.state as { focusSuggestions?: boolean } | null)?.focusSuggestions);

  const suggestionCards = useMemo(() => flattenSuggestions(suggestions), [suggestions]);

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (cancelled) {
          return;
        }
        setSkaters(data);
        setSelectedSkaterId(focusSkaterId || (isParentMode ? "" : pickSkaterIdForChildView(data, childView)) || data.find((skater) => skater.is_default)?.id || data[0]?.id || "");
      } catch {
        if (!cancelled) {
          setError("冰宝（IceBuddy）暂时没有拿到练习档案，请稍后再试。");
        }
      }
    };

    void loadSkaters();
    return () => {
      cancelled = true;
    };
  }, [childView, focusSkaterId, isParentMode]);

  useEffect(() => {
    if (isParentMode || focusSkaterId || !skaters.length) {
      return;
    }

    const nextSkaterId = pickSkaterIdForChildView(skaters, childView);
    setSelectedSkaterId((current) => (current === nextSkaterId ? current : nextSkaterId));
  }, [childView, focusSkaterId, isParentMode, skaters]);

  useEffect(() => {
    if (!selectedSkaterId || !isParentMode) {
      return;
    }

    let cancelled = false;
    const loadMemories = async () => {
      setIsLoadingMemories(true);
      setMemoryError(null);
      try {
        const data = await fetchMemories(selectedSkaterId);
        if (!cancelled) {
          setMemories(data);
        }
      } catch {
        if (!cancelled) {
          setMemoryError("长期记忆加载失败了，请稍后再试。");
        }
      } finally {
        if (!cancelled) {
          setIsLoadingMemories(false);
        }
      }
    };

    void loadMemories();
    return () => {
      cancelled = true;
    };
  }, [isParentMode, selectedSkaterId]);

  useEffect(() => {
    if (!selectedSkaterId || !isParentMode) {
      setSuggestions([]);
      return;
    }

    let cancelled = false;
    const loadSuggestions = async () => {
      setIsLoadingSuggestions(true);
      try {
        const data = await fetchMemorySuggestions(selectedSkaterId);
        if (!cancelled) {
          setSuggestions(data);
        }
      } catch {
        if (!cancelled) {
          setSuggestions([]);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingSuggestions(false);
        }
      }
    };

    void loadSuggestions();
    return () => {
      cancelled = true;
    };
  }, [isParentMode, selectedSkaterId]);

  useEffect(() => {
    historyRef.current?.scrollTo({ top: historyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, isChatting]);

  useEffect(() => {
    if (!shouldFocusSuggestions || !suggestionCards.length) {
      return;
    }
    suggestionAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [shouldFocusSuggestions, suggestionCards.length]);

  const selectedSkater = skaters.find((skater) => skater.id === selectedSkaterId) ?? null;

  const handleSkaterChange = (nextSkaterId: string) => {
    setSelectedSkaterId(nextSkaterId);
    if (isParentMode) {
      return;
    }

    const nextView = childViewFromSkater(skaters.find((skater) => skater.id === nextSkaterId));
    if (nextView) {
      setChildView(nextView);
    }
  };

  const resetMemoryModal = () => {
    setIsModalOpen(false);
    setEditingMemoryId(null);
    setDraftMemory(EMPTY_MEMORY);
    setMemoryError(null);
  };

  const refreshMemories = async () => {
    if (!selectedSkaterId) {
      return;
    }
    const data = await fetchMemories(selectedSkaterId);
    setMemories(data);
  };

  const refreshSuggestions = async () => {
    if (!selectedSkaterId) {
      return;
    }
    const data = await fetchMemorySuggestions(selectedSkaterId);
    setSuggestions(data);
  };

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2200);
  };

  const handleChatSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || isChatting) {
      return;
    }

    const nextMessages = [...messages, { role: "user" as const, content: message }];
    setMessages(nextMessages);
    setInput("");
    setError(null);
    setIsChatting(true);

    try {
      const response = await chatWithSnowball({
        skater_id: selectedSkaterId || undefined,
        message,
        history: nextMessages.slice(1),
      });
      setMessages((current) => [...current, { role: "assistant", content: response.reply }]);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "冰宝（IceBuddy）这会儿没有顺利回复。"));
      } else {
        setError("冰宝（IceBuddy）这会儿没有顺利回复。");
      }
    } finally {
      setIsChatting(false);
    }
  };

  const handleSaveMemory = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedSkaterId) {
      setMemoryError("请先选择练习档案。");
      return;
    }

    setIsSavingMemory(true);
    setMemoryError(null);

    const payload = {
      title: draftMemory.title,
      content: draftMemory.content,
      category: draftMemory.category,
      is_pinned: draftMemory.is_pinned,
      expires_at: toExpiryPayload(draftMemory.expires_at),
    };

    try {
      if (editingMemoryId) {
        await updateMemory(selectedSkaterId, editingMemoryId, payload);
        showNotice("冰宝（IceBuddy）记忆已更新。");
      } else {
        await createMemory(selectedSkaterId, payload);
        showNotice("已新增一条冰宝（IceBuddy）记忆。");
      }
      await refreshMemories();
      resetMemoryModal();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setMemoryError(String(requestError.response?.data?.detail ?? "记忆保存失败，请稍后再试。"));
      } else {
        setMemoryError("记忆保存失败，请稍后再试。");
      }
    } finally {
      setIsSavingMemory(false);
    }
  };

  const handleDeleteMemory = async (memory: SnowballMemory) => {
    if (!selectedSkaterId) {
      return;
    }
    const confirmed = window.confirm(`要删除「${memory.title}」这条冰宝（IceBuddy）记忆吗？`);
    if (!confirmed) {
      return;
    }

    try {
      await deleteMemory(selectedSkaterId, memory.id);
      setMemories((current) => current.filter((item) => item.id !== memory.id));
      showNotice("冰宝（IceBuddy）记忆已删除。");
    } catch {
      setMemoryError("删除失败了，请稍后再试。");
    }
  };

  const handleTogglePin = async (memory: SnowballMemory) => {
    if (!selectedSkaterId) {
      return;
    }

    try {
      const updated = await toggleMemoryPin(selectedSkaterId, memory.id, !memory.is_pinned);
      setMemories((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      showNotice(updated.is_pinned ? "这条记忆已固定给冰宝（IceBuddy）。" : "这条记忆已取消固定。");
    } catch {
      setMemoryError("固定状态更新失败，请稍后再试。");
    }
  };

  const handleApplySuggestion = async (card: SuggestionCard) => {
    if (!selectedSkaterId) {
      return;
    }
    setIsMutatingSuggestion(`${card.suggestionId}:${card.index}`);
    try {
      await applyMemorySuggestions(selectedSkaterId, card.suggestionId, [card.index]);
      await Promise.all([refreshMemories(), refreshSuggestions()]);
      showNotice("记忆建议已采纳。");
    } catch {
      setMemoryError("采纳建议失败，请稍后再试。");
    } finally {
      setIsMutatingSuggestion(null);
    }
  };

  const handleDismissSuggestion = async (card: SuggestionCard) => {
    if (!selectedSkaterId) {
      return;
    }
    setIsMutatingSuggestion(`${card.suggestionId}:${card.index}`);
    try {
      await dismissMemorySuggestion(selectedSkaterId, card.suggestionId);
      await refreshSuggestions();
      showNotice("建议已忽略。");
    } catch {
      setMemoryError("忽略建议失败，请稍后再试。");
    } finally {
      setIsMutatingSuggestion(null);
    }
  };

  const openCreateModal = () => {
    setEditingMemoryId(null);
    setDraftMemory(EMPTY_MEMORY);
    setIsModalOpen(true);
    setMemoryError(null);
  };

  const openEditModal = (memory: SnowballMemory) => {
    setEditingMemoryId(memory.id);
    setDraftMemory({
      title: memory.title,
      content: memory.content,
      category: memory.category,
      is_pinned: memory.is_pinned,
      expires_at: getExpiryPreset(memory),
    });
    setIsModalOpen(true);
    setMemoryError(null);
  };

  return (
    <div className="space-y-6">
      {notice ? (
        <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div>
      ) : null}

      <section className="app-card overflow-hidden p-6 tablet:p-8">
        <div className="grid gap-6 web:grid-cols-[1.05fr_0.95fr]">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">SNOWBALL COACH</p>
            <div className="mt-4 flex items-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-[24px] bg-gradient-to-br from-sky-100 via-white to-blue-100 text-3xl shadow-[0_12px_30px_rgba(59,130,246,0.18)]">
                ❄️
              </div>
              <div>
                <h1 className="text-3xl font-semibold text-slate-900 tablet:text-4xl">冰宝（IceBuddy）</h1>
                <p className="mt-1 text-sm uppercase tracking-[0.28em] text-slate-400">Snowball Coach</p>
              </div>
            </div>
            <p className="mt-5 max-w-2xl text-base leading-8 text-slate-500">
              冰宝（IceBuddy）会结合你固定留下来的长期记忆、最近训练背景和当前问题，给出更简洁、更能直接执行的陪练建议。
            </p>
          </div>

          <div className="app-card-muted rounded-[32px] p-5">
            <p className="text-sm font-semibold text-slate-900">当前练习档案</p>
            <div className="mt-4 flex flex-wrap gap-3">
              {skaters.map((skater) => {
                const selected = skater.id === selectedSkaterId;
                return (
                  <button
                    key={skater.id}
                    type="button"
                    onClick={() => handleSkaterChange(skater.id)}
                    className={`inline-flex min-h-[60px] items-center gap-3 rounded-full px-4 py-2 text-sm font-medium transition ${
                      selected ? "bg-blue-500 text-white shadow-[0_12px_24px_rgba(59,130,246,0.22)]" : "bg-white text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    <ZodiacAvatar avatarType={skater.avatar_type} avatarEmoji={skater.avatar_emoji} size="sm" animate={selected} />
                    <span>{skater.display_name || skater.name}</span>
                  </button>
                );
              })}
            </div>
            {selectedSkater ? (
              <p className="mt-4 text-sm leading-7 text-slate-500">
                当前对象：{selectedSkater.display_name || selectedSkater.name}
                {selectedSkater.level ? ` · ${selectedSkater.level}` : ""}
              </p>
            ) : null}
          </div>
        </div>
      </section>

      <div className="grid gap-6 web:grid-cols-[1.05fr_0.95fr]">
        <section className="app-card flex min-h-[680px] flex-col overflow-hidden p-0">
          <div className="border-b border-slate-100 px-6 py-5 tablet:px-7">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Chat</p>
            <p className="mt-2 text-lg font-semibold text-slate-900">和冰宝（IceBuddy）聊聊今天想练什么</p>
          </div>

          <div ref={historyRef} className="flex-1 space-y-4 overflow-y-auto px-6 py-5 tablet:px-7">
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`flex ${message.role === "assistant" ? "justify-start" : "justify-end"}`}>
                <div
                  className={`max-w-[88%] rounded-[28px] px-5 py-4 text-sm leading-7 shadow-sm ${
                    message.role === "assistant"
                      ? "border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-sky-50 text-slate-700"
                      : "bg-blue-500 text-white shadow-[0_12px_24px_rgba(59,130,246,0.2)]"
                  }`}
                >
                  {message.role === "assistant" ? <ChatMessageBody content={message.content} /> : <p className="whitespace-pre-wrap">{message.content}</p>}
                </div>
              </div>
            ))}
            {isChatting ? (
              <div className="flex justify-start">
                <div className="rounded-[28px] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-sky-50 px-5 py-4 text-sm text-slate-500">
                  冰宝（IceBuddy）正在想一想…
                </div>
              </div>
            ) : null}
          </div>

          <form onSubmit={handleChatSubmit} className="border-t border-slate-100 bg-white px-6 py-5 tablet:px-7">
            {error ? <p className="mb-3 rounded-[20px] bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</p> : null}
            <div className="flex flex-col gap-3 tablet:flex-row tablet:items-end">
              <div className="flex-1 space-y-2">
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  rows={3}
                  placeholder="比如：今天华尔兹落冰总是飘，先从哪一步练？"
                  className="app-textarea min-h-[120px] resize-none"
                />
                <p className="text-xs text-slate-400">建议一条消息只问一个重点，冰宝的回答会更清楚。</p>
              </div>
              <button
                type="submit"
                disabled={!input.trim() || isChatting}
                className="min-h-[52px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-55"
              >
                {isChatting ? "发送中..." : "发给冰宝（IceBuddy）"}
              </button>
            </div>
          </form>
        </section>

        <section className="app-card p-6 tablet:p-7">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">SNOWBALL MEMORY</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">长期记忆</h2>
              <p className="mt-3 max-w-xl text-sm leading-7 text-slate-500">
                这里保存冰宝（IceBuddy）长期参考的信息，比如你的目标、偏好、常见卡点，以及你想固定留下来的摘要。
              </p>
            </div>

            {isParentMode ? (
              <div className="flex gap-3">
                <Link to="/settings/api" className="app-pill text-sm font-semibold text-slate-700">
                  API 设置
                </Link>
                <button
                  type="button"
                  onClick={openCreateModal}
                  className="min-h-[48px] rounded-full bg-blue-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-blue-600"
                >
                  新增一条记忆
                </button>
              </div>
            ) : (
              <button type="button" onClick={() => void enterParentMode()} className="app-pill text-sm font-semibold">
                进入家长模式
              </button>
            )}
          </div>

          {!isParentMode ? (
            <div className="mt-6 rounded-[28px] border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-sm leading-7 text-slate-500">
              长期记忆只在家长模式可见。进入家长模式后，你可以固定目标、偏好和阶段总结，让冰宝（IceBuddy）每次都带着这些背景一起思考。
            </div>
          ) : isLoadingMemories ? (
            <div className="mt-6 rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">冰宝（IceBuddy）正在整理长期记忆…</div>
          ) : (
            <>
              {memoryError ? <p className="mt-5 rounded-[20px] bg-rose-50 px-4 py-3 text-sm text-rose-600">{memoryError}</p> : null}

              <div ref={suggestionAnchorRef} className="mt-6 space-y-4">
                {isLoadingSuggestions ? (
                  <div className="rounded-[28px] bg-amber-50 px-5 py-5 text-sm text-amber-700">冰宝（IceBuddy）正在整理记忆建议…</div>
                ) : suggestionCards.length ? (
                  <section className="rounded-[28px] border border-amber-200 bg-amber-50/70 p-5">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-lg font-semibold text-slate-900">待确认建议（{suggestionCards.length}条）</h3>
                    </div>
                    <div className="mt-4 space-y-4">
                      {suggestionCards.map((card) => {
                        const busy = isMutatingSuggestion === `${card.suggestionId}:${card.index}`;
                        return (
                          <article key={`${card.suggestionId}-${card.index}`} className="rounded-[24px] border border-amber-200 bg-white/90 p-4">
                            <p className="text-sm font-semibold text-amber-700">
                              [{card.action === "add" ? "新增" : card.action === "update" ? "更新" : "过期"}] {card.title}
                            </p>
                            <p className="mt-2 text-sm leading-7 text-slate-600">「{card.content}」</p>
                            {card.category ? <p className="mt-2 text-xs text-slate-500">分类：{card.category}</p> : null}
                            <div className="mt-4 flex flex-wrap gap-3">
                              <button
                                type="button"
                                onClick={() => void handleApplySuggestion(card)}
                                disabled={busy}
                                className="min-h-[42px] rounded-full bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-60"
                              >
                                {busy ? "处理中..." : "✅ 采纳"}
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleDismissSuggestion(card)}
                                disabled={busy}
                                className="min-h-[42px] rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                              >
                                ❌ 忽略
                              </button>
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  </section>
                ) : null}
              </div>

              <div className="mt-6 space-y-4">
                {memories.length ? (
                  memories.map((memory) => (
                    <article
                      key={memory.id}
                      className={`rounded-[28px] border p-5 shadow-[0_12px_30px_rgba(15,23,42,0.04)] ${
                        memory.is_expired ? "border-slate-200 bg-slate-50 text-slate-400" : "border-slate-200 bg-white"
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h3 className={`text-lg font-semibold ${memory.is_expired ? "text-slate-500" : "text-slate-900"}`}>{memory.title}</h3>
                          <p className={`mt-3 max-w-xl text-sm leading-7 ${memory.is_expired ? "text-slate-500" : "text-slate-600"}`}>{memory.content}</p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {!memory.is_expired ? (
                            <button
                              type="button"
                              onClick={() => handleTogglePin(memory)}
                              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                                memory.is_pinned ? "bg-blue-50 text-blue-600" : "bg-slate-100 text-slate-500"
                              }`}
                            >
                              {memory.is_pinned ? "固定" : "未固定"}
                            </button>
                          ) : (
                            <span className="rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-500">已过期</span>
                          )}
                          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{memory.category}</span>
                          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">
                            {memory.is_expired ? "过期于" : "过期设置"}：{formatExpireText(memory.expires_at)}
                          </span>
                        </div>
                      </div>

                      <div className="mt-4 flex flex-wrap gap-3">
                        <button type="button" onClick={() => openEditModal(memory)} className="app-pill text-sm font-semibold">
                          编辑
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteMemory(memory)}
                          className="rounded-full border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-100"
                        >
                          删除
                        </button>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="rounded-[28px] border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-sm leading-7 text-slate-500">
                    还没有长期记忆。你可以先固定一个目标，比如“华尔兹”，让冰宝（IceBuddy）之后都记得。
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {isModalOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/45 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-2xl rounded-[32px] bg-white p-6 shadow-[0_24px_80px_rgba(15,23,42,0.28)] tablet:p-7">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Snowball Memory</p>
                <h3 className="mt-2 text-2xl font-semibold text-slate-900">{editingMemoryId ? "编辑记忆" : "新增一条记忆"}</h3>
              </div>
              <button type="button" onClick={resetMemoryModal} className="app-pill px-4 text-sm font-semibold">
                关闭
              </button>
            </div>

            <form onSubmit={handleSaveMemory} className="mt-6 space-y-4">
              <label className="block space-y-2">
                <span className="text-sm font-medium text-slate-700">标题</span>
                <input
                  value={draftMemory.title}
                  onChange={(event) => setDraftMemory((current) => ({ ...current, title: event.target.value }))}
                  className="app-input"
                  placeholder="比如：当前目标"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-sm font-medium text-slate-700">内容</span>
                <textarea
                  value={draftMemory.content}
                  onChange={(event) => setDraftMemory((current) => ({ ...current, content: event.target.value }))}
                  rows={5}
                  className="app-textarea min-h-[150px] resize-y"
                  placeholder="写下冰宝（IceBuddy）以后每次都该记住的信息"
                />
              </label>

              <fieldset className="space-y-3">
                <legend className="text-sm font-medium text-slate-700">分类</legend>
                <div className="flex flex-wrap gap-2">
                  {CATEGORY_OPTIONS.map((category) => {
                    const selected = draftMemory.category === category;
                    return (
                      <button
                        key={category}
                        type="button"
                        onClick={() => setDraftMemory((current) => ({ ...current, category }))}
                        className={`min-h-[44px] rounded-full px-4 text-sm font-semibold transition ${
                          selected ? "bg-blue-500 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        }`}
                      >
                        {category}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              <fieldset className="space-y-3">
                <legend className="text-sm font-medium text-slate-700">过期设置</legend>
                <div className="flex flex-wrap gap-2">
                  {EXPIRY_OPTIONS.map((option) => {
                    const selected = draftMemory.expires_at === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setDraftMemory((current) => ({ ...current, expires_at: option.value }))}
                        className={`min-h-[44px] rounded-full px-4 text-sm font-semibold transition ${
                          selected ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        }`}
                      >
                        {option.label}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              <label className="settings-row flex items-center justify-between rounded-[24px] bg-slate-50 px-4 py-4">
                <div>
                  <p className="text-sm font-semibold text-slate-900">固定给冰宝（IceBuddy）</p>
                  <p className="mt-1 text-sm text-slate-500">固定后，这条记忆会在未过期时注入到冰宝（IceBuddy）的长期 context。</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={draftMemory.is_pinned}
                  onClick={() => setDraftMemory((current) => ({ ...current, is_pinned: !current.is_pinned }))}
                  data-checked={draftMemory.is_pinned}
                  className={`toggle-switch ${draftMemory.is_pinned ? "bg-blue-500" : "bg-slate-300"}`}
                >
                  <span
                    className="toggle-thumb bg-white"
                  />
                </button>
              </label>

              {memoryError ? <p className="rounded-[20px] bg-rose-50 px-4 py-3 text-sm text-rose-600">{memoryError}</p> : null}

              <div className="flex flex-col gap-3 tablet:flex-row tablet:justify-end">
                <button type="button" onClick={resetMemoryModal} className="app-pill px-5 text-sm font-semibold">
                  取消
                </button>
                <button
                  type="submit"
                  disabled={!draftMemory.title.trim() || !draftMemory.content.trim() || isSavingMemory}
                  className="min-h-[48px] rounded-full bg-blue-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-55"
                >
                  {isSavingMemory ? "保存中..." : editingMemoryId ? "保存记忆" : "新增记忆"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
