import { useSavedJumpReplay } from "../useSavedJumpReplay";
import { Link, useParams } from "react-router-dom";

import { fetchAnalysisExperienceV2 } from "../api";
import type { AnalysisExperienceV2, ExperienceEvent, ProfileMomentKey } from "../contracts";
import { actionEventLabel } from "../profilePresentation";
import { presentAnalysisExperience } from "../presenter";
import ActionPhaseStrip from "../../components/ActionPhaseStrip";
import AnalysisExperienceBody from "./AnalysisExperienceBody";
import AnalysisExperienceMore from "./AnalysisExperienceMore";
import AnalysisExperienceSummary from "./AnalysisExperienceSummary";
import { useEffect, useMemo, useState } from "react";

function EventPicker({ experience, selectedEventId, onSelect }: { experience: AnalysisExperienceV2; selectedEventId: string | null; onSelect: (eventId: string) => void }) {
  if (experience.events.length < 2) return null;
  return <section className="app-card p-4" aria-label="动作片段选择">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold text-slate-900">这次复盘里的动作片段</h2><span className="text-sm text-slate-500">{selectedEventId ?? "请选择"}</span></div>
    <div className="mt-3 flex snap-x gap-2 overflow-x-auto pb-1" role="listbox" aria-label="动作片段">
      {experience.events.map((event, index) => <button key={event.eventId} type="button" role="option" aria-selected={event.eventId === selectedEventId} onClick={() => onSelect(event.eventId)} className={`min-h-[44px] shrink-0 rounded-full border px-4 py-2 text-sm font-semibold ${event.eventId === selectedEventId ? "border-blue-500 bg-blue-500 text-white" : "border-slate-200 bg-white text-slate-700"}`}>片段 {index + 1} · {actionEventLabel(event)}</button>)}
    </div>
  </section>;
}

function EventUnavailable() {
  return <section className="app-card border border-slate-200 bg-slate-50 p-6" role="status"><p className="text-sm leading-7 text-slate-600">当前没有可安全展示的动作片段；需要家长复核后才能继续查看。</p></section>;
}

/** Family report keeps V2 authority; the matching saved legacy TAL event has a read-only replay projection. */
export default function AnalysisExperienceReport({ compact = false }: { compact?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const [experience, setExperience] = useState<AnalysisExperienceV2 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedMomentKey, setSelectedMomentKey] = useState<ProfileMomentKey | null>(null);

  useEffect(() => {
    if (!id) {
      setError("无效的复盘 ID。");
      return;
    }
    let cancelled = false;
    setExperience(null);
    setError(null);
    void fetchAnalysisExperienceV2(id)
      .then((next) => {
        if (cancelled) return;
        setExperience(next);
        setSelectedEventId(next.events[0]?.eventId ?? null);
      })
      .catch(() => {
        if (!cancelled) setError("当前复盘暂时不可用，请稍后重试。");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const selectedEvent = useMemo(() => experience?.events.find((event) => event.eventId === selectedEventId) ?? experience?.events[0] ?? null, [experience, selectedEventId]);
  const savedJumpReplay = useSavedJumpReplay(experience, selectedEvent?.eventId ?? null);
  useEffect(() => setSelectedMomentKey(null), [selectedEvent?.eventId]);

  if (error) return <section className="app-card mx-auto max-w-3xl p-8" role="alert"><h1 className="text-2xl font-semibold text-slate-900">复盘暂时不可用</h1><p className="mt-3 text-sm leading-7 text-slate-600">{error}</p><Link className="mt-5 inline-flex min-h-[44px] items-center rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700" to="/history">返回历史记录</Link></section>;
  if (!experience) return <section className="app-card mx-auto max-w-3xl p-8" role="status">正在读取复盘…</section>;

  const view = presentAnalysisExperience(experience, selectedEvent?.eventId);
  const familyCanInspectEvents = experience.familyUsable && !experience.diagnosticOnly;
  return <div className={`min-w-0 space-y-6 ${compact ? "text-sm" : ""}`} data-testid="experience-report-route">
    <header className="app-card overflow-hidden p-5 tablet:p-7">
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">分析复盘</p><h1 className="mt-2 text-3xl font-semibold text-slate-900">本次训练的复盘</h1><p className="mt-3 text-sm leading-7 text-slate-600">{view.stateLabel} · {view.authorityLabel}</p></div><Link className="app-pill w-fit" to="/review">开始新的复盘</Link></div>
      {experience.events.length > 1 ? <div className="mt-5"><EventPicker experience={experience} selectedEventId={selectedEvent?.eventId ?? null} onSelect={(next) => setSelectedEventId(next)} /></div> : null}
    </header>
    <AnalysisExperienceSummary experience={experience} selectedEventId={selectedEvent?.eventId} />
    {savedJumpReplay ? <ActionPhaseStrip analysis={savedJumpReplay} pose={savedJumpReplay.pose_data} showVideo /> : familyCanInspectEvents && selectedEvent ? <ActionPhaseStrip analysisId={experience.analysisId} pose={null} event={selectedEvent} selectedMomentKey={selectedMomentKey} onSelectMoment={setSelectedMomentKey} showVideo /> : <EventUnavailable />}
    <div className="grid gap-6 web:grid-cols-2"><AnalysisExperienceBody experience={experience} selectedEventId={familyCanInspectEvents ? selectedEvent?.eventId : null} /><AnalysisExperienceMore experience={experience} selectedEventId={familyCanInspectEvents ? selectedEvent?.eventId : null} /></div>
  </div>;
}
