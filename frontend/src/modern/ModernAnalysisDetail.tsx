import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { fetchAnalysisExperienceV2 } from "../analysis-v2/api";
import type { AnalysisExperienceV2, ExperienceEvent, ProfileMomentKey } from "../analysis-v2/contracts";
import { useAppMode } from "../components/AppModeContext";
import { IslandPageHeader } from "./IslandSurface";
import SectionNav from "./SectionNav";
import { AnalysisView, resolveAnalysisView } from "./analysisNavigation";
import { orderedProposalEvents, proposalDeepLink, selectProposalEvent } from "../analysis-v2/eventProposals";
import { actionEventLabel } from "../analysis-v2/profilePresentation";
import ActionPhaseStrip from "../components/ActionPhaseStrip";
import AnalysisExperienceSummary from "../analysis-v2/components/AnalysisExperienceSummary";
import AnalysisExperienceBody from "../analysis-v2/components/AnalysisExperienceBody";
import AnalysisExperienceMore from "../analysis-v2/components/AnalysisExperienceMore";
import { presentAnalysisExperience } from "../analysis-v2/presenter";

const ITEMS = [
  { id: "summary", label: "总结", to: "summary" },
  { id: "moments", label: "关键时刻", to: "moments" },
  { id: "body", label: "身体与姿态", to: "body" },
  { id: "ask", label: "追问", to: "ask" },
  { id: "more", label: "更多", to: "more" },
] as const;

export default function ModernAnalysisDetail({ initialView }: { initialView?: AnalysisView }) {
  const { id } = useParams<{ id: string }>();
  const { isParentMode, parentPin } = useAppMode();
  const [experience, setExperience] = useState<AnalysisExperienceV2 | null>(null);
  const [selectedMomentKey, setSelectedMomentKey] = useState<ProfileMomentKey | null>(null);
  const [params, setParams] = useSearchParams();
  const view = resolveAnalysisView({ initialView, view: params.get("view"), legacyTab: params.get("tab") });
  const sectionItems = ITEMS.map((item) => ({
    ...item,
    to: `/analysis/${id}?view=${item.to}${item.id === "more" ? "&tool=diagnostics" : ""}`,
  }));
  const selected = useMemo(() => experience ? selectProposalEvent(experience, params.get("event")) : { eventId: null, event: null }, [experience, params]);
  const proposalEvents = useMemo(() => experience ? orderedProposalEvents(experience) : [], [experience]);
  useEffect(() => {
    if (!experience || !selected.eventId || params.get("event") === selected.eventId) return;
    const next = new URLSearchParams(params);
    next.set("event", selected.eventId);
    setParams(next, { replace: true });
  }, [experience, params, selected.eventId, setParams]);
  useEffect(() => { setSelectedMomentKey(null); }, [selected.eventId]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setExperience(null);
    void fetchAnalysisExperienceV2(id)
      .then((next) => { if (!cancelled) setExperience(next); })
      .catch(() => { if (!cancelled) setExperience(null); });
    return () => { cancelled = true; };
  }, [id, isParentMode, parentPin]);

  return (
    <div className="modern-space modern-analysis-detail">
      <IslandPageHeader
        title="分析详情"
        description="结论、关键时刻、身体姿态和追问都集中在同一次复盘里。"
        action={<Link className="island-button island-button--secondary" to="/review">返回冰场小屋</Link>}
      />
      <SectionNav label="分析详情分区" items={sectionItems} activeId={view} />
      {experience ? (
        <section className="modern-analysis-detail__experience" data-testid="analysis-experience-contract" aria-label="分析复盘状态">
          <span className="rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-xs font-semibold text-slate-600">{experience.authority === "v2" ? "Current review" : "Legacy history"}</span>
          {experience.diagnosticOnly && proposalEvents.length ? <div className="modern-analysis-detail__events" aria-label="动作事件概览">
            <p>这里的事件只用于家长复核</p>
            <div role="listbox" aria-label="动作事件选择">
              {proposalEvents.map((event, index) => <button type="button" role="option" aria-label={`Event ${index + 1} · ${actionEventLabel(event)}`} aria-selected={event.eventId === selected.eventId} key={event.eventId} onClick={() => { const next = new URLSearchParams(params); next.set("event", event.eventId); setParams(next); }}>
                事件 {index + 1} · {actionEventLabel(event)} · {event.startPts?.toFixed(2) ?? "?"}–{event.endPts?.toFixed(2) ?? "?"} 秒
              </button>)}
            </div>
            {selected.event ? <p data-testid="selected-proposal">当前事件 {selected.event.eventId}：{actionEventLabel(selected.event)} · {selected.event.observability}</p> : null}
            {selected.event ? <Link to={proposalDeepLink(experience.analysisId, selected.event.eventId)}>复制事件链接</Link> : null}
          </div> : null}
        </section>
      ) : null}
      <div className="modern-analysis-detail__content">
        {experience ? <ExperienceSection experience={experience} view={view} selectedEvent={selected.event} selectedEventId={selected.eventId} selectedMomentKey={selectedMomentKey} onSelectMoment={setSelectedMomentKey} parentPin={parentPin} analysisId={id} initialSeekPts={params.has("t") && Number.isFinite(Number(params.get("t"))) ? Number(params.get("t")) : null} /> : (
          <section className="app-card p-6" role="status">当前复盘暂时不可用，请稍后重试。</section>
        )}
      </div>
    </div>
  );
}

