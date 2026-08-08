import { Link } from "react-router-dom";

import type { AnalysisExperienceV2 } from "../contracts";
import { presentAnalysisExperience } from "../presenter";

export default function AnalysisExperienceSummary({
  experience,
  selectedEventId,
  compact = false,
}: {
  experience: AnalysisExperienceV2;
  selectedEventId?: string | null;
  compact?: boolean;
}) {
  const view = presentAnalysisExperience(experience, selectedEventId);
  const tone = view.state === "confirmed" ? "border-emerald-200 bg-emerald-50/70 text-emerald-900" : view.state === "unobservable" ? "border-slate-200 bg-slate-50 text-slate-700" : "border-amber-200 bg-amber-50/80 text-amber-900";
  return <section className={`rounded-[24px] border p-5 ${tone}`} aria-labelledby="experience-summary-title" aria-live="polite" data-testid="family-analysis-summary">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] opacity-70">{view.authorityLabel}</p>
        <h2 id="experience-summary-title" className={`${compact ? "text-xl" : "text-2xl"} mt-2 font-semibold`}>本次总结</h2>
      </div>
      <span className="rounded-full bg-white/80 px-3 py-1 text-xs font-semibold">{view.stateLabel}</span>
    </div>
    <p className="mt-3 leading-8">{view.summary}</p>
    {view.exclusionLabel ? <p className="mt-2 text-sm opacity-80" role="status">{view.exclusionLabel}</p> : null}
    {view.nextAction && view.nextAction.state !== "unobservable" ? <div className="mt-4 rounded-2xl bg-white/75 p-4"><p className="text-xs font-semibold uppercase tracking-[0.18em] opacity-65">下一步</p><strong className="mt-1 block">{view.nextAction.text}</strong>{view.nextAction.note ? <p className="mt-1 text-xs opacity-75">{view.nextAction.note}</p> : null}</div> : null}
    {view.reviewActionLabel ? <Link className="mt-4 inline-flex min-h-[44px] items-center rounded-full bg-white px-4 py-2 text-sm font-semibold shadow-sm" to={`/review?analysis=${encodeURIComponent(experience.analysisId)}${view.reviewTask?.eventId ? `&event=${encodeURIComponent(view.reviewTask.eventId)}` : ""}`}>{view.reviewActionLabel}</Link> : null}
  </section>;
}
