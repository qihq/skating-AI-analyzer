import type { GrowthSummary } from "../api/client";

interface GrowthKpiBarProps {
  summary: GrowthSummary;
}

export default function GrowthKpiBar({ summary }: GrowthKpiBarProps) {
  const items = [
    ["训练课次", summary.lesson_count, "lesson_count"],
    ["累计复盘", summary.completed_analysis_count, "completed_analysis_count"],
    ["本月复盘", summary.current_month_analysis_count, "current_month_analysis_count"],
    ["成长里程碑", summary.milestone_count, "milestone_count"],
  ] as const;

  return (
    <section className="app-card p-4 tablet:p-5" aria-label="成长数据摘要">
      <div className="grid grid-cols-2 gap-3 tablet:grid-cols-4">
        {items.map(([label, value, definitionKey]) => (
          <article
            key={definitionKey}
            title={summary.metric_definitions[definitionKey]}
            className="rounded-[20px] bg-slate-50 px-4 py-4"
          >
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
            <p className="mt-2 text-3xl font-semibold text-slate-900">{value}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
