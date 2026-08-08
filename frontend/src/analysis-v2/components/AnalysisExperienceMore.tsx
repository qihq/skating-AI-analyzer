import type { AnalysisExperienceV2 } from "../contracts";
import { presentAnalysisExperience } from "../presenter";

export default function AnalysisExperienceMore({ experience, selectedEventId }: { experience: AnalysisExperienceV2; selectedEventId?: string | null }) {
  const view = presentAnalysisExperience(experience, selectedEventId);
  return <section className="app-card p-5 tablet:p-6" aria-labelledby="experience-more-title" data-testid="family-analysis-more">
    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">More</p>
    <h2 id="experience-more-title" className="mt-2 text-2xl font-semibold text-slate-900">更多</h2>
    <dl className="mt-4 grid gap-3 text-sm tablet:grid-cols-2">
      <div className="rounded-2xl bg-slate-50 p-4"><dt className="font-semibold text-slate-500">记录类型</dt><dd className="mt-1 text-slate-800">{view.authorityLabel}</dd></div>
      <div className="rounded-2xl bg-slate-50 p-4"><dt className="font-semibold text-slate-500">动作片段</dt><dd className="mt-1 text-slate-800">{view.events.length} 个</dd></div>
      <div className="rounded-2xl bg-slate-50 p-4"><dt className="font-semibold text-slate-500">当前状态</dt><dd className="mt-1 text-slate-800">{view.stateLabel}</dd></div>
      <div className="rounded-2xl bg-slate-50 p-4"><dt className="font-semibold text-slate-500">未进入确定结论</dt><dd className="mt-1 text-slate-800">{view.excludedClaimCount} 项</dd></div>
      <div className="rounded-2xl bg-slate-50 p-4"><dt className="font-semibold text-slate-500">可用于成长的内容</dt><dd className="mt-1 text-slate-800">{view.confirmedClaimCount} 项</dd></div>
    </dl>
    <p className="mt-4 text-xs leading-6 text-slate-500">普通页面只显示同一份复盘中可供家庭阅读的内容；内部模型、路线名称与原始诊断不会出现在这里。</p>
  </section>;
}
