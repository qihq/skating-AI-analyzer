import axios from "axios";
import { ChangeEvent, useEffect, useMemo, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import { IceMediaPlayer } from "../../media/IceMediaPlayer";
import { IslandButton, IslandCard, IslandTitle } from "../../modern/IslandSurface";
import { attestGoldenReview, fetchGoldenReviewQueue, fetchGoldenSourceFrame, fetchGoldenSourceMediaUrl, fetchGoldenWorkspace, importGoldenSource, saveGoldenAnnotations } from "../api";
import type { ChallengeInterval, GoldenEvent, GoldenObservability, GoldenPose, GoldenProfile, GoldenReviewItem, GoldenTrack, GoldenWorkspace, IntervalDetails, JumpDetails, PhaseInterval, RotationLabel, SourceMoment, SpinDetails } from "../golden-contracts";

const profiles: GoldenProfile[] = ["jump", "spin", "step", "spiral", "unknown"];
const joints = ["nose", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"] as const;
const uid = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;
const numberValue = (value: string) => Number(value);

function blankEvent(sourceHash: string, now: number): GoldenEvent {
  return { event_id: uid("event"), source_sha256: sourceHash, start_pts: Math.max(0, now), end_pts: Math.max(0.1, now + 1), profile: "unknown", subtype: null, observability: "uncertain", strata: [], ambiguity_tags: [], failure_tags: [], annotator_confidence: 0.5, main_skater_confirmed: false, split: null, challenge_intervals: [] };
}

function blankRotation(): RotationLabel {
  return { observed_turns_min: 0, observed_turns_max: 0, reported_turns: null, convention: "unknown", observability: "uncertain" };
}

export default function GoldenAnnotationWorkspace() {
  const { parentPin } = useAppMode();
  const params = new URLSearchParams(window.location.search);
  const [workspace, setWorkspace] = useState<GoldenWorkspace | null>(null);
  const [review, setReview] = useState<GoldenReviewItem[]>([]);
  const [sourceHash, setSourceHash] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [frame, setFrame] = useState<{ sourceFrameIndex: number; pts: number; duration: number | null } | null>(null);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [message, setMessage] = useState<string | null>(null);
  const [annotator, setAnnotator] = useState("owner");
  const [sessionAlias, setSessionAlias] = useState("");
  const [groupAlias, setGroupAlias] = useState("");
  const [reviewType, setReviewType] = useState<"delayed_relabel" | "ambiguous_rotation" | "frozen_identity_crossing">("delayed_relabel");
  const [boxDraft, setBoxDraft] = useState({ left: "", top: "", right: "", bottom: "", state: "confirmed" as GoldenTrack["state"] });
  const [poseDraft, setPoseDraft] = useState({ joint: "nose" as typeof joints[number], x: "", y: "", visibility: "1", observability: "observable" as GoldenPose["observability"] });

  const load = async () => {
    if (!parentPin) return;
    try {
      const [next, queue] = await Promise.all([fetchGoldenWorkspace(parentPin), fetchGoldenReviewQueue(parentPin)]);
      const requested = next.events.find((event) => event.event_id === params.get("event"));
      setWorkspace(next); setReview(queue);
      setSourceHash((previous) => requested?.source_sha256 ?? previous ?? next.sources[0]?.source_sha256 ?? null);
      setSelectedEvent((previous) => requested?.event_id ?? previous);
      if (requested && Number.isFinite(Number(params.get("pts")))) setTime(Number(params.get("pts")));
    } catch { setMessage("Private annotation workspace is unavailable. Retry when the connection is restored."); }
  };
  useEffect(() => { void load(); }, [parentPin]);
  useEffect(() => { const update = () => setOffline(!navigator.onLine); window.addEventListener("online", update); window.addEventListener("offline", update); return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); }; }, []);
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } }; window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn); }, [dirty]);
  useEffect(() => {
    let active = true;
    if (!parentPin || !sourceHash) { setMediaUrl(null); return; }
    void fetchGoldenSourceMediaUrl(parentPin, sourceHash).then((url) => {
      if (!active) { URL.revokeObjectURL(url); return; }
      setMediaUrl((previous) => { if (previous) URL.revokeObjectURL(previous); return url; }); setMessage(null);
    }).catch(() => { if (active) setMessage("Private video could not be authorized. Re-enter parent mode and retry."); });
    return () => { active = false; };
  }, [parentPin, sourceHash]);
  useEffect(() => () => { if (mediaUrl) URL.revokeObjectURL(mediaUrl); }, [mediaUrl]);

  const source = workspace?.sources.find((item) => item.source_sha256 === sourceHash) ?? null;
  const events = useMemo(() => workspace?.events.filter((item) => item.source_sha256 === sourceHash) ?? [], [workspace, sourceHash]);
  const selected = events.find((item) => item.event_id === selectedEvent) ?? null;
  const tracks = useMemo(() => workspace?.tracks.filter((item) => item.event_id === selectedEvent) ?? [], [workspace, selectedEvent]);
  const poses = useMemo(() => workspace?.poses.filter((item) => item.event_id === selectedEvent) ?? [], [workspace, selectedEvent]);
  const frameIndex = frame?.sourceFrameIndex ?? Math.max(0, Math.round(time * (source?.source_frame_count && source.duration_pts ? source.source_frame_count / source.duration_pts : 30)));
  const currentMoment = (): SourceMoment | null => frame ? { pts: frame.pts, source_frame_index: frame.sourceFrameIndex } : null;
  const requireSourceFrame = () => {
    if (frame) return true;
    setMessage("Step to the exact private source frame before capturing a moment, box, or pose joint.");
    return false;
  };

  const step = async (direction: -1 | 1) => {
    if (!parentPin || !source) return;
    try { const next = await fetchGoldenSourceFrame(parentPin, source.source_sha256, Math.max(0, frameIndex + direction)); setFrame(next); setTime(next.pts); setMessage(null); } catch { setFrame(null); setMessage("The requested source frame is unavailable; no label was saved."); }
  };
  const updateEvent = (change: Partial<GoldenEvent>) => {
    if (!workspace || !selected) return;
    setWorkspace({ ...workspace, events: workspace.events.map((event) => event.event_id === selected.event_id ? { ...event, ...change } : event) }); setDirty(true);
  };
  const updateTrack = (labelId: string, change: Partial<GoldenTrack>) => {
    if (!workspace) return;
    setWorkspace({ ...workspace, tracks: workspace.tracks.map((item) => item.label_id === labelId ? { ...item, ...change } : item) }); setDirty(true);
  };
  const updatePose = (labelId: string, change: Partial<GoldenPose>) => {
    if (!workspace) return;
    setWorkspace({ ...workspace, poses: workspace.poses.map((item) => item.label_id === labelId ? { ...item, ...change } : item) }); setDirty(true);
  };
  const createEvent = () => { if (!workspace || !source) return; const event = blankEvent(source.source_sha256, time); setWorkspace({ ...workspace, events: [...workspace.events, event] }); setSelectedEvent(event.event_id); setDirty(true); };
  const selectProfile = (profile: GoldenProfile) => updateEvent({ profile, jump: null, spin: null, step: null, spiral: null });
  const intervalProfile = selected?.profile === "step" || selected?.profile === "spiral" ? selected.profile : null;
  const intervalDetails = intervalProfile ? selected?.[intervalProfile] as IntervalDetails | null | undefined : null;
  const setMoment = (key: "takeoff" | "apex" | "landing" | "representative_moment") => {
    if (!selected) return;
    if (!requireSourceFrame()) return;
    const moment = currentMoment();
    if (!moment) return;
    if (key === "representative_moment" && intervalProfile) updateEvent({ [intervalProfile]: { ...(intervalDetails ?? {}), representative_moment: moment } });
    else updateEvent({ jump: { ...(selected.jump ?? {}), [key]: moment } });
  };
  const setPhase = (key: "entry" | "main" | "exit" | "phase", field: keyof PhaseInterval, value: number) => {
    if (!selected) return;
    if (key === "phase" && intervalProfile) updateEvent({ [intervalProfile]: { ...(intervalDetails ?? {}), phase: { ...(intervalDetails?.phase ?? { start_pts: selected.start_pts, end_pts: selected.end_pts }), [field]: value } } });
    else {
      const spinKey = key as "entry" | "main" | "exit";
      updateEvent({ spin: { ...(selected.spin ?? {}), [spinKey]: { ...(selected.spin?.[spinKey] ?? { start_pts: selected.start_pts, end_pts: selected.end_pts }), [field]: value } } });
    }
  };
  const setRotation = (profile: "jump" | "spin", change: Partial<RotationLabel>) => updateEvent({ [profile]: { ...(selected?.[profile] ?? {}), rotation: { ...((selected?.[profile] as JumpDetails | SpinDetails | null)?.rotation ?? blankRotation()), ...change } } });
  const addChallenge = () => { if (!selected) return; updateEvent({ challenge_intervals: [...selected.challenge_intervals, { start_pts: selected.start_pts, end_pts: selected.end_pts, category: "unknown", observability: "uncertain" }] }); };
  const updateChallenge = (index: number, change: Partial<ChallengeInterval>) => { if (!selected) return; updateEvent({ challenge_intervals: selected.challenge_intervals.map((item, itemIndex) => itemIndex === index ? { ...item, ...change } : item) }); };
  const removeChallenge = (index: number) => { if (selected) updateEvent({ challenge_intervals: selected.challenge_intervals.filter((_, itemIndex) => itemIndex !== index) }); };
  const capturePhaseStart = (key: "entry" | "main" | "exit" | "phase") => {
    if (!selected) return;
    if (time >= selected.end_pts) { setMessage("Move the source cursor inside the event interval before starting this phase."); return; }
    if (key === "phase" && intervalProfile) updateEvent({ [intervalProfile]: { ...(intervalDetails ?? {}), phase: { start_pts: time, end_pts: selected.end_pts } } });
    else if (key !== "phase") updateEvent({ spin: { ...(selected.spin ?? {}), [key]: { start_pts: time, end_pts: selected.end_pts } } });
  };
  const addBox = () => {
    if (!workspace || !selected) return;
    if (!requireSourceFrame() || !frame) return;
    const bbox = { left: numberValue(boxDraft.left), top: numberValue(boxDraft.top), right: numberValue(boxDraft.right), bottom: numberValue(boxDraft.bottom) };
    if (Object.values(bbox).some((value) => !Number.isFinite(value)) || bbox.left < 0 || bbox.top < 0 || bbox.right > 1 || bbox.bottom > 1 || bbox.right <= bbox.left || bbox.bottom <= bbox.top) { setMessage("Enter a real normalized box (0 to 1, with positive area) before adding it."); return; }
    setWorkspace({ ...workspace, tracks: [...workspace.tracks, { label_id: uid("track"), event_id: selected.event_id, source_sha256: selected.source_sha256, source_frame_index: frame.sourceFrameIndex, pts: frame.pts, bbox, state: boxDraft.state }] }); setDirty(true); setMessage(null);
  };
  const addPoseJoint = () => {
    if (!workspace || !selected) return;
    if (!requireSourceFrame() || !frame) return;
    const x = numberValue(poseDraft.x); const y = numberValue(poseDraft.y); const visibility = numberValue(poseDraft.visibility);
    if (![x, y, visibility].every(Number.isFinite) || x < 0 || x > 1 || y < 0 || y > 1 || visibility < 0 || visibility > 1) { setMessage("Enter observed normalized joint coordinates and visibility (0 to 1) before adding them."); return; }
    const existing = workspace.poses.find((item) => item.event_id === selected.event_id && item.source_frame_index === frame.sourceFrameIndex);
    if (existing && existing.joints.some((joint) => joint.joint === poseDraft.joint)) { setMessage("That joint already exists on this source frame. Edit it below instead."); return; }
    const joint = { joint: poseDraft.joint, x, y, visibility };
    setWorkspace({ ...workspace, poses: existing ? workspace.poses.map((item) => item.label_id === existing.label_id ? { ...item, joints: [...item.joints, joint] } : item) : [...workspace.poses, { label_id: uid("pose"), event_id: selected.event_id, source_sha256: selected.source_sha256, source_frame_index: frame.sourceFrameIndex, pts: frame.pts, observability: poseDraft.observability, joints: [joint] }] }); setDirty(true); setMessage(null);
  };
  const save = async () => {
    if (!workspace || !parentPin || offline) return;
    setSaving(true); setMessage(null);
    try { const next = await saveGoldenAnnotations(parentPin, { expected_revision: workspace.revision, annotator_alias: annotator, events: workspace.events, tracks: workspace.tracks, poses: workspace.poses }); setWorkspace(next); setDirty(false); setReview(await fetchGoldenReviewQueue(parentPin)); setMessage("Confirmed Ground Truth saved with a new revision."); }
    catch (error) { const status = axios.isAxiosError(error) ? error.response?.status : 0; setMessage(status === 409 ? "Another save won. Reloaded data is required before retrying." : "Save failed. Nothing was marked confirmed. Check event bounds, profile fields, and label values."); }
    finally { setSaving(false); }
  };
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file || !parentPin || !workspace) return;
    if (!sessionAlias.trim() || !groupAlias.trim()) { setMessage("Enter redacted recording-session and grouping aliases before import."); event.target.value = ""; return; }
    const form = new FormData(); form.set("file", file); form.set("recording_session_id", sessionAlias.trim()); form.set("grouping_id", groupAlias.trim()); form.set("redacted_alias", `source-${workspace.sources.length + 1}`); form.set("expected_revision", String(workspace.revision)); form.set("annotator_alias", annotator);
    try { await importGoldenSource(parentPin, form); await load(); setMessage("Private source imported and source metadata recorded."); } catch { setMessage("Import failed; no private source was registered."); }
  };
  const attestReview = async () => { if (!parentPin || !selected) return; try { await attestGoldenReview(parentPin, selected.event_id, { reviewer_alias: annotator, review_type: reviewType }); await load(); setMessage("Review attestation recorded separately from Ground Truth."); } catch { setMessage("Review attestation was not eligible or could not be recorded."); } };

  const momentEditor = (label: string, key: "takeoff" | "apex" | "landing" | "representative_moment", value?: SourceMoment | null) => <div className="golden-annotation__capture"><span>{label}: {value ? `${value.pts.toFixed(6)}s / frame ${value.source_frame_index ?? "not supplied"}` : "not set"}</span><IslandButton variant="secondary" onClick={() => setMoment(key)}>Use current frame and PTS</IslandButton></div>;
  const phaseEditor = (label: string, key: "entry" | "main" | "exit" | "phase", value?: PhaseInterval | null) => <fieldset className="golden-annotation__phase"><legend>{label}</legend><label>Start PTS <input aria-label={`${label} start PTS`} type="number" step="0.001" value={value?.start_pts ?? selected?.start_pts ?? 0} onChange={(event) => setPhase(key, "start_pts", numberValue(event.target.value))} /></label><label>End PTS <input aria-label={`${label} end PTS`} type="number" step="0.001" value={value?.end_pts ?? selected?.end_pts ?? 0} onChange={(event) => setPhase(key, "end_pts", numberValue(event.target.value))} /></label><IslandButton variant="secondary" onClick={() => capturePhaseStart(key)}>Start at current PTS</IslandButton></fieldset>;
  const rotationEditor = (profile: "jump" | "spin", value?: RotationLabel | null) => { const rotation = value ?? blankRotation(); return <fieldset className="golden-annotation__rotation"><legend>Rotation (human observation only)</legend><label>Minimum turns <input aria-label={`${profile} minimum turns`} type="number" min="0" max="12" step="0.25" value={rotation.observed_turns_min} onChange={(event) => setRotation(profile, { observed_turns_min: numberValue(event.target.value) })} /></label><label>Maximum turns <input aria-label={`${profile} maximum turns`} type="number" min="0" max="12" step="0.25" value={rotation.observed_turns_max} onChange={(event) => setRotation(profile, { observed_turns_max: numberValue(event.target.value) })} /></label><label>Reported turns <input aria-label={`${profile} reported turns`} type="number" min="0" max="12" step="0.25" value={rotation.reported_turns ?? ""} onChange={(event) => setRotation(profile, { reported_turns: event.target.value === "" ? null : numberValue(event.target.value) })} /></label><label>Convention <select aria-label={`${profile} rotation convention`} value={rotation.convention} onChange={(event) => setRotation(profile, { convention: event.target.value as RotationLabel["convention"] })}><option value="unknown">unknown</option><option value="axel_includes_forward_takeoff">axel includes forward takeoff</option><option value="non_axel_airborne">non-axel airborne</option></select></label><label>Rotation observability <select aria-label={`${profile} rotation observability`} value={rotation.observability} onChange={(event) => setRotation(profile, { observability: event.target.value as GoldenObservability })}><option>observable</option><option>uncertain</option><option>unobservable</option></select></label></fieldset>; };

  return <div className="golden-annotation" data-testid="golden-annotation-workspace">
    <IslandCard className="modern-me-panel"><IslandTitle>Private source browser</IslandTitle><div className="golden-annotation__source-fields"><label>Annotator <input value={annotator} onChange={(event) => setAnnotator(event.target.value)} /></label><label>Recording-session alias <input aria-label="Recording-session alias" value={sessionAlias} onChange={(event) => setSessionAlias(event.target.value)} placeholder="session-01" /></label><label>Grouping alias <input aria-label="Grouping alias" value={groupAlias} onChange={(event) => setGroupAlias(event.target.value)} placeholder="group-01" /></label><label>Import a newly selected private video <input aria-label="Import private source video" type="file" accept="video/*" onChange={upload} /></label></div><select aria-label="Golden source" value={sourceHash ?? ""} onChange={(event) => { setSourceHash(event.target.value); setSelectedEvent(null); }}>{workspace?.sources.map((item) => <option key={item.source_sha256} value={item.source_sha256}>{item.redacted_alias} ({item.width}x{item.height})</option>)}</select>{source ? <p>Duration {source.duration_pts.toFixed(3)}s; display rotation {source.display_rotation_degrees} degrees. Source metadata stays private.</p> : <p>Import a newly selected video to begin. Historical debug media is unavailable here.</p>}</IslandCard>
    {source ? <IslandCard className="modern-me-panel">{mediaUrl ? <IceMediaPlayer fallbackSrc={mediaUrl} onTimeChange={setTime} seekTime={frame?.pts ?? null} sourceFrame={frame} onStepSourceFrame={step} unavailableFrame={message?.startsWith("The requested source frame") ?? false} /> : <p>Authorizing private video…</p>}<p>Exact source time: {time.toFixed(6)} seconds; source frame: {frameIndex}. Every capture below records this pair from the private source.</p></IslandCard> : null}
    <div className="golden-annotation__grid"><IslandCard className="modern-me-panel"><IslandTitle>Event intervals</IslandTitle><IslandButton onClick={createEvent} disabled={!source}>Add event at current source time</IslandButton><div className="golden-annotation__events">{events.map((event) => <button type="button" className={event.event_id === selectedEvent ? "is-active" : ""} key={event.event_id} onClick={() => setSelectedEvent(event.event_id)}>{event.profile} {event.start_pts.toFixed(2)}-{event.end_pts.toFixed(2)}</button>)}</div></IslandCard>
    <IslandCard className="modern-me-panel"><IslandTitle>Human Ground Truth</IslandTitle>{selected ? <div className="golden-annotation__form"><label>Profile <select value={selected.profile} onChange={(event) => selectProfile(event.target.value as GoldenProfile)}>{profiles.map((profile) => <option key={profile}>{profile}</option>)}</select></label><label>Subtype <input value={selected.subtype ?? ""} onChange={(event) => updateEvent({ subtype: event.target.value || null })} /></label><label>Scene strata (comma-separated) <input aria-label="Scene strata" value={selected.strata.join(", ")} onChange={(event) => updateEvent({ strata: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label><label>Split <select value={selected.split ?? ""} onChange={(event) => updateEvent({ split: (event.target.value || null) as GoldenEvent["split"] })}><option value="">Unassigned</option><option value="development">development</option><option value="validation">validation</option><option value="frozen_test">frozen_test</option></select></label><label>Start PTS <input type="number" step="0.001" value={selected.start_pts} onChange={(event) => updateEvent({ start_pts: numberValue(event.target.value) })} /></label><label>End PTS <input type="number" step="0.001" value={selected.end_pts} onChange={(event) => updateEvent({ end_pts: numberValue(event.target.value) })} /></label><label>Observability <select value={selected.observability} onChange={(event) => updateEvent({ observability: event.target.value as GoldenObservability, ...(event.target.value === "unobservable" ? { jump: null, spin: null, step: null, spiral: null } : {}) })}><option>observable</option><option>uncertain</option><option>unobservable</option></select></label><label><input type="checkbox" checked={selected.main_skater_confirmed} onChange={(event) => updateEvent({ main_skater_confirmed: event.target.checked })} /> Main skater confirmed</label><label>Confidence <input type="number" min="0" max="1" step="0.05" value={selected.annotator_confidence} onChange={(event) => updateEvent({ annotator_confidence: numberValue(event.target.value) })} /></label>
      {selected.observability !== "unobservable" && selected.profile === "jump" ? <section className="golden-annotation__details"><h3>Jump details</h3>{momentEditor("Takeoff", "takeoff", selected.jump?.takeoff)}{momentEditor("Apex", "apex", selected.jump?.apex)}{momentEditor("Landing", "landing", selected.jump?.landing)}{rotationEditor("jump", selected.jump?.rotation)}</section> : null}
      {selected.observability !== "unobservable" && selected.profile === "spin" ? <section className="golden-annotation__details"><h3>Spin details</h3>{phaseEditor("Entry", "entry", selected.spin?.entry)}{phaseEditor("Main", "main", selected.spin?.main)}{phaseEditor("Exit", "exit", selected.spin?.exit)}{rotationEditor("spin", selected.spin?.rotation)}</section> : null}
      {selected.observability !== "unobservable" && intervalProfile ? <section className="golden-annotation__details"><h3>{intervalProfile} details</h3>{phaseEditor("Phase", "phase", intervalDetails?.phase)}{momentEditor("Representative moment", "representative_moment", intervalDetails?.representative_moment)}</section> : null}
      <section className="golden-annotation__details"><h3>Challenge intervals</h3><IslandButton variant="secondary" onClick={addChallenge}>Add challenge interval</IslandButton>{selected.challenge_intervals.map((challenge, index) => <div className="golden-annotation__challenge" key={`${challenge.category}-${index}`}><label>Start <input type="number" step="0.001" value={challenge.start_pts} onChange={(event) => updateChallenge(index, { start_pts: numberValue(event.target.value) })} /></label><label>End <input type="number" step="0.001" value={challenge.end_pts} onChange={(event) => updateChallenge(index, { end_pts: numberValue(event.target.value) })} /></label><label>Category <select value={challenge.category} onChange={(event) => updateChallenge(index, { category: event.target.value as ChallengeInterval["category"] })}>{["crossing", "occlusion", "relock", "exit_reentry", "blur", "compression", "unknown"].map((item) => <option key={item}>{item}</option>)}</select></label><label>Observability <select value={challenge.observability} onChange={(event) => updateChallenge(index, { observability: event.target.value as GoldenObservability })}><option>observable</option><option>uncertain</option><option>unobservable</option></select></label><button type="button" onClick={() => removeChallenge(index)}>Remove</button></div>)}</section></div> : <p>Select or add an event. Suggestions are structurally separate and are never saved from this form.</p>}</IslandCard></div>
    {selected ? <div className="golden-annotation__grid"><IslandCard className="modern-me-panel"><IslandTitle>Skater boxes</IslandTitle><p>Add boxes only when you observed the main skater. Coordinates are normalized: 0 is left/top and 1 is right/bottom.</p><div className="golden-annotation__label-draft"><label>Left <input aria-label="Box left" value={boxDraft.left} onChange={(event) => setBoxDraft({ ...boxDraft, left: event.target.value })} /></label><label>Top <input aria-label="Box top" value={boxDraft.top} onChange={(event) => setBoxDraft({ ...boxDraft, top: event.target.value })} /></label><label>Right <input aria-label="Box right" value={boxDraft.right} onChange={(event) => setBoxDraft({ ...boxDraft, right: event.target.value })} /></label><label>Bottom <input aria-label="Box bottom" value={boxDraft.bottom} onChange={(event) => setBoxDraft({ ...boxDraft, bottom: event.target.value })} /></label><label>State <select value={boxDraft.state} onChange={(event) => setBoxDraft({ ...boxDraft, state: event.target.value as GoldenTrack["state"] })}><option>confirmed</option><option>uncertain</option><option>lost</option></select></label><IslandButton variant="secondary" onClick={addBox}>Add box at current frame</IslandButton></div>{tracks.map((track) => <div className="golden-annotation__saved-label" key={track.label_id}><strong>Frame {track.source_frame_index ?? "legacy"}, {track.pts.toFixed(3)}s</strong><label>State <select value={track.state} onChange={(event) => updateTrack(track.label_id, { state: event.target.value as GoldenTrack["state"] })}><option>confirmed</option><option>uncertain</option><option>lost</option></select></label><label>Left <input value={track.bbox.left} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, left: numberValue(event.target.value) } })} /></label><label>Top <input value={track.bbox.top} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, top: numberValue(event.target.value) } })} /></label><label>Right <input value={track.bbox.right} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, right: numberValue(event.target.value) } })} /></label><label>Bottom <input value={track.bbox.bottom} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, bottom: numberValue(event.target.value) } })} /></label></div>)}</IslandCard>
      <IslandCard className="modern-me-panel"><IslandTitle>Pose joints</IslandTitle><p>Only add joints you can actually observe. Do not add a pose at all when it is unobservable; omission is the correct label.</p><div className="golden-annotation__label-draft"><label>Joint <select value={poseDraft.joint} onChange={(event) => setPoseDraft({ ...poseDraft, joint: event.target.value as typeof joints[number] })}>{joints.map((joint) => <option key={joint}>{joint}</option>)}</select></label><label>X <input aria-label="Pose joint X" value={poseDraft.x} onChange={(event) => setPoseDraft({ ...poseDraft, x: event.target.value })} /></label><label>Y <input aria-label="Pose joint Y" value={poseDraft.y} onChange={(event) => setPoseDraft({ ...poseDraft, y: event.target.value })} /></label><label>Visibility <input aria-label="Pose joint visibility" value={poseDraft.visibility} onChange={(event) => setPoseDraft({ ...poseDraft, visibility: event.target.value })} /></label><label>Observability <select value={poseDraft.observability} onChange={(event) => setPoseDraft({ ...poseDraft, observability: event.target.value as GoldenPose["observability"] })}><option>observable</option><option>uncertain</option></select></label><IslandButton variant="secondary" onClick={addPoseJoint}>Add observed joint at current frame</IslandButton></div>{poses.map((pose) => <div className="golden-annotation__saved-label" key={pose.label_id}><strong>Frame {pose.source_frame_index ?? "legacy"}, {pose.pts.toFixed(3)}s</strong><label>Observability <select value={pose.observability} onChange={(event) => updatePose(pose.label_id, { observability: event.target.value as GoldenPose["observability"] })}><option>observable</option><option>uncertain</option></select></label>{pose.joints.map((joint, index) => <div className="golden-annotation__joint" key={joint.joint}><span>{joint.joint}</span><label>X <input value={joint.x} onChange={(event) => updatePose(pose.label_id, { joints: pose.joints.map((item, itemIndex) => itemIndex === index ? { ...item, x: numberValue(event.target.value) } : item) })} /></label><label>Y <input value={joint.y} onChange={(event) => updatePose(pose.label_id, { joints: pose.joints.map((item, itemIndex) => itemIndex === index ? { ...item, y: numberValue(event.target.value) } : item) })} /></label><label>Visibility <input value={joint.visibility} onChange={(event) => updatePose(pose.label_id, { joints: pose.joints.map((item, itemIndex) => itemIndex === index ? { ...item, visibility: numberValue(event.target.value) } : item) })} /></label></div>)}</div>)}</IslandCard></div> : null}
    <IslandCard className="modern-me-panel"><IslandTitle>Review queue and history</IslandTitle>{review.length ? <ul>{review.map((item) => <li key={`${item.event_id}-${item.status}`}>{item.event_id}: {item.message}</li>)}</ul> : <p>No incomplete, contradictory, or low-confidence labels need review.</p>}<p>Every human-confirmed field records annotator, timestamp, and revision in the private manifest history.</p>{selected ? <div><label>Review evidence <select value={reviewType} onChange={(event) => setReviewType(event.target.value as typeof reviewType)}><option value="delayed_relabel">Delayed re-label (24h+)</option><option value="ambiguous_rotation">Ambiguous rotation double review</option><option value="frozen_identity_crossing">Frozen crossing double review</option></select></label><IslandButton variant="secondary" onClick={() => void attestReview()}>Record eligible review</IslandButton></div> : null}</IslandCard>
    {message ? <p role="alert">{message}</p> : null}<IslandButton onClick={save} disabled={!dirty || saving || offline}>{saving ? "Saving..." : offline ? "Offline - retry when connected" : dirty ? "Save confirmed Ground Truth" : "All changes saved"}</IslandButton>{dirty ? <p>Unsaved changes: leaving this page will ask for confirmation.</p> : null}
  </div>;
}
