import axios from "axios";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AnalysisCompareResponse,
  AnalysisComparisonDetail,
  CompareVideoSide,
  createAnalysisComparison,
  fetchAnalysisMedia,
  fetchAnalysisComparison,
  retryAnalysisComparison,
  type MediaManifest,
} from "../api/client";
import { IceMediaPlayer, type IceMediaPlayerHandle } from "../media/IceMediaPlayer";
import { useSynchronizedMediaGroup } from "../media/useSynchronizedMediaGroup";
import ReportCard from "../components/ReportCard";
import { parseApiDate } from "../utils/datetime";
import { createShareImagePreview, ShareImagePreview } from "../utils/shareCanvas";
import { exportShareDocument } from "../utils/shareExport";
import IslandShareDialog from "../modern/IslandShareDialog";
import SubmitButton from "../modern/SubmitButton";
import { useAnalysisExperiences } from "../analysis-v2/useAnalysisExperiences";
import { canCompareExperiences, presentAnalysisExperience, presentComparison, type FamilyComparisonView } from "../analysis-v2/presenter";

const SPEED_OPTIONS = [0.25, 0.5, 1] as const;

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(parseApiDate(dateString));
}

function formatShortDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(parseApiDate(dateString));
}

function formatValue(value: number | null | undefined, unit?: string | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  const text = Number.isInteger(value) ? String(value) : value.toFixed(Math.abs(value) < 10 ? 2 : 1);
  return `${text}${unit ?? ""}`;
}

function signedValue(value: number | null | undefined, unit?: string | null) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatValue(value, unit)}`;
}

function trendClass(delta: number | null) {
  if (typeof delta !== "number") {
    return "text-slate-500";
  }
  if (delta > 0) {
    return "text-emerald-600";
  }
  if (delta < 0) {
    return "text-rose-600";
  }
  return "text-slate-600";
}

function scoreTone(delta: number) {
  if (delta > 0) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (delta < 0) {
    return "border-rose-200 bg-rose-50 text-rose-600";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}

function normalizeShareSnippet(value: string | null | undefined, fallback: string, maxLength = 92) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!text) {
    return fallback;
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}â€¦` : text;
}

function comparisonStatusLabel(status: string) {
  if (status === "pending") {
    return "ç­‰å¾…ç”Ÿæˆ";
  }
  if (status === "processing") {
    return "ç”Ÿæˆä¸­";
  }
  if (status === "completed") {
    return "å·²å®Œæˆ";
  }
  if (status === "failed") {
    return "ç”Ÿæˆå¤±è´¥";
  }
  return status;
}

function comparisonStatusTone(status: string) {
  if (status === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-600";
  }
  if (status === "processing") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function getRequestErrorMessage(requestError: unknown, fallback: string) {
  const detail = axios.isAxiosError(requestError) ? requestError.response?.data?.detail : null;
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String(detail.message);
  }
  return fallback;
}

function VideoPane({ title, side, manifest, playerRef }: { title: string; side: CompareVideoSide; manifest: MediaManifest | null; playerRef: React.RefObject<IceMediaPlayerHandle | null> }) {
  return <div className="min-w-0 overflow-hidden rounded-[22px] border border-slate-200 bg-white">
    <div className="flex min-h-[68px] items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
      <div><p className="text-xs uppercase tracking-[0.24em] text-blue-500">{title}</p><p className="mt-1 text-sm text-slate-500">动作窗口 {formatValue(side.action_window_start, "s")} - {formatValue(side.action_window_end, "s")}</p></div>
      {side.is_slow_motion ? <span className="shrink-0 rounded-full bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-600">慢动作 {Math.round(side.source_fps ?? 0)}fps</span> : null}
    </div>
    {side.available && side.video_url ? <IceMediaPlayer ref={playerRef} manifest={manifest} fallbackSrc={side.video_url} /> : <div className="flex aspect-video items-center justify-center bg-slate-950 px-6 text-center text-sm leading-7 text-slate-400">{side.missing_reason ?? "原视频不可用，仍可查看关键帧与量化对比。"}</div>}
  </div>;
}

