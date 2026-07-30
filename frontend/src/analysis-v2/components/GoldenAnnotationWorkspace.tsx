import axios from "axios";
import { ChangeEvent, useEffect, useMemo, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import { IceMediaPlayer } from "../../media/IceMediaPlayer";
import { IslandButton, IslandCard, IslandTitle } from "../../modern/IslandSurface";
import { fetchGoldenReviewQueue, fetchGoldenSourceFrame, fetchGoldenWorkspace, importGoldenSource, saveGoldenAnnotations } from "../api";
import type { GoldenEvent, GoldenProfile, GoldenReviewItem, GoldenWorkspace } from "../golden-contracts";

const profiles: GoldenProfile[] = ["jump", "spin", "step", "spiral", "unknown"];
const uid = () => `event-${crypto.randomUUID()}`;

function blankEvent(sourceHash: string, now: number): GoldenEvent {
  return { event_id: uid(), source_sha256: sourceHash, start_pts: Math.max(0, now), end_pts: Math.max(0.1, now + 1), profile: "unknown", subtype: null, observability: "uncertain", strata: [], ambiguity_tags: [], failure_tags: [], annotator_confidence: 0.5, main_skater_confirmed: false, split: null, challenge_intervals: [] };
}

export default function GoldenAnnotationWorkspace() {
  const { parentPin } = useAppMode();
  const [workspace, setWorkspace] = useState<GoldenWorkspace | null>(null);
  const [review, setReview] = useState<GoldenReviewItem[]>([]);
  const [sourceHash, setSourceHash] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [frame, setFrame] = useState<{ sourceFrameIndex: number; pts: number; duration: number | null } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [message, setMessage] = useState<string | null>(null);
  const [annotator, setAnnotator] = useState("owner");

  const load = async () => {
    if (!parentPin) return;
    try {
      const [next, queue] = await Promise.all([fetchGoldenWorkspace(parentPin), fetchGoldenReviewQueue(parentPin)]);
      setWorkspace(next); setReview(queue); setSourceHash((previous) => previous ?? next.sources[0]?.source_sha256 ?? null);
    } catch { setMessage("Private annotation workspace is unavailable. Retry when the connection is restored."); }
  };
  useEffect(() => { void load(); }, [parentPin]);
  useEffect(() => { const update = () => setOffline(!navigator.onLine); window.addEventListener("online", update); window.addEventListener("offline", update); return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); }; }, []);
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } }; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [dirty]);

  const source = workspace?.sources.find((item) => item.source_sha256 === sourceHash) ?? null;
  const events = useMemo(() => workspace?.events.filter((item) => item.source_sha256 === sourceHash) ?? [], [workspace, sourceHash]);
  const selected = events.find((item) => item.event_id === selectedEvent) ?? null;
  const frameIndex = frame?.sourceFrameIndex ?? Math.max(0, Math.round(time * (source?.source_frame_count && source.duration_pts ? source.source_frame_count / source.duration_pts : 30)));

  const step = async (direction: -1 | 1) => {
    if (!parentPin || !source) return;
    try { const next = await fetchGoldenSourceFrame(parentPin, source.source_sha256, Math.max(0, frameIndex + direction)); setFrame(next); setTime(next.pts); setMessage(null); } catch { setFrame(null); setMessage("The requested source frame is unavailable; no label was saved."); }
  };
  const updateEvent = (change: Partial<GoldenEvent>) => {
    if (!workspace || !selected) return;
    setWorkspace({ ...workspace, events: workspace.events.map((event) => event.event_id === selected.event_id ? { ...event, ...change } : event) }); setDirty(true);
  };
  const createEvent = () => { if (!workspace || !source) return; const event = blankEvent(source.source_sha256, time); setWorkspace({ ...workspace, events: [...workspace.events, event] }); setSelectedEvent(event.event_id); setDirty(true); };
  const save = async () => {
    if (!workspace || !parentPin || offline) return;
    setSaving(true); setMessage(null);
    try { const next = await saveGoldenAnnotations(parentPin, { expected_revision: workspace.revision, annotator_alias: annotator, events: workspace.events, tracks: workspace.tracks, poses: workspace.poses }); setWorkspace(next); setDirty(false); setReview(await fetchGoldenReviewQueue(parentPin)); setMessage("Confirmed Ground Truth saved with a new revision."); }
    catch (error) { const status = axios.isAxiosError(error) ? error.response?.status : 0; setMessage(status === 409 ? "Another save won. Reloaded data is required before retrying." : "Save failed. Nothing was marked confirmed."); }
    finally { setSaving(false); }
  };
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file || !parentPin || !workspace) return;
    const form = new FormData(); form.set("file", file); form.set("recording_session_id", "session-new"); form.set("grouping_id", "session-new"); form.set("redacted_alias", `source-${workspace.sources.length + 1}`); form.set("expected_revision", String(workspace.revision)); form.set("annotator_alias", annotator);
    try { await importGoldenSource(parentPin, form); await load(); setMessage("Private source imported and source metadata recorded."); } catch { setMessage("Import failed; no private source was registered."); }
  };

  return <div className="golden-annotation" data-testid="golden-annotation-workspace">
    <IslandCard className="modern-me-panel"><IslandTitle>Private source browser</IslandTitle><label>Annotator <input value={annotator} onChange={(event) => setAnnotator(event.target.value)} /></label><label>Import a newly selected private video <input aria-label="Import private source video" type="file" accept="video/*" onChange={upload} /></label><select aria-label="Golden source" value={sourceHash ?? ""} onChange={(event) => { setSourceHash(event.target.value); setSelectedEvent(null); }}>{workspace?.sources.map((item) => <option key={item.source_sha256} value={item.source_sha256}>{item.redacted_alias} ({item.width}x{item.height})</option>)}</select>{source ? <p>Duration {source.duration_pts.toFixed(3)}s; display rotation {source.display_rotation_degrees} degrees. Source metadata stays private.</p> : <p>Import a newly selected video to begin. Historical debug media is unavailable here.</p>}</IslandCard>
    {source ? <IslandCard className="modern-me-panel"><IceMediaPlayer fallbackSrc={`/api/golden/v2/sources/${source.source_sha256}/media`} onTimeChange={setTime} seekTime={frame?.pts ?? null} sourceFrame={frame} onStepSourceFrame={step} unavailableFrame={message?.startsWith("The requested source frame") ?? false} /><p>Exact source time: {time.toFixed(6)} seconds. Frame identity is requested from the private source, not derived from CSS playback.</p></IslandCard> : null}
    <div className="golden-annotation__grid"><IslandCard className="modern-me-panel"><IslandTitle>Event intervals</IslandTitle><IslandButton onClick={createEvent} disabled={!source}>Add event at current source time</IslandButton><div className="golden-annotation__events">{events.map((event) => <button type="button" className={event.event_id === selectedEvent ? "is-active" : ""} key={event.event_id} onClick={() => setSelectedEvent(event.event_id)}>{event.profile} {event.start_pts.toFixed(2)}-{event.end_pts.toFixed(2)}</button>)}</div></IslandCard>
    <IslandCard className="modern-me-panel"><IslandTitle>Human Ground Truth</IslandTitle>{selected ? <div className="golden-annotation__form"><label>Profile <select value={selected.profile} onChange={(event) => updateEvent({ profile: event.target.value as GoldenProfile })}>{profiles.map((profile) => <option key={profile}>{profile}</option>)}</select></label><label>Subtype <input value={selected.subtype ?? ""} onChange={(event) => updateEvent({ subtype: event.target.value || null })} /></label><label>Start PTS <input type="number" step="0.001" value={selected.start_pts} onChange={(event) => updateEvent({ start_pts: Number(event.target.value) })} /></label><label>End PTS <input type="number" step="0.001" value={selected.end_pts} onChange={(event) => updateEvent({ end_pts: Number(event.target.value) })} /></label><label>Observability <select value={selected.observability} onChange={(event) => updateEvent({ observability: event.target.value as GoldenEvent["observability"] })}><option>observable</option><option>uncertain</option><option>unobservable</option></select></label><label><input type="checkbox" checked={selected.main_skater_confirmed} onChange={(event) => updateEvent({ main_skater_confirmed: event.target.checked })} /> Main skater confirmed</label><label>Confidence <input type="number" min="0" max="1" step="0.05" value={selected.annotator_confidence} onChange={(event) => updateEvent({ annotator_confidence: Number(event.target.value) })} /></label><p>For jump, record T/A/L and rotation in the source-time details. For spin, record entry/main/exit and observable turns. Step/spiral use phase plus representative moment. Boxes and pose labels remain separate typed records; mark pose unobservable instead of inventing joints.</p></div> : <p>Select or add an event. Suggestions are structurally separate and are never saved from this form.</p>}</IslandCard></div>
    <IslandCard className="modern-me-panel"><IslandTitle>Review queue and history</IslandTitle>{review.length ? <ul>{review.map((item) => <li key={`${item.event_id}-${item.status}`}>{item.event_id}: {item.message}</li>)}</ul> : <p>No incomplete, contradictory, or low-confidence labels need review.</p>}<p>Every human-confirmed field records annotator, timestamp, and revision in the private manifest history.</p></IslandCard>
    {message ? <p role="alert">{message}</p> : null}<IslandButton onClick={save} disabled={!dirty || saving || offline}>{saving ? "Saving..." : offline ? "Offline - retry when connected" : dirty ? "Save confirmed Ground Truth" : "All changes saved"}</IslandButton>{dirty ? <p>Unsaved changes: leaving this page will ask for confirmation.</p> : null}
  </div>;
}
