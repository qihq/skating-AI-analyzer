import { useEffect, useMemo, useState } from "react";

import {
  AnnualExport,
  AnnualCollectionPreview,
  AnnualMilestone,
  MonthlyChapter,
  Skater,
  createAnnualCollection,
  createAnnualExport,
  fetchAnnualExport,
  fetchAnnualMilestones,
  fetchMonthlyChapters,
  fetchSkaters,
  previewAnnualCollection,
} from "../api/client";
import AnnualChapterPicker from "../components/AnnualChapterPicker";
import AnnualExportStatus from "../components/AnnualExportStatus";
import AnnualMilestonePicker from "../components/AnnualMilestonePicker";

function initialYear(): number { return new Date().getFullYear(); }
function message(error: unknown): string {
  if (error && typeof error === "object" && "response" in error) return (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || "操作失败，请稍后重试。";
  return error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

export default function AnnualCollectionPage() {
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
    void Promise.all([fetchMonthlyChapters(skaterId), fetchAnnualMilestones(skaterId, year)]).then(([items, milestoneItems]) => {
      if (!active) return;
      const published = items.filter((item) => item.status === "published" && item.year_month.startsWith(`${year}-`));
      setChapters(published);
      setSelectedIds(published.map((item) => item.id));
      setMilestones(milestoneItems);
      setSelectedMilestoneIds(milestoneItems.map((item) => item.id));
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
  const canExport = Boolean(skaterId && selectedCount && !working);
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
    setWorking(true); setError(null);
    try {
      const collection = await createAnnualCollection(skaterId, year, selectedIds, selectedMilestoneIds);
      setExportJob(await createAnnualExport(collection.id));
    } catch (reason) { setError(message(reason)); }
    finally { setWorking(false); }
  };
  const handleRetryExport = async () => {
    if (!exportJob?.collection_id) return;
    setWorking(true); setError(null);
    try { setExportJob(await createAnnualExport(exportJob.collection_id)); }
    catch (reason) { setError(message(reason)); }
    finally { setWorking(false); }
  };

  return (
    <div className="space-y-6">
      <section className="app-card p-6 tablet:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Annual Collection</p>
        <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">年度成长合集</h1>
        <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500">从已发布的月度章节整理为可下载 PDF。生成结果保留快照来源，可随时重新生成。</p>
        <div className="mt-5 flex flex-wrap gap-3">
          <label className="space-y-1"><span className="block text-sm font-medium text-slate-700">练习档案</span><select aria-label="练习档案" value={skaterId} onChange={(event) => setSkaterId(event.target.value)} className="app-input">{skaters.map((item) => <option key={item.id} value={item.id}>{item.display_name || item.name}</option>)}</select></label>
          <label className="space-y-1"><span className="block text-sm font-medium text-slate-700">年份</span><input aria-label="年份" className="app-input w-28" type="number" min="2000" max="2100" value={year} onChange={(event) => setYear(Number(event.target.value) || initialYear())} /></label>
        </div>
      </section>
      {error ? <p role="alert" className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p> : null}
      <section className="app-card p-5 tablet:p-6"><AnnualChapterPicker chapters={chapters} selectedIds={selectedIds} onChange={setSelectedIds} /><AnnualMilestonePicker milestones={milestones} selectedIds={selectedMilestoneIds} onChange={setSelectedMilestoneIds} /></section>
      <section className="app-card flex flex-wrap items-center gap-3 p-5"><p className="mr-auto text-sm text-slate-600">已选择 {selectionSummary}</p><button type="button" className="app-pill min-h-[44px] px-5 font-semibold" disabled={!canExport} onClick={() => void handlePreview()}>预览合集</button><button type="button" className="app-pill min-h-[44px] px-5 font-semibold" disabled={!canExport} onClick={() => void handleExport()}>生成年度 PDF</button></section>
      {preview ? <section className="rounded-2xl bg-blue-50 px-5 py-4 text-sm leading-7 text-blue-800">预览：{preview.coverage.published_chapter_count} 个已发布章节，其中 {preview.coverage.text_only_chapter_count} 个将以文字版呈现。</section> : null}
      <AnnualExportStatus exportJob={exportJob} onRetry={() => void handleRetryExport()} retrying={working} />
    </div>
  );
}
