import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { AnalysisCompareResponse, AnalysisDetail, fetchAnalysisCompare } from "../api/client";
import ReportCard from "../components/ReportCard";
import TopNav from "../components/TopNav";

const ISSUE_STYLES: Record<string, string> = {
  high: "border-rose-400/45 bg-rose-500/10",
  medium: "border-amber-300/45 bg-amber-400/10",
  low: "border-sky-300/40 bg-sky-400/10",
};

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(dateString));
}

function CompareColumn({ title, analysis }: { title: string; analysis: AnalysisDetail }) {
  return (
    <div className="space-y-5">
      <div className="frost-panel">
        <p className="text-sm uppercase tracking-[0.28em] text-cyan-200/80">{title}</p>
        <h2 className="mt-3 text-3xl font-semibold text-white">{analysis.action_type}</h2>
        <div className="mt-3 flex flex-wrap gap-3 text-sm text-slate-300">
          <span>{formatDate(analysis.created_at)}</span>
          {analysis.skater_name ? <span>{analysis.skater_name}</span> : null}
          {analysis.skill_category ? <span>{analysis.skill_category}</span> : null}
        </div>
        <div className="mt-6 inline-flex rounded-full bg-white/8 px-4 py-2 text-base text-white">
          发力评分 {analysis.force_score ?? "--"}
        </div>
      </div>

      <ReportCard title="总体评价" eyebrow="Summary">
        <p className="leading-7 text-slate-100/90">{analysis.report?.summary ?? "暂无总体评价。"}</p>
      </ReportCard>

      <ReportCard title="问题列表" eyebrow="Issues">
        <div className="space-y-3">
          {analysis.report?.issues?.length ? (
            analysis.report.issues.map((issue, index) => (
              <article key={`${issue.category}-${index}`} className={`rounded-3xl border p-4 ${ISSUE_STYLES[issue.severity] ?? ISSUE_STYLES.low}`}>
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-base font-medium text-white">{issue.category}</h3>
                  <span className="text-xs uppercase tracking-[0.22em] text-slate-200/80">{issue.severity}</span>
                </div>
                <p className="mt-2 leading-7 text-slate-100/90">{issue.description}</p>
              </article>
            ))
          ) : (
            <p className="text-slate-300">暂无明显问题。</p>
          )}
        </div>
      </ReportCard>

      <ReportCard title="改进建议" eyebrow="Improvements">
        <div className="space-y-3">
          {analysis.report?.improvements?.length ? (
            analysis.report.improvements.map((item, index) => (
              <article key={`${item.target}-${index}`} className="rounded-3xl border border-white/10 bg-white/5 p-4">
                <p className="text-sm uppercase tracking-[0.2em] text-cyan-200/80">{item.target}</p>
                <p className="mt-2 leading-7 text-slate-100/90">{item.action}</p>
              </article>
            ))
          ) : (
            <p className="text-slate-300">暂无改进建议。</p>
          )}
        </div>
      </ReportCard>
    </div>
  );
}

function SummaryGroup({
  title,
  items,
  tone,
}: {
  title: string;
  items: AnalysisCompareResponse["summary"]["improved"];
  tone: string;
}) {
  return (
    <ReportCard title={title} eyebrow="Compare" className={tone}>
      <div className="space-y-3">
        {items.length ? (
          items.map((item, index) => (
            <article key={`${item.category}-${index}`} className="rounded-3xl border border-white/10 bg-white/5 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <h3 className="text-base font-medium text-white">{item.category}</h3>
                {item.before_severity ? <span className="compare-severity">之前 {item.before_severity}</span> : null}
                {item.after_severity ? <span className="compare-severity">现在 {item.after_severity}</span> : null}
              </div>
              <p className="mt-3 leading-7 text-slate-100/90">{item.description}</p>
            </article>
          ))
        ) : (
          <p className="text-slate-300">当前没有该分类变化。</p>
        )}
      </div>
    </ReportCard>
  );
}

export default function ComparePage() {
  const { id_a, id_b } = useParams<{ id_a: string; id_b: string }>();
  const [data, setData] = useState<AnalysisCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id_a || !id_b) {
      setError("无效的对比参数。");
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetchAnalysisCompare(id_a, id_b);
        if (!cancelled) {
          setData(response);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("对比结果加载失败，请返回历史记录页重试。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [id_a, id_b]);

  return (
    <main className="page-shell page-scroll-container page-content min-h-screen">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="ice-orb left-[8%] top-[12%]" />
        <div className="ice-orb bottom-[12%] right-[10%]" />
        <div className="grid-ice h-full w-full" />
      </div>

      <section className="mx-auto min-h-screen w-full max-w-6xl px-6 py-6 lg:px-10">
        <TopNav />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link to="/history" className="pill-link">
            ← 返回历史记录
          </Link>
          {data ? (
            <div className="rounded-full bg-white/8 px-4 py-2 text-sm text-white">
              评分变化 {data.score_delta >= 0 ? "+" : ""}
              {data.score_delta}
            </div>
          ) : null}
        </div>

        {error ? (
          <div className="mt-6 frost-panel text-rose-100">{error}</div>
        ) : data ? (
          <>
            <div className="mt-8 grid gap-6 md:grid-cols-2">
              <CompareColumn title="较早记录" analysis={data.analysis_a} />
              <CompareColumn title="较新记录" analysis={data.analysis_b} />
            </div>

            <div className="mt-8 grid gap-6 lg:grid-cols-3">
              <SummaryGroup title="改善项" items={data.summary.improved} tone="border border-emerald-400/25 bg-emerald-400/8" />
              <SummaryGroup title="新增项" items={data.summary.added} tone="border border-rose-400/25 bg-rose-500/8" />
              <SummaryGroup title="未变化" items={data.summary.unchanged} tone="border border-white/10 bg-white/5" />
            </div>
          </>
        ) : (
          <div className="mt-6 frost-panel text-slate-300">正在生成对比结果…</div>
        )}
      </section>
    </main>
  );
}
