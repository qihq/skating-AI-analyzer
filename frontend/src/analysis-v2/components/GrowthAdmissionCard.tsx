import { useEffect, useState } from "react";

import { fetchGrowthAdmission, type GrowthAdmissionReport } from "../api";

const REASON_LABELS: Record<string, string> = {
  ambiguous_profile: "动作家庭有歧义",
  unknown_profile: "动作家庭未知",
  missing_confirmed_profile: "缺少已确认动作家庭",
  incompatible_profile: "动作家庭不兼容",
  profile_not_eligible: "尚未满足成长记录条件",
  shadow_diagnostic: "Shadow 诊断结果不进入成长记录",
};

export default function GrowthAdmissionCard({ analysisIds, parentPin }: { analysisIds: string[]; parentPin: string }) {
  const [report, setReport] = useState<GrowthAdmissionReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setReport(null);
    setError(null);
    if (!analysisIds.length) return () => { active = false; };
    void fetchGrowthAdmission(parentPin, analysisIds)
      .then((next) => { if (active) setReport(next); })
      .catch(() => { if (active) setError("动作家庭纳入状态暂时无法读取。"); });
    return () => { active = false; };
  }, [analysisIds, parentPin]);

  return (
    <section className="mt-5 rounded-[24px] border border-sky-200 bg-sky-50/70 p-4 phone:p-5" aria-label="动作家庭成长纳入状态">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-sky-700">V2 Profile Admission</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-900">成长记录只接收已确认动作家庭</h2>
          <p className="mt-1 text-sm text-slate-600">有歧义、未知和 Shadow 诊断事件会被排除，不会默认为步法或其他动作。</p>
        </div>
        {report ? <div className="flex shrink-0 gap-2 text-sm"><span className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-800">纳入 {report.included_count}</span><span className="rounded-full bg-amber-100 px-3 py-1 text-amber-800">排除 {report.excluded_count}</span></div> : null}
      </div>
      {!analysisIds.length ? <p className="mt-3 text-sm text-slate-500">当前范围还没有可检查的复盘。</p> : null}
      {analysisIds.length && !report && !error ? <p className="mt-3 text-sm text-slate-500" role="status">正在检查动作家庭纳入条件…</p> : null}
      {error ? <p className="mt-3 text-sm text-rose-700" role="alert">{error}</p> : null}
      {report && Object.keys(report.excluded_reasons).length ? <ul className="mt-3 grid gap-2 text-sm text-slate-700 tablet:grid-cols-2">{Object.entries(report.excluded_reasons).map(([reason, count]) => <li key={reason} className="rounded-2xl bg-white px-3 py-2">{REASON_LABELS[reason] ?? reason}：{count}</li>)}</ul> : null}
    </section>
  );
}
