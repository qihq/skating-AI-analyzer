import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  fetchGrowthSummary,
  fetchMonthlyChapters,
  fetchSkaters,
  GrowthSummary,
  Skater,
} from "../api/client";
import GrowthKpiBar from "../components/GrowthKpiBar";
import MilestoneTimeline from "../components/MilestoneTimeline";
import { fetchAnalysisExperienceV2 } from "../analysis-v2/api";
import type { AnalysisExperienceV2 } from "../analysis-v2/contracts";
import { presentAnalysisExperience } from "../analysis-v2/presenter";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "暂时无法读取成长档案，请稍后重试。";
}

export default function GrowthHomePage() {
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState<string | null>(null);
  const [summary, setSummary] = useState<GrowthSummary | null>(null);
  const [latestExperience, setLatestExperience] = useState<AnalysisExperienceV2 | null>(null);
  const [hasPublishedChapters, setHasPublishedChapters] = useState(false);
  const [loadingSkaters, setLoadingSkaters] = useState(true);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    void fetchSkaters()
      .then((items) => {
        if (cancelled) {
          return;
        }
        setSkaters(items);
        setSelectedSkaterId((current) => current ?? items.find((item) => item.is_default)?.id ?? items[0]?.id ?? null);
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setError(errorMessage(requestError));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingSkaters(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedSkaterId) {
      return;
    }
    let cancelled = false;
    setLoadingSummary(true);
    setError(null);
    setSummary(null);
    setLatestExperience(null);
    setHasPublishedChapters(false);

    void (async () => {
      try {
        const nextSummary = await fetchGrowthSummary(selectedSkaterId);
        if (cancelled) {
          return;
        }
        setSummary(nextSummary);
        void fetchMonthlyChapters(selectedSkaterId)
          .then((chapters) => !cancelled && setHasPublishedChapters(chapters.some((chapter) => chapter.status === "published")))
          .catch(() => !cancelled && setHasPublishedChapters(false));
        if (nextSummary.latest_analysis_id) {
          const experience = await fetchAnalysisExperienceV2(nextSummary.latest_analysis_id);
          if (!cancelled) setLatestExperience(experience);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (!cancelled) {
          setLoadingSummary(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [selectedSkaterId]);

  const presented = latestExperience ? presentAnalysisExperience(latestExperience) : null;
  const nextAction = presented?.nextAction?.state === "confirmed" ? presented.nextAction.text : summary?.current_focus?.label;
  const skaterName = useMemo(
    () => skaters.find((s) => s.id === selectedSkaterId)?.display_name ?? "小滑手",
    [skaters, selectedSkaterId],
  );

  return (
    <div className="space-y-6">
      <section className="app-card p-6 tablet:p-8">
        <div className="flex flex-col gap-5 tablet:flex-row tablet:items-end tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Growth Home</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">看见每次训练，积累每一步进步</h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500">把最近一次复盘、下一步练习和成长里程碑放在同一个可信的入口。</p>
          </div>
          <label className="min-w-0 tablet:w-56">
            <span className="sr-only">当前练习档案</span>
            <select
              aria-label="当前练习档案"
              value={selectedSkaterId ?? ""}
              onChange={(event) => setSelectedSkaterId(event.target.value || null)}
              disabled={loadingSkaters || !skaters.length}
              className="app-input w-full"
            >
              {skaters.map((skater) => (
                <option key={skater.id} value={skater.id}>
                  {skater.display_name || skater.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {error ? <p role="alert" className="rounded-[22px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-700">{error}</p> : null}
      {loadingSkaters || loadingSummary ? <p className="app-card p-5 text-sm text-slate-500">正在读取成长记录…</p> : null}
      {!loadingSkaters && !selectedSkaterId && !error ? <p className="app-card p-5 text-sm text-slate-500">请先在设置中创建练习档案。</p> : null}

      {summary ? (
        <>
          <GrowthKpiBar summary={summary} />

          <section className="grid gap-4 tablet:grid-cols-3">
            <article className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">这次练得怎么样</p>
                <p className="mt-3 text-lg font-semibold text-slate-900">{presented?.summary || "完成复盘后，这里会显示本次训练的结论。"}</p>
            </article>
            <article className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">当前重点</p>
              <p className="mt-3 text-lg font-semibold text-slate-900">{summary.current_focus?.label || "完成第一次复盘后，系统会整理当前练习重点。"}</p>
              {summary.current_focus?.excluded_reason ? <p className="mt-2 text-xs leading-6 text-amber-700" role="status">{summary.current_focus.excluded_reason}</p> : null}
            </article>
            <article className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">下次具体练什么</p>
              <p className="mt-3 text-lg font-semibold text-slate-900">{nextAction || "完成第一次复盘后，这里会给出下一步练习动作。"}</p>
            </article>
          </section>

          {latestExperience ? (
            <section className="app-card p-5" aria-label="最近复盘状态">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">最近复盘</p>
              <p className="mt-3 text-sm leading-7 text-slate-600">{presented?.stateLabel} · {presented?.poseSummary}</p>
              {presented?.observations.slice(0, 2).map((item) => <p key={`${item.claim.claimType}-${item.claim.eventId ?? "all"}`} className="mt-2 text-sm leading-7 text-slate-700"><span className="font-semibold">{item.title}：</span>{item.text}</p>)}
            </section>
          ) : (
            <section className="app-card p-5 text-sm leading-7 text-slate-500">完成第一次复盘后，这里会出现关键动作阶段。</section>
          )}

          <MilestoneTimeline items={summary.recent_milestones} skaterName={skaterName} />

          <section className="flex flex-wrap gap-3">
            {summary.latest_analysis_id ? <Link className="app-pill" to={`/report/${summary.latest_analysis_id}`}>查看完整报告</Link> : null}
            <Link className="app-pill" to="/chapters">查看月度章节</Link>
            {hasPublishedChapters ? <Link className="app-pill" to="/annual">制作年度合集</Link> : null}
            <Link className="app-pill" to="/archive">查看月度进步</Link>
            <Link className="app-pill" to="/path">查看成长档案</Link>
          </section>
        </>
      ) : null}
    </div>
  );
}
