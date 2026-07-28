import { useEffect, useMemo, useState } from "react";

import {
  AnnualExport,
  AnnualCollection,
  AnnualCollectionPreview,
  AnnualMilestone,
  MonthlyChapter,
  Skater,
  createAnnualCollection,
  createAnnualExport,
  fetchAnnualExport,
  fetchAnnualMilestones,
  fetchAnnualCollections,
  reviseAnnualCollection,
  recycleAnnualCollection,
  restoreAnnualCollection,
  permanentlyDeleteAnnualCollection,
  fetchMonthlyChapters,
  fetchSkaters,
  previewAnnualCollection,
} from "../api/client";
import AnnualChapterPicker from "../components/AnnualChapterPicker";
import AnnualExportStatus from "../components/AnnualExportStatus";
import AnnualMilestonePicker from "../components/AnnualMilestonePicker";
import IslandShareDialog from "../modern/IslandShareDialog";
import { createShareImagePreview, ShareImagePreview } from "../utils/shareCanvas";
import { exportShareDocument } from "../utils/shareExport";
import { Button, Card, Collapse, Input, Select, Table, Tag } from "../modern/AnimalUi";
import { useAppMode } from "../components/AppModeContext";
import ModernConfirmModal from "../modern/ModernConfirmModal";
import { useOnlineStatus } from "../hooks/useOnlineStatus";