function ExperienceSection({ experience, view, selectedEvent, selectedEventId, selectedMomentKey, onSelectMoment, parentPin, analysisId, initialSeekPts }: { experience: AnalysisExperienceV2; view: AnalysisView; selectedEvent: ExperienceEvent | null; selectedEventId: string | null; selectedMomentKey: ProfileMomentKey | null; onSelectMoment: (key: ProfileMomentKey) => void; parentPin: string | null; analysisId?: string; initialSeekPts: number | null }) {
  const familyView = presentAnalysisExperience(experience, selectedEventId);
  const eventSelector = experience.diagnosticOnly ? null : <EventSelector experience={experience} selectedEvent={selectedEvent} selectedEventId={selectedEventId} />;
  if (view === "summary") return <div className="space-y-5">{eventSelector}<AnalysisExperienceSummary experience={experience} selectedEventId={selectedEventId} /><div className="grid gap-5 web:grid-cols-2"><AnalysisExperienceBody experience={experience} selectedEventId={selectedEventId} /><AnalysisExperienceMore experience={experience} selectedEventId={selectedEventId} /></div></div>;
  if (view === "moments") return <div className="space-y-5">{eventSelector}{selectedEvent ? <ActionPhaseStrip analysisId={analysisId} pose={null} event={selectedEvent} selectedMomentKey={selectedMomentKey} onSelectMoment={onSelectMoment} parentPin={parentPin} showVideo initialSeekPts={initialSeekPts} /> : <UnavailableCard text="当前没有可展示的动作片段。" />}</div>;
  if (view === "body") return <div className="space-y-5">{eventSelector}<AnalysisExperienceBody experience={experience} selectedEventId={selectedEventId} /></div>;
  if (view === "more") return <div className="space-y-5"><AnalysisExperienceMore experience={experience} selectedEventId={selectedEventId} />{experience.diagnosticOnly ? <Link className="inline-flex min-h-[44px] items-center rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700" to={`/me/advanced?analysis=${encodeURIComponent(experience.analysisId)}`}>打开家长复核工具</Link> : null}</div>;
  return <section className="app-card p-6" aria-labelledby="experience-chat-title"><h2 id="experience-chat-title" className="text-2xl font-semibold text-slate-900">追问</h2><p className="mt-3 leading-7 text-slate-600">你可以围绕这次复盘继续提问。回答只会使用当前复盘里已经确认的内容，并会保留未知或需要确认的部分。</p><Link className="mt-5 inline-flex min-h-[44px] items-center rounded-full bg-blue-500 px-5 py-2 text-sm font-semibold text-white" to={`/analysis-chat?analysis=${encodeURIComponent(experience.analysisId)}${selectedEventId ? `&event=${encodeURIComponent(selectedEventId)}` : ""}`}>继续追问</Link><p className="mt-3 text-xs text-slate-500">{familyView.excludedClaimCount ? `${familyView.excludedClaimCount} 项内容仍未进入确定结论。` : "当前复盘没有需要额外确认的内容。"}</p></section>;
}

function EventSelector({ experience, selectedEvent, selectedEventId }: { experience: AnalysisExperienceV2; selectedEvent: ExperienceEvent | null; selectedEventId: string | null }) {
  const [params, setParams] = useSearchParams();
  if (experience.events.length < 2) return null;
  const select = (id: string) => { const next = new URLSearchParams(params); next.set("event", id); setParams(next); };
  return <section className="app-card p-4" aria-label="动作片段选择">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold text-slate-900">这次复盘里的动作片段</h2><span className="text-sm text-slate-500">{selectedEvent ? actionEventLabel(selectedEvent) : "请选择"}</span></div>
    <div className="mt-3 flex snap-x gap-2 overflow-x-auto pb-1" role="listbox" aria-label="动作片段">
      {orderedProposalEvents(experience).map((event, index) => <button key={event.eventId} role="option" aria-selected={event.eventId === selectedEventId} type="button" onClick={() => select(event.eventId)} className={`min-h-[44px] shrink-0 rounded-full border px-4 py-2 text-sm font-semibold ${event.eventId === selectedEventId ? "border-blue-500 bg-blue-500 text-white" : "border-slate-200 bg-white text-slate-700"}`}>片段 {index + 1} · {actionEventLabel(event)}</button>)}
    </div>
  </section>;
}

function UnavailableCard({ text }: { text: string }) { return <section className="app-card border border-slate-200 bg-slate-50 p-6" role="status"><p className="text-sm leading-7 text-slate-600">{text}</p></section>; }