function SyncedVideoSection({ data, comparisonView }: { data: AnalysisCompareResponse; comparisonView: FamilyComparisonView | null }) {
  const beforeRef = useRef<IceMediaPlayerHandle | null>(null);
  const afterRef = useRef<IceMediaPlayerHandle | null>(null);
  const videoCompare = data.video_compare;
  const [manifests, setManifests] = useState<{ before: MediaManifest | null; after: MediaManifest | null }>({ before: null, after: null });
  const fallbackSide: CompareVideoSide = { analysis_id: "", video_url: null, available: false, missing_reason: null, action_window_start: null, action_window_end: null, action_window_duration: null, sync_start: null, sync_duration: null, is_slow_motion: false, source_fps: null };
  const group = useSynchronizedMediaGroup(beforeRef, afterRef, videoCompare?.before ?? fallbackSide, videoCompare?.after ?? fallbackSide);
  useEffect(() => {
    if (!videoCompare) return;
    let cancelled = false;
    void Promise.all([fetchAnalysisMedia(videoCompare.before.analysis_id), fetchAnalysisMedia(videoCompare.after.analysis_id)])
      .then(([before, after]) => { if (!cancelled) setManifests({ before, after }); })
      .catch(() => { if (!cancelled) setManifests({ before: null, after: null }); });
    return () => { cancelled = true; };
  }, [videoCompare]);
  if (!videoCompare) return null;

  return <ReportCard title="同步回放" eyebrow="Video Sync">
    <div className="grid gap-4 lg:grid-cols-2">
      <VideoPane title="之前" side={videoCompare.before} manifest={manifests.before} playerRef={beforeRef} />
      <VideoPane title="现在" side={videoCompare.after} manifest={manifests.after} playerRef={afterRef} />
    </div>
    <div className="mt-4 rounded-[22px] border border-slate-200 bg-slate-50 p-3 tablet:p-4">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void group.togglePlayback()} className="min-h-[44px] rounded-full bg-blue-500 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-600">{group.isPlaying ? "暂停" : "同步播放"}</button>
          <button type="button" onClick={() => group.seekRelative(0)} className="pill-link">跳到动作开始</button>
          <span className="rounded-full border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-500">全程静音</span>
        </div>
        <div className="flex w-fit rounded-full border border-slate-200 bg-white p-1">
          {SPEED_OPTIONS.map((option) => <button key={option} type="button" onClick={() => group.setSpeed(option)} className={`min-h-[34px] rounded-full px-3 text-xs font-semibold transition ${group.speed === option ? "bg-blue-500 text-white" : "text-slate-500 hover:bg-slate-100"}`}>{option}x</button>)}
        </div>
      </div>
      {comparisonView?.momentChips.length ? <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-200 pt-3">{comparisonView.momentChips.map((item) => <button key={item.key} type="button" onClick={() => group.seekTimestamps({ beforeTimestamp: item.beforePtsSec, afterTimestamp: item.afterPtsSec })} className="pill-link">{item.label}</button>)}</div> : null}
    </div>
  </ReportCard>;
}

function HeroSummary({ data, actionLabel, compatibilityReason, comparisonView }: { data: AnalysisCompareResponse; actionLabel?: string | null; compatibilityReason?: string | null; comparisonView?: FamilyComparisonView | null }) {
  const before = data.analysis_a;
  const after = data.analysis_b;
  const actionName = actionLabel || "动作对比";
  return (
    <header className="app-card overflow-hidden p-6 tablet:p-8">
      <div className="grid gap-6 lg:grid-cols-[1fr_260px] lg:items-center">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Compare Review</p>
          <h1 className="mt-3 text-3xl font-semibold text-slate-900 sm:text-4xl">{actionName} è¿›æ­¥å¤ç›˜</h1>
          <div className="mt-4 flex flex-wrap gap-3 text-sm text-slate-500">
            <span>{before.skater_name ?? after.skater_name ?? "å°è¿åŠ¨å‘˜"}</span>
            <span>{formatDate(before.created_at)} â†’ {formatDate(after.created_at)}</span>
            <span>{comparisonView?.compatible ? "同源证据对比" : "比较状态"}</span>
          </div>
          {comparisonView?.compatible ? <p className="mt-5 max-w-4xl text-base leading-8 text-slate-600">本页只显示两份复盘中已确认、可追踪且定义兼容的共同证据。</p> : null}
          {compatibilityReason ? <div className="mt-3 rounded-[22px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-7 text-rose-700">{compatibilityReason}</div> : null}
        </div>
        <div className={`rounded-[28px] border p-5 text-center ${scoreTone(comparisonView?.scoreDelta ?? 0)}`}>
          <p className="text-sm uppercase tracking-[0.24em] opacity-80">è¯„åˆ†å˜åŒ–</p>
          <p className="mt-3 text-5xl font-semibold">
            {comparisonView?.scoreDelta == null ? "--" : `${comparisonView.scoreDelta >= 0 ? "+" : ""}${comparisonView.scoreDelta}`}
          </p>
          <p className="mt-3 text-sm opacity-80">
            {comparisonView?.scoreBefore ?? "--"} â†’ {comparisonView?.scoreAfter ?? "--"}
          </p>
        </div>
      </div>
    </header>
  );
}

