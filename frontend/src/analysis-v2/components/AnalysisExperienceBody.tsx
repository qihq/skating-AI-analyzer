import type { AnalysisExperienceV2 } from "../contracts";
import { presentAnalysisExperience } from "../presenter";

export default function AnalysisExperienceBody({ experience, selectedEventId }: { experience: AnalysisExperienceV2; selectedEventId?: string | null }) {
  const view = presentAnalysisExperience(experience, selectedEventId);
  return <section className="app-card p-5 tablet:p-6" aria-labelledby="experience-body-title" data-testid="family-analysis-body">
    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">Body & posture</p>
    <h2 id="experience-body-title" className="mt-2 text-2xl font-semibold text-slate-900">身体与姿态</h2>
    <p className="mt-3 text-sm leading-7 text-slate-600">{view.poseSummary}</p>
    <div className="mt-5 grid gap-3 tablet:grid-cols-2">
      {view.observations.map((item, index) => <article key={`${item.claim.claimType}-${item.claim.eventId ?? "all"}-${index}`} className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between gap-3"><h3 className="font-semibold text-slate-900">{item.title}</h3><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${item.state === "confirmed" ? "bg-emerald-50 text-emerald-700" : item.state === "unobservable" ? "bg-slate-100 text-slate-600" : "bg-amber-50 text-amber-700"}`}>{item.state === "confirmed" ? "已确认" : item.state === "unobservable" ? "暂不判断" : "需要确认"}</span></div>
        <p className="mt-2 leading-7 text-slate-700">{item.text}</p>
        {item.note ? <p className="mt-2 text-xs leading-5 text-slate-500">{item.note}</p> : null}
      </article>)}
      {!view.observations.length ? <p className="rounded-2xl border border-dashed border-slate-300 p-4 text-sm leading-7 text-slate-500">当前没有可安全展示的身体或技术观察；不会从旧字段补齐。</p> : null}
    </div>
  </section>;
}
