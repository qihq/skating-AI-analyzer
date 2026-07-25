import { useEffect, useMemo, useRef, useState } from "react";

import {
  createMonthlyChapterFacts,
  fetchMonthlyChapters,
  generateMonthlyChapter,
  patchMonthlyChapter,
  reviseMonthlyChapter,
  recycleMonthlyChapter,
  restoreMonthlyChapter,
  permanentlyDeleteMonthlyChapter,
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
import { Button, Card, Collapse, Input, Select, Tag } from "../modern/AnimalUi";
import { useAppMode } from "../components/AppModeContext";
import ModernConfirmModal from "../modern/ModernConfirmModal";
import { useOnlineStatus } from "../hooks/useOnlineStatus";

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
  const { parentPin, enterParentMode } = useAppMode();
  const online = useOnlineStatus();
  const [confirmation, setConfirmation] = useState<{ title: string; description: string; label: string; danger?: boolean; run: () => Promise<void> } | null>(null);
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
  const [recycled, setRecycled] = useState<MonthlyChapter[]>([]);
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
      const [list, recycledList] = await Promise.all([fetchMonthlyChapters(skaterId, month), fetchMonthlyChapters(skaterId, month, true)]);
      if (requestVersion !== chapterRequestVersion.current) return;
      setChapters(list);
      setRecycled(recycledList);
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
    if (!parentPin) { setError("请先验证家长 PIN 后再整理月报。"); await enterParentMode(); return; }
    if (!selectedSkaterId || !MONTH_REGEX.test(yearMonth)) {
      setError("请先选择合法的月份（YYYY-MM）。");
      return;
    }
    setWorking(true);
    chapterRequestVersion.current += 1;
    setLoadingList(false);
    setError(null);
    try {
      const chapter = await createMonthlyChapterFacts(selectedSkaterId, yearMonth, parentPin);
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
    if (!parentPin) { setError("请先验证家长 PIN 后再生成月报。"); await enterParentMode(); return; }
    setWorking(true);
    setError(null);
    try {
      const updated = await generateMonthlyChapter(selectedChapter.id, parentPin);
      setChapters(upsert(updated));
      setSelectedChapterId(updated.id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setWorking(false);
    }
  };

  const handleSaveDraft = async (finalText: string, title: string) => {
    if (!selectedChapter) return;
    if (!parentPin) { setEditorError("请先验证家长 PIN 后再保存。"); await enterParentMode(); return; }
    setWorking(true);
    setEditorError(null);
    try {
      const updated = selectedChapter.status === "published"
        ? await reviseMonthlyChapter(selectedChapter.id, finalText, title, parentPin)
        : await patchMonthlyChapter(selectedChapter.id, finalText, title, parentPin);
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
    if (!parentPin) { setEditorError("请先验证家长 PIN 后再发布。"); await enterParentMode(); return; }
    setWorking(true);
    setEditorError(null);
    try {
      const updated = await publishMonthlyChapter(selectedChapter.id, parentPin);
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

  const handleRecycle = async () => {
    if (!selectedChapter) return;
    if (!parentPin) { setError("请先验证家长 PIN 后再删除。"); await enterParentMode(); return; }
    setWorking(true);
    try { await recycleMonthlyChapter(selectedChapter.id, parentPin); if (selectedSkaterId) await reloadChapters(selectedSkaterId, yearMonth); }
    catch (requestError) { setError(errorMessage(requestError)); } finally { setWorking(false); }
  };

  const handleRestore = async (id: string) => {
    if (!parentPin) { setError("请先验证家长 PIN 后再恢复。"); await enterParentMode(); return; }
    setWorking(true); try { await restoreMonthlyChapter(id, parentPin); if (selectedSkaterId) await reloadChapters(selectedSkaterId, yearMonth); }
    catch (requestError) { setError(errorMessage(requestError)); } finally { setWorking(false); }
  };

  const handlePermanentDelete = async (id: string) => {
    if (!parentPin) { setError("请先验证家长 PIN 后再永久删除。"); await enterParentMode(); return; }
    setWorking(true); try { await permanentlyDeleteMonthlyChapter(id, parentPin); if (selectedSkaterId) await reloadChapters(selectedSkaterId, yearMonth); }
    catch (requestError) { setError(errorMessage(requestError)); } finally { setWorking(false); }
  };

  const confirmRecycle = () => {
    if (!selectedChapter) return;
    setConfirmation({ title: "移入回收站", description: `“${selectedChapter.title}”删除后仍可恢复。`, label: "移入回收站", danger: true, run: handleRecycle });
  };

  const confirmPermanentDelete = (id: string) => setConfirmation({ title: "永久删除月报", description: "永久删除后无法恢复，请确认确实不再需要这个版本。", label: "永久删除", danger: true, run: () => handlePermanentDelete(id) });

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
              <Select
                aria-label="练习档案"
                value={selectedSkaterId ?? ""}
                onChange={(value) => setSelectedSkaterId(value || null)}
                options={skaters.map((skater) => ({ key: skater.id, label: skater.display_name || skater.name }))}
              />
            </label>
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">月份</span>
              <Input
                aria-label="月份"
                type="month"
                value={yearMonth}
                onChange={(event) => setYearMonth(event.target.value)}
              />
            </label>
          </div>
        </div>
      </section>

      {monthInvalid ? <p className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-700">请选择合法的月份（YYYY-MM）。</p> : null}
      {!online ? <p role="status" className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">当前离线：可以查看已缓存内容，编辑、删除、恢复和生成操作暂不可用。</p> : null}
      {error ? <p role="alert" className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}

      <section className="app-card p-5">
        <h2 className="text-lg font-semibold text-slate-900">章节修订流程</h2>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => void handleShareChapter()} disabled={!selectedChapter}>分享月度故事</Button>
          <Button
            onClick={() => void handleGatherFacts()}
            disabled={!selectedSkaterId || monthInvalid || working || !online}
            loading={working}
          >
            整理本月事实
          </Button>
          <Button
            type="primary"
            onClick={() => void handleGenerate()}
            disabled={!selectedChapter || selectedChapter.status === "published" || working || !online}
            loading={working}
          >
            生成叙事初稿
          </Button>
        </div>

        {revisionOptions.length > 0 ? (
          <label className="mt-4 block space-y-2">
            <span className="text-sm font-medium text-slate-700">选择修订</span>
            <Select
              aria-label="选择修订"
              value={selectedChapterId ?? ""}
              onChange={(value) => setSelectedChapterId(value || null)}
              options={revisionOptions.map((revision) => ({ key: revision.value, label: revision.label }))}
            />
          </label>
        ) : loadingList ? (
          <p className="mt-4 text-sm text-slate-500">正在读取已有章节…</p>
        ) : (
          <p className="mt-4 text-sm text-slate-500">本月尚无章节，先“整理本月事实”。</p>
        )}
      </section>

      {snapshot ? <MonthlyFactPreview snapshot={snapshot as MonthlyFactSnapshot} /> : null}

      {selectedChapter ? (
        <>
          <MonthlyChapterEditor chapter={selectedChapter} onSaveDraft={handleSaveDraft} onPublish={handlePublish} saving={working} error={editorError} />
          <Card pattern="app-red" className="mt-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><strong>管理这个版本</strong><p className="text-sm">删除后可在本月回收站恢复。</p></div><Button danger onClick={confirmRecycle} disabled={working || !online}>移入回收站</Button></div></Card>
        </>
      ) : null}
      <Collapse question={`本月回收站（${recycled.length}）`} answer={recycled.length ? <div className="space-y-3">{recycled.map((item) => <Card key={item.id} pattern="default"><div className="flex flex-wrap items-center justify-between gap-3"><div><strong>{item.title}</strong><Tag color="brown">第 {item.revision} 版</Tag></div><div className="flex gap-2"><Button onClick={() => void handleRestore(item.id)} disabled={working || !online}>恢复</Button><Button danger onClick={() => confirmPermanentDelete(item.id)} disabled={working || !online}>永久删除</Button></div></div></Card>)}</div> : <p>回收站为空。</p>} />
      <IslandShareDialog preview={sharePreview} title="月度故事分享" onClose={() => setSharePreview(null)} />
      <ModernConfirmModal open={Boolean(confirmation)} title={confirmation?.title || "确认操作"} description={confirmation?.description || ""} confirmLabel={confirmation?.label || "确认"} danger={confirmation?.danger} loading={working} onCancel={() => setConfirmation(null)} onConfirm={() => { const action = confirmation?.run; if (!action) return; void action().finally(() => setConfirmation(null)); }} />
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
