import { useEffect, useMemo, useRef, useState } from "react";

import {
  createMonthlyChapterFacts,
  fetchMonthlyChapters,
  generateMonthlyChapter,
  patchMonthlyChapter,
  publishMonthlyChapter,
  MonthlyChapter,
  MonthlyFactSnapshot,
  Skater,
  fetchSkaters,
} from "../api/client";
import MonthlyFactPreview from "../components/MonthlyFactPreview";
import MonthlyChapterEditor from "../components/MonthlyChapterEditor";
import IslandShareDialog from "../modern/IslandShareDialog";
import { createAdaptiveSharePoster, createShareImagePreview, ShareImagePreview } from "../utils/shareCanvas";

const MONTH_REGEX = /^\d{4}-(0[1-9]|1[0-2])$/;

function currentYearMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "response" in error) {
    const detail = error as unknown as { response?: { data?: { detail?: string } } };
    return detail.response?.data?.detail ?? "操作失败，请稍后重试。";
  }
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

interface Revision {
  label: string;
  value: string;
}

export default function MonthlyChaptersPage() {
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState<string | null>(null);
  const [yearMonth, setYearMonth] = useState<string>(currentYearMonth());
  const [chapters, setChapters] = useState<MonthlyChapter[]>([]);
  const [selectedChapterId, setSelectedChapterId] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [sharePreview, setSharePreview] = useState<ShareImagePreview | null>(null);
  const chapterRequestVersion = useRef(0);

  useEffect(() => {
    let cancelled = false;
    void fetchSkaters()
      .then((items) => {
        if (cancelled) return;
        setSkaters(items);
        setSelectedSkaterId((current) => current ?? items.find((item) => item.is_default)?.id ?? items[0]?.id ?? null);
      })
      .catch((requestError) => {
        if (!cancelled) setError(errorMessage(requestError));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const reloadChapters = async (skaterId: string, month: string) => {
    const requestVersion = ++chapterRequestVersion.current;
    setLoadingList(true);
    setError(null);
    try {
      const list = await fetchMonthlyChapters(skaterId, month);
      if (requestVersion !== chapterRequestVersion.current) return;
      setChapters(list);
      setSelectedChapterId(list[0]?.id ?? null);
    } catch (requestError) {
      if (requestVersion !== chapterRequestVersion.current) return;
      setChapters([]);
      setError(errorMessage(requestError));
    } finally {
      if (requestVersion === chapterRequestVersion.current) setLoadingList(false);
    }
  };

  useEffect(() => {
    if (selectedSkaterId && MONTH_REGEX.test(yearMonth)) {
      void reloadChapters(selectedSkaterId, yearMonth);
    } else {
      setChapters([]);
      setSelectedChapterId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSkaterId, yearMonth]);

  const selectedChapter = useMemo(
    () => chapters.find((chapter) => chapter.id === selectedChapterId) ?? null,
    [chapters, selectedChapterId],
  );

  const revisionOptions: Revision[] = useMemo(
    () =>
      chapters.map((chapter) => ({
        label: `第 ${chapter.revision} 次修订（${statusLabel(chapter.status)}）`,
        value: chapter.id,
      })),
    [chapters],
  );

  const upsert = (updated: MonthlyChapter): MonthlyChapter[] => {
      const next = [...chapters.filter((chapter) => chapter.id !== updated.id), updated];
      next.sort((a, b) => b.revision - a.revision);
      return next;
    };

  const handleGatherFacts = async () => {
    if (!selectedSkaterId || !MONTH_REGEX.test(yearMonth)) {
      setError("请先选择合法的月份（YYYY-MM）。");
      return;
    }
    setWorking(true);
    chapterRequestVersion.current += 1;
    setLoadingList(false);
    setError(null);
    try {
      const chapter = await createMonthlyChapterFacts(selectedSkaterId, yearMonth);
      setChapters((current) => {
        const next = [...current.filter((item) => item.id !== chapter.id), chapter];
        next.sort((a, b) => b.revision - a.revision);
        return next;
      });
      setSelectedChapterId(chapter.id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedChapter) return;
    setWorking(true);
    setError(null);
    try {
      const updated = await generateMonthlyChapter(selectedChapter.id);
      setChapters(upsert(updated));
      setSelectedChapterId(updated.id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  };

  const handleSaveDraft = async (finalText: string) => {
    if (!selectedChapter) return;
    setWorking(true);
    setEditorError(null);
    try {
      const updated = await patchMonthlyChapter(selectedChapter.id, finalText);
      setChapters(upsert(updated));
      setSelectedChapterId(updated.id);
    } catch (requestError) {
      setEditorError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  };

  const handlePublish = async () => {
    if (!selectedChapter) return;
    setWorking(true);
    setEditorError(null);
    try {
      const updated = await publishMonthlyChapter(selectedChapter.id);
      setChapters(upsert(updated));
      setSelectedChapterId(updated.id);
    } catch (requestError) {
      setEditorError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  };

  const monthInvalid = !MONTH_REGEX.test(yearMonth);
  const snapshot = selectedChapter?.fact_snapshot ?? null;
  const handleShareChapter = async () => {
    if (!selectedChapter) return;
    const result = await createAdaptiveSharePoster({
      eyebrow: "Animal Island · 月度故事",
      title: selectedChapter.year_month,
      subtitle: skaters.find((item) => item.id === selectedSkaterId)?.display_name || "成长记录",
      intro: selectedChapter.final_text || selectedChapter.draft_text || "本月故事还在整理中。",
      sections: [{ label: "章节状态", title: statusLabel(selectedChapter.status), body: `第 ${selectedChapter.revision} 次修订`, meta: "每一步都值得被记住" }],
      filename: `monthly-story-${selectedChapter.year_month}.jpg`,
    });
    setSharePreview(createShareImagePreview(result, false));
  };

  return (
    <div className="space-y-6">
      <section className="app-card p-6 tablet:p-8">
        <div className="flex flex-col gap-5 tablet:flex-row tablet:items-end tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Monthly Chapter</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">月度成长章节</h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500">
              按月整理可查的事实，再生成可读叙事。事实不可人工编辑，家长仅编辑最终文字。
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">练习档案</span>
              <select
                aria-label="练习档案"
                value={selectedSkaterId ?? ""}
                onChange={(event) => setSelectedSkaterId(event.target.value || null)}
                className="app-input"
              >
                {skaters.map((skater) => (
                  <option key={skater.id} value={skater.id}>
                    {skater.display_name || skater.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">月份</span>
              <input
                aria-label="月份"
                type="month"
                value={yearMonth}
                onChange={(event) => setYearMonth(event.target.value)}
                className="app-input"
              />
            </label>
          </div>
        </div>
      </section>

      {monthInvalid ? <p className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-700">请选择合法的月份（YYYY-MM）。</p> : null}
      {error ? <p role="alert" className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}

      <section className="app-card p-5">
        <h2 className="text-lg font-semibold text-slate-900">章节修订流程</h2>
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" className="island-button island-button--secondary min-h-[44px] px-5" onClick={() => void handleShareChapter()} disabled={!selectedChapter}>分享月度故事</button>
          <button
            type="button"
            className="app-pill min-h-[44px] px-5 text-sm font-semibold"
            onClick={() => void handleGatherFacts()}
            disabled={!selectedSkaterId || monthInvalid || working}
          >
            整理本月事实
          </button>
          <button
            type="button"
            className="app-pill min-h-[44px] px-5 text-sm font-semibold"
            onClick={() => void handleGenerate()}
            disabled={!selectedChapter || selectedChapter.status === "published" || working}
          >
            生成叙事初稿
          </button>
        </div>

        {revisionOptions.length > 0 ? (
          <label className="mt-4 block space-y-2">
            <span className="text-sm font-medium text-slate-700">选择修订</span>
            <select
              aria-label="选择修订"
              value={selectedChapterId ?? ""}
              onChange={(event) => setSelectedChapterId(event.target.value || null)}
              className="app-input"
            >
              {revisionOptions.map((revision) => (
                <option key={revision.value} value={revision.value}>
                  {revision.label}
                </option>
              ))}
            </select>
          </label>
        ) : loadingList ? (
          <p className="mt-4 text-sm text-slate-500">正在读取已有章节…</p>
        ) : (
          <p className="mt-4 text-sm text-slate-500">本月尚无章节，先“整理本月事实”。</p>
        )}
      </section>

      {snapshot ? <MonthlyFactPreview snapshot={snapshot as MonthlyFactSnapshot} /> : null}

      {selectedChapter ? (
        <MonthlyChapterEditor
          chapter={selectedChapter}
          onSaveDraft={handleSaveDraft}
          onPublish={handlePublish}
          saving={working}
          error={editorError}
        />
      ) : null}
      <IslandShareDialog preview={sharePreview} title="月度故事分享" onClose={() => setSharePreview(null)} />
    </div>
  );
}

function statusLabel(status: string): string {
  switch (status) {
    case "facts_ready":
      return "事实就绪";
    case "generated":
      return "已生成";
    case "published":
      return "已发布";
    case "stale":
      return "已过时";
    default:
      return status;
  }
}