function initialYear(): number { return new Date().getFullYear(); }
function message(error: unknown): string {
  if (error && typeof error === "object" && "response" in error) return (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || "操作失败，请稍后重试。";
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

export default function AnnualCollectionPage() {
  const { parentPin, enterParentMode } = useAppMode();
  const online = useOnlineStatus();
  const [confirmation, setConfirmation] = useState<{ title: string; description: string; label: string; run: () => Promise<void> } | null>(null);
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [skaterId, setSkaterId] = useState("");
  const [year, setYear] = useState(initialYear);
  const [chapters, setChapters] = useState<MonthlyChapter[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [milestones, setMilestones] = useState<AnnualMilestone[]>([]);
  const [selectedMilestoneIds, setSelectedMilestoneIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<AnnualCollectionPreview | null>(null);
  const [exportJob, setExportJob] = useState<AnnualExport | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sharePreview, setSharePreview] = useState<ShareImagePreview[]>([]);
  const [collections, setCollections] = useState<AnnualCollection[]>([]);
  const [recycledCollections, setRecycledCollections] = useState<AnnualCollection[]>([]);
  const [editingCollection, setEditingCollection] = useState<AnnualCollection | null>(null);
  const [title, setTitle] = useState("");

  useEffect(() => {
    let active = true;
    void fetchSkaters().then((items) => {
      if (!active) return;
      setSkaters(items);
      setSkaterId(items.find((item) => item.is_default)?.id || items[0]?.id || "");
    }).catch((reason) => active && setError(message(reason)));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!skaterId) return;
    let active = true;
    setPreview(null);
    setSelectedIds([]);
    setSelectedMilestoneIds([]);
    void Promise.all([fetchMonthlyChapters(skaterId), fetchAnnualMilestones(skaterId, year), fetchAnnualCollections(skaterId, year), fetchAnnualCollections(skaterId, year, true)]).then(([items, milestoneItems, collectionItems, recycledItems]) => {
      if (!active) return;
      const published = items.filter((item) => item.status === "published" && item.year_month.startsWith(`${year}-`));
      setChapters(published);
      setSelectedIds(published.map((item) => item.id));
      setMilestones(milestoneItems);
      setSelectedMilestoneIds(milestoneItems.map((item) => item.id));
      setCollections(collectionItems);
      setRecycledCollections(recycledItems);
    }).catch((reason) => active && setError(message(reason)));
    return () => { active = false; };
  }, [skaterId, year]);

  useEffect(() => {
    if (!exportJob || (exportJob.status !== "pending" && exportJob.status !== "processing")) return;
    let active = true;
    const refresh = () => {
      void fetchAnnualExport(exportJob.id).then((next) => active && setExportJob(next)).catch((reason) => active && setError(message(reason)));
    };
    refresh();
    const timer = window.setInterval(refresh, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [exportJob?.id, exportJob?.status]);

  const selectedCount = selectedIds.length;
  const canExport = Boolean(skaterId && selectedCount && !working && online);
  const selectionSummary = useMemo(() => `${selectedCount} 个已发布章节`, [selectedCount]);

  const handlePreview = async () => {
    if (!skaterId || !selectedIds.length) return;
    setWorking(true); setError(null);
    try { setPreview(await previewAnnualCollection(skaterId, year, selectedIds, selectedMilestoneIds)); }
    catch (reason) { setError(message(reason)); }
    finally { setWorking(false); }
  };
  const handleExport = async () => {
    if (!skaterId || !selectedIds.length) return;
    if (!parentPin) { setError("请先验证家长 PIN 后再生成年度报告。"); await enterParentMode(); return; }
    setWorking(true); setError(null);
    try {
      const collection = editingCollection
        ? await reviseAnnualCollection(editingCollection.id, title || editingCollection.title, selectedIds, selectedMilestoneIds, parentPin)
        : await createAnnualCollection(skaterId, year, selectedIds, selectedMilestoneIds, title || undefined, parentPin);
      setEditingCollection(null);
      setTitle("");
      setCollections((current) => [collection, ...current.filter((item) => item.id !== collection.id)]);
      setExportJob(await createAnnualExport(collection.id, false, parentPin));
    } catch (reason) { setError(message(reason)); }
    finally { setWorking(false); }
  };
  const handleRetryExport = async () => {
    if (!exportJob?.collection_id) return;
    if (!parentPin) { setError("请先验证家长 PIN 后再重新生成。"); await enterParentMode(); return; }
    setWorking(true); setError(null);
    try { setExportJob(await createAnnualExport(exportJob.collection_id, true, parentPin)); }
    catch (reason) { setError(message(reason)); }
    finally { setWorking(false); }
  };

  const loadForEdit = (collection: AnnualCollection) => {
    setEditingCollection(collection); setTitle(collection.title); setSelectedIds(collection.selected_chapter_ids); setSelectedMilestoneIds(collection.selected_milestone_ids);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const reloadCollections = async () => {
    if (!skaterId) return;
    const [active, recycled] = await Promise.all([fetchAnnualCollections(skaterId, year), fetchAnnualCollections(skaterId, year, true)]);
    setCollections(active); setRecycledCollections(recycled);
  };

  const recycleCollection = async (item: AnnualCollection) => {
    if (!parentPin) { setError("请先验证家长 PIN 后再删除。"); await enterParentMode(); return; }
    setWorking(true); try { await recycleAnnualCollection(item.id, parentPin); await reloadCollections(); } catch (reason) { setError(message(reason)); } finally { setWorking(false); }
  };

  const restoreCollection = async (id: string) => { if (!parentPin) { setError("请先验证家长 PIN 后再恢复。"); await enterParentMode(); return; } setWorking(true); try { await restoreAnnualCollection(id, parentPin); await reloadCollections(); } catch (reason) { setError(message(reason)); } finally { setWorking(false); } };
  const permanentlyDeleteCollection = async (id: string) => {
    if (!parentPin) { setError("请先验证家长 PIN 后再永久删除。"); await enterParentMode(); return; }
    setWorking(true); try { await permanentlyDeleteAnnualCollection(id, parentPin); await reloadCollections(); } catch (reason) { setError(message(reason)); } finally { setWorking(false); }
  };

  const confirmRecycle = (item: AnnualCollection) => setConfirmation({ title: "移入年度回收站", description: `“${item.title}”及已有 PDF 会保留，可随时恢复。`, label: "移入回收站", run: () => recycleCollection(item) });
  const confirmPermanentDelete = (item: AnnualCollection) => setConfirmation({ title: "永久删除年度报告", description: `“${item.title}”及其 PDF 文件将永久删除且无法恢复。`, label: "永久删除", run: () => permanentlyDeleteCollection(item.id) });

  const tableRows = collections.map((item) => ({ ...item, _collection: item }));
  const historyColumns = [
    { title: "报告", dataIndex: "title", render: (_: unknown, row: Record<string, unknown>) => { const item = row._collection as AnnualCollection; return <div><strong>{item.title}</strong><p className="text-sm text-slate-500">{item.selected_chapter_ids.length} 个月报 · {item.selected_milestone_ids.length} 个里程碑</p></div>; } },
    { title: "版本", dataIndex: "revision", render: (_: unknown, row: Record<string, unknown>) => { const item = row._collection as AnnualCollection; return <Tag color="app-teal">第 {item.revision} 版</Tag>; } },
    { title: "状态", dataIndex: "status", render: (_: unknown, row: Record<string, unknown>) => (row._collection as AnnualCollection).status === "exported" ? "已导出" : "可生成" },
    { title: "修改时间", dataIndex: "updated_at", render: (_: unknown, row: Record<string, unknown>) => new Date((row._collection as AnnualCollection).updated_at).toLocaleDateString("zh-CN") },
    { title: "操作", render: (_: unknown, row: Record<string, unknown>) => { const item = row._collection as AnnualCollection; return <div className="flex flex-wrap gap-2"><Button onClick={() => loadForEdit(item)} disabled={!online}>修改为新版本</Button><Button danger onClick={() => confirmRecycle(item)} disabled={working || !online}>移入回收站</Button></div>; } },
  ];

  const handleShareAnnual = async () => {
    if (!exportJob || exportJob.status !== "completed") return;
    const skater = skaters.find((item) => item.id === skaterId);
    const highlights = chapters.slice(0, 4).map((chapter) => `${chapter.year_month}: ${chapter.final_text || chapter.draft_text || "月度记录"}`).join("\n");
    const result = await exportShareDocument({
      eyebrow: "Animal Island · 年度合集",
      title: `${year} 年成长合集`,
      subtitle: skater?.display_name || skater?.name || "训练档案",
      intro: `收录 ${selectedCount} 个月度章节 · ${selectedMilestoneIds.length} 个里程碑`,
      sections: [{ label: "年度亮点", title: "这一年的小岛足迹", body: highlights || "每一次练习都值得被记录。", meta: "PDF 完整合集可下载分享" }],
      filename: `annual-collection-${year}.jpg`,
    });
    setSharePreview(result.pages.map((page) => createShareImagePreview(page, false)));
  };

  return (
    <div className="space-y-6">
      <section className="app-card p-6 tablet:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Annual Collection</p>
        <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">年度成长合集</h1>
        <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500">从已发布的月度章节整理为可下载 PDF。生成结果保留快照来源，可随时重新生成。</p>
        <div className="mt-5 flex flex-wrap gap-3">
          <label className="space-y-1"><span className="block text-sm font-medium text-slate-700">练习档案</span><Select aria-label="练习档案" value={skaterId} onChange={setSkaterId} options={skaters.map((item) => ({ key: item.id, label: item.display_name || item.name }))} /></label>
          <label className="space-y-1"><span className="block text-sm font-medium text-slate-700">年份</span><Input aria-label="年份" className="w-28" type="number" min="2000" max="2100" value={year} onChange={(event) => setYear(Number(event.target.value) || initialYear())} /></label>
          <label className="min-w-[240px] flex-1 space-y-1"><span className="block text-sm font-medium text-slate-700">年报标题</span><Input aria-label="年报标题" className="w-full" value={title} onChange={(event) => setTitle(event.target.value)} placeholder={`${year} 年度成长合集`} /></label>
        </div>
      </section>
      {error ? <p role="alert" className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}
      {!online ? <p role="status" className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">当前离线：可以查看已缓存报告，编辑、删除、恢复和 PDF 操作暂不可用。</p> : null}
      <section className="app-card p-5 tablet:p-6"><AnnualChapterPicker chapters={chapters} selectedIds={selectedIds} onChange={setSelectedIds} /><AnnualMilestonePicker milestones={milestones} selectedIds={selectedMilestoneIds} onChange={setSelectedMilestoneIds} /></section>
      <section className="app-card flex flex-wrap items-center gap-3 p-5"><p className="mr-auto text-sm text-slate-600">已选择 {selectionSummary}{editingCollection ? ` · 正在编辑第 ${editingCollection.revision} 版` : ""}</p><Button disabled={!canExport} onClick={() => void handlePreview()}>预览合集</Button><Button type="primary" loading={working} disabled={!canExport} onClick={() => void handleExport()}>{editingCollection ? "保存新版本并生成 PDF" : "生成年度 PDF"}</Button></section>
      {preview ? <section className="rounded-2xl bg-blue-50 px-5 py-4 text-sm leading-7 text-blue-800">预览：{preview.coverage.published_chapter_count} 个已发布章节，其中 {preview.coverage.text_only_chapter_count} 个将以文字版呈现。</section> : null}
      <AnnualExportStatus exportJob={exportJob} onRetry={() => void handleRetryExport()} onRegenerate={() => void handleRetryExport()} retrying={working} />
      <Collapse question={`年度版本历史（${collections.length}）`} defaultExpanded answer={<>{collections.length ? <><div className="hidden tablet:block"><Table columns={historyColumns} dataSource={tableRows} rowKey="id" striped /></div><div className="space-y-3 tablet:hidden">{collections.map((item) => <Card key={item.id} pattern="default"><div className="space-y-3"><div><strong>{item.title}</strong><Tag color="app-teal">第 {item.revision} 版</Tag><p className="text-sm">{item.selected_chapter_ids.length} 个月报 · {item.selected_milestone_ids.length} 个里程碑</p></div><div className="flex flex-wrap gap-2"><Button onClick={() => loadForEdit(item)} disabled={!online}>修改为新版本</Button><Button danger onClick={() => confirmRecycle(item)} disabled={working || !online}>移入回收站</Button></div></div></Card>)}</div></> : <p>暂无年度版本。</p>}</>} />
      <Collapse question={`年度回收站（${recycledCollections.length}）`} answer={<div className="space-y-3">{recycledCollections.length ? recycledCollections.map((item) => <Card key={item.id} pattern="app-red"><div className="flex flex-wrap items-center justify-between gap-3"><strong>{item.title} · 第 {item.revision} 版</strong><div className="flex gap-2"><Button onClick={() => void restoreCollection(item.id)} disabled={working || !online}>恢复</Button><Button danger onClick={() => confirmPermanentDelete(item)} disabled={working || !online}>永久删除</Button></div></div></Card>) : <p>回收站为空。</p>}</div>} />
      {exportJob?.status === "completed" ? <Button type="primary" onClick={() => void handleShareAnnual()}>分享年度合集</Button> : null}
      <IslandShareDialog
        preview={null}
        previews={sharePreview}
        title="年度合集分享"
        onClose={() => setSharePreview([])}
        extraActions={exportJob?.status === "completed" ? <a className="island-button island-button--secondary" href={`/api/annual/exports/${exportJob.id}/download`} download={`annual-collection-${year}.pdf`}>下载 PDF</a> : null}
      />
      <ModernConfirmModal open={Boolean(confirmation)} title={confirmation?.title || "确认操作"} description={confirmation?.description || ""} confirmLabel={confirmation?.label || "确认"} danger loading={working} onCancel={() => setConfirmation(null)} onConfirm={() => { const action = confirmation?.run; if (!action) return; void action().finally(() => setConfirmation(null)); }} />
    </div>
  );
}