function createFamilyCompareShareDocument(data: AnalysisCompareResponse, view: FamilyComparisonView, actionLabel: string | null) {
  const before = data.analysis_a;
  const after = data.analysis_b;
  const first = view.deltas[0];
  return {
    eyebrow: "冰宝对比分享",
    title: `${normalizeShareSnippet(actionLabel, "滑冰对比复盘", 24)} 进步复盘`,
    subtitle: `${before.skater_name ?? after.skater_name ?? "小运动员"} · ${formatShortDate(before.created_at)} → ${formatShortDate(after.created_at)}`,
    intro: view.compatible ? "本次分享仅解释两份复盘中已确认、定义兼容的共同证据。" : (view.reason ?? "当前没有足够的同源证据可计算技术变化。"),
    sections: [
      { label: "主要变化", title: first ? `${first.label} ${signedValue(first.delta, first.unit)}` : "暂无已确认的共同量化变化", color: "#059669", bg: "#ECFDF5" },
      { label: "综合评分", title: view.scoreDelta == null ? "暂不可比较" : `${view.scoreBefore ?? "--"} → ${view.scoreAfter ?? "--"}（${view.scoreDelta >= 0 ? "+" : ""}${view.scoreDelta}）`, color: "#2563EB", bg: "#EFF6FF" },
      { label: "证据覆盖", title: view.excludedCount ? `${view.excludedCount} 项因冲突、不确定或定义不兼容而排除` : "所有展示内容均来自已确认共同证据", color: "#7C3AED", bg: "#F5F3FF" },
    ],
    footer: "对比结论仅供复盘参考，请在教练或家长陪同下完成训练。",
    filename: `icebuddy-compare-${after.id.slice(0, 8)}.jpg`,
  };
}

function FamilyComparisonSection({ view }: { view: FamilyComparisonView }) {
  return (
    <ReportCard title="同源证据变化" eyebrow="Confirmed facts">
      <div className="space-y-4">
        <div className={`rounded-[22px] border px-4 py-3 text-sm leading-7 ${view.compatible ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`} role="status">
          {view.compatible ? "仅展示两份复盘中已确认且定义兼容的共同事实。" : (view.reason ?? "当前没有可安全比较的共同事实。")}
        </div>
        {view.scoreDelta != null ? <div className="rounded-[22px] border border-slate-200 bg-slate-50 p-4"><p className="text-sm font-semibold text-slate-900">综合评分</p><p className="mt-2 text-2xl font-semibold text-slate-900">{view.scoreBefore} → {view.scoreAfter} <span className={trendClass(view.scoreDelta)}>{view.scoreDelta >= 0 ? "+" : ""}{view.scoreDelta}</span></p></div> : null}
        {view.deltas.length ? <div className="grid gap-3 tablet:grid-cols-2">{view.deltas.map((item) => <article key={`${item.claimType}:${item.compatibilityGroup ?? ""}`} className="rounded-[22px] border border-slate-200 bg-white p-4"><div className="flex items-center justify-between gap-3"><p className="text-sm font-semibold text-slate-900">{item.label}</p><span className={trendClass(item.delta)}>{item.delta >= 0 ? "+" : ""}{formatValue(item.delta, item.unit)}</span></div><p className="mt-2 text-xs text-slate-500">{formatValue(item.before, item.unit)} → {formatValue(item.after, item.unit)}</p></article>)}</div> : <p className="rounded-[22px] border border-dashed border-slate-300 p-4 text-sm text-slate-500">没有可比较的已确认量化事实。</p>}
        {view.excludedCount ? <p className="text-xs leading-6 text-slate-500">{view.excludedCount} 项因未知、冲突或定义不兼容而排除，未计算无效差值。</p> : null}
      </div>
    </ReportCard>
  );
}

