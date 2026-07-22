import { MonthlyFact, MonthlyFactSnapshot } from "../api/client";

const GROUP_LABELS: Record<string, string> = {
  count: "课次与复盘",
  metric: "可比较指标",
  milestone: "里程碑",
  observation: "重复观察",
  focus: "当前重点",
  quote: "本月球寄语",
};

const GROUP_ORDER = ["count", "metric", "milestone", "observation", "focus", "quote"];

function factSummary(fact: MonthlyFact): string {
  switch (fact.kind) {
    case "count":
      return fact.text ?? "";
    case "metric":
      return `${fact.label ?? fact.metric}（${fact.action_subtype ?? "动作"}）从 ${fact.before} ${fact.unit ?? ""} 到 ${fact.after} ${fact.unit ?? ""}（${fact.sample_count} 次样本）`;
    case "milestone":
      return fact.text ?? "";
    case "observation":
      return `${fact.category ?? ""}：本月重复 ${fact.occurrence_count ?? 0} 次`;
    case "focus":
      return `${fact.category ?? ""}：连续 ${fact.occurrence_count ?? 0} 次复盘关注`;
    case "quote":
      return `「${fact.text ?? ""}」—— ${fact.speaker ?? "未指定"}`;
    default:
      return fact.text ?? "";
  }
}

function qualityBadge(fact: MonthlyFact): string | null {
  if (fact.kind === "milestone") {
    switch (fact.verification) {
      case "parent_confirmed":
        return "家长确认";
      case "coach_confirmed":
        return "教练确认";
      default:
        return "系统识别";
    }
  }
  if (fact.kind === "metric") {
    return fact.sample_count && fact.sample_count >= 2 ? "趋势证据" : null;
  }
  return null;
}

interface MonthlyFactPreviewProps {
  snapshot: MonthlyFactSnapshot;
}

export default function MonthlyFactPreview({ snapshot }: MonthlyFactPreviewProps) {
  const grouped: Record<string, MonthlyFact[]> = {};
  for (const fact of snapshot.facts) {
    grouped[fact.kind] = grouped[fact.kind] ?? [];
    (grouped[fact.kind] ?? []).push(fact);
  }

  return (
    <section className="app-card p-5 tablet:p-6">
      <h2 className="text-xl font-semibold text-slate-900">本月事实预览</h2>
      <p className="mt-2 text-sm text-slate-500">
        本月记录 {snapshot.coverage.sessions} 次课次，完成 {snapshot.coverage.completed_analyses} 次动作分析；
        {snapshot.coverage.comparable_metrics > 0 ? `含 ${snapshot.coverage.comparable_metrics} 项可比较指标。` : "本月可比较指标较少。"}
      </p>

      {snapshot.quality_flags.includes("insufficient_comparable_evidence") ? (
        <p className="mt-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-700">
          本月可比较指标较少，未生成趋势结论；生成叙事时将如实说明。
        </p>
      ) : null}

      <div className="mt-5 grid gap-4">
        {GROUP_ORDER.filter((kind) => (grouped[kind] ?? []).length > 0).map((kind) => (
          <div key={kind}>
            <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-blue-500">{GROUP_LABELS[kind] ?? kind}</h3>
            <ul className="mt-3 space-y-2">
              {(grouped[kind] ?? []).map((fact) => {
                const badge = qualityBadge(fact);
                return (
                  <li key={fact.id} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span>{factSummary(fact)}</span>
                      {badge ? <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-600">{badge}</span> : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}