export default function ComparePage() {
  const { id_a, id_b, comparison_id } = useParams<{ id_a?: string; id_b?: string; comparison_id?: string }>();
  const navigate = useNavigate();
  const [comparison, setComparison] = useState<AnalysisComparisonDetail | null>(null);
  const [data, setData] = useState<AnalysisCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRetrying, setIsRetrying] = useState(false);
  const [pollVersion, setPollVersion] = useState(0);
  const [isSharing, setIsSharing] = useState(false);
  const [shareImagePreview, setShareImagePreview] = useState<ShareImagePreview[]>([]);
  const experienceIds = useMemo(() => data ? [data.analysis_a.id, data.analysis_b.id] : [], [data]);
  const { experiences: experienceById, loading: experiencesLoading } = useAnalysisExperiences(experienceIds);
  const leftExperience = data ? experienceById[data.analysis_a.id] : null;
  const rightExperience = data ? experienceById[data.analysis_b.id] : null;
  const compatibility = useMemo(() => {
    if (!leftExperience || !rightExperience) return null;
    return canCompareExperiences(leftExperience, rightExperience);
  }, [leftExperience, rightExperience]);
  const comparisonView = useMemo(() => {
    if (!leftExperience || !rightExperience) return null;
    return presentComparison(leftExperience, rightExperience);
  }, [leftExperience, rightExperience]);
  const presentedActionLabel = leftExperience && rightExperience
    ? `${presentAnalysisExperience(leftExperience).selectedEvent?.label ?? "复盘"} → ${presentAnalysisExperience(rightExperience).selectedEvent?.label ?? "复盘"}`
    : null;

  useEffect(() => {
    if (comparison_id) {
      return;
    }
    if (!id_a || !id_b) {
      setError("æ— æ•ˆçš„å¯¹æ¯”å‚æ•°ã€‚");
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    const createComparison = async () => {
      setIsLoading(true);
      try {
        const created = await createAnalysisComparison(id_a, id_b);
        if (!cancelled) {
          navigate(`/compare/results/${created.id}`, { replace: true });
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(getRequestErrorMessage(requestError, "å¯¹æ¯”ä»»åŠ¡åˆ›å»ºå¤±è´¥ï¼Œè¯·è¿”å›žåŽ†å²è®°å½•é¡µé‡è¯•ã€‚"));
          setIsLoading(false);
        }
      }
    };

    void createComparison();
    return () => {
      cancelled = true;
    };
  }, [comparison_id, id_a, id_b, navigate]);

  useEffect(() => {
    if (!comparison_id) {
      return;
    }

    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      try {
        const detail = await fetchAnalysisComparison(comparison_id);
        if (cancelled) {
          return;
        }
        setComparison(detail);
        setData(detail.result);
        setError(null);
        setIsLoading(false);
        if (detail.status === "pending" || detail.status === "processing") {
          timer = window.setTimeout(load, 3000);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(getRequestErrorMessage(requestError, "å¯¹æ¯”ç»“æžœåŠ è½½å¤±è´¥ï¼Œè¯·è¿”å›žåŽ†å²è®°å½•é¡µé‡è¯•ã€‚"));
          setIsLoading(false);
        }
      }
    };

    setIsLoading(true);
    void load();
    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [comparison_id, pollVersion]);

  // The comparison surface remains visible when evidence is conflicting or
  // unobservable; the presenter masks invalid deltas and explains the reason.
  const hasContent = useMemo(() => Boolean(data && !error && comparisonView), [data, error, comparisonView]);
  const isWorking = comparison?.status === "pending" || comparison?.status === "processing";
  const canRetry = Boolean(comparison_id && comparison?.status === "failed");

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const handleRetry = async () => {
    if (!comparison_id || !canRetry || isRetrying) {
      return;
    }
    setIsRetrying(true);
    setError(null);
    try {
      const detail = await retryAnalysisComparison(comparison_id);
      setComparison(detail);
      setData(detail.result);
      setPollVersion((current) => current + 1);
      showNotice("å·²é‡æ–°æäº¤å¯¹æ¯”ä»»åŠ¡");
    } catch (requestError) {
      setError(getRequestErrorMessage(requestError, "å¯¹æ¯”ä»»åŠ¡é‡è¯•å¤±è´¥ï¼Œè¯·ç¨åŽå†è¯•ã€‚"));
    } finally {
      setIsRetrying(false);
    }
  };

  const handleShareCompare = async () => {
    if (!data) return;
    setIsSharing(true);
    setError(null);
    try {
      if (!comparisonView) return;
      const result = await exportShareDocument(createFamilyCompareShareDocument(data, comparisonView, presentedActionLabel));
      setShareImagePreview(result.pages.map((page) => createShareImagePreview(page, false)));
      showNotice("分享图已生成");
    } catch {
      setError("分享图生成失败，请稍后重试。");
    } finally {
      setIsSharing(false);
    }
  };
  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/history" className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
          â† è¿”å›žåŽ†å²è®°å½•
        </Link>
        {data ? (
          <div className="flex flex-wrap gap-3">
            <SubmitButton
              onClick={() => void handleShareCompare()}
              status={isSharing ? "submitting" : error ? "error" : "idle"}
              error={error}
              loadingLabel="生成中..."
              className="rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSharing ? "ç”Ÿæˆä¸­â€¦" : "åˆ†äº«å¯¹æ¯”å›¾"}
            </SubmitButton>
            <Link to={`/report/${data.analysis_b.id}`} className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-blue-600">
              æŸ¥çœ‹æœ€æ–°æŠ¥å‘Š
            </Link>
          </div>
        ) : null}
      </div>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}
      {isLoading || experiencesLoading ? <div className="rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">正在读取同一份复盘证据…</div> : null}
      {!isLoading && comparison ? (
        <section className={`rounded-[28px] border px-5 py-4 text-sm ${comparisonStatusTone(comparison.status)}`}>
          <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
            <div>
              <p className="font-semibold">å¯¹æ¯”çŠ¶æ€ï¼š{comparisonStatusLabel(comparison.status)}</p>
              {isWorking ? <p className="mt-1 opacity-80">å¯¹æ¯”è¯æ®æ­£åœ¨æ•´ç†ï¼Œç»“æžœä¼šè‡ªåŠ¨åˆ·æ–°ã€‚</p> : null}
              {comparison.status === "failed" ? <p className="mt-1 opacity-80">{comparison.error_message || "å¯¹æ¯”ç”Ÿæˆå¤±è´¥ï¼Œè¯·é‡è¯•ã€‚"}</p> : null}
            </div>
            {canRetry ? (
              <SubmitButton
                onClick={() => void handleRetry()}
                status={isRetrying ? "submitting" : error ? "error" : "idle"}
                error={error}
                loadingLabel="重新提交中..."
                className="w-fit rounded-full bg-white px-4 py-2 text-sm font-semibold text-rose-600 shadow-sm transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isRetrying ? "é‡æ–°æäº¤ä¸­â€¦" : "é‡è¯•ç”Ÿæˆ"}
              </SubmitButton>
            ) : null}
          </div>
        </section>
      ) : null}

      {hasContent && data && comparisonView ? (
        <div className="space-y-6">
          <HeroSummary data={data} actionLabel={presentedActionLabel} compatibilityReason={comparisonView.reason} comparisonView={comparisonView} />
          <FamilyComparisonSection view={comparisonView} />
          <SyncedVideoSection data={data} comparisonView={comparisonView} />
        </div>
      ) : null}

      <IslandShareDialog preview={null} previews={shareImagePreview} title="对比分享图" onClose={() => setShareImagePreview([])} />
    </div>
  );
}
