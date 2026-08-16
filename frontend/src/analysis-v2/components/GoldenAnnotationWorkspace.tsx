import axios from "axios";
import { ChangeEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import { IceMediaPlayer } from "../../media/IceMediaPlayer";
import { IslandButton, IslandCard, IslandTitle } from "../../modern/IslandSurface";
import { attestGoldenReview, deleteGoldenSource, fetchGoldenReviewQueue, fetchGoldenSourceFrame, fetchGoldenSourceFrameImageUrl, fetchGoldenSourceMediaUrl, fetchGoldenWorkspace, importGoldenSource, saveGoldenAnnotations, updateGoldenSource } from "../api";
import { displayToSource, sourceBoxToDisplay, sourceToDisplay } from "../timebase";
import type { ChallengeInterval, GoldenEvent, GoldenObservability, GoldenPose, GoldenProfile, GoldenReviewItem, GoldenSanitizedExport, GoldenTrack, GoldenWorkspace, IntervalDetails, JumpDetails, PhaseInterval, RotationLabel, SourceMoment, SpinDetails } from "../golden-contracts";

const profiles: GoldenProfile[] = ["jump", "spin", "step", "spiral", "unknown"];
const joints = ["nose", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"] as const;
const uid = (prefix: string) => {
  if (typeof globalThis.crypto?.randomUUID === "function") return `${prefix}-${globalThis.crypto.randomUUID()}`;
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function") globalThis.crypto.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  return `${prefix}-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
};
const numberValue = (value: string) => Number(value);
const profileNames: Record<GoldenProfile, string> = { jump: "跳跃", spin: "旋转", step: "步法", spiral: "燕式/螺旋线", unknown: "暂时不确定" };
const jointConnections: Array<[typeof joints[number], typeof joints[number]]> = [
  ["left_shoulder", "right_shoulder"], ["left_shoulder", "left_elbow"], ["left_elbow", "left_wrist"],
  ["right_shoulder", "right_elbow"], ["right_elbow", "right_wrist"], ["left_shoulder", "left_hip"],
  ["right_shoulder", "right_hip"], ["left_hip", "right_hip"], ["left_hip", "left_knee"],
  ["left_knee", "left_ankle"], ["right_hip", "right_knee"], ["right_knee", "right_ankle"],
];

type Point = { x: number; y: number };
type BBox = { left: number; top: number; right: number; bottom: number };

function blankEvent(sourceHash: string, now: number): GoldenEvent {
  return { event_id: uid("event"), source_sha256: sourceHash, start_pts: Math.max(0, now), end_pts: Math.max(0.1, now + 1), profile: "unknown", subtype: null, observability: "uncertain", strata: [], ambiguity_tags: [], failure_tags: [], annotator_confidence: 0.5, main_skater_confirmed: false, split: null, challenge_intervals: [] };
}

function blankRotation(profile: "jump" | "spin" = "jump"): RotationLabel {
  return { observed_turns_min: 0, observed_turns_max: .5, reported_turns: null, convention: "unknown", observability: "uncertain", definition: profile === "jump" ? "airborne_body_rotation" : "observed_spin_rotation", status: "range", value_turns: null, range_turns: [0, .5], review_start_pts: null, review_end_pts: null, review_method: "source_frame_step" };
}

type GoldenAnnotationWorkspaceProps = { gateTemplate: GoldenSanitizedExport["gate_template"] };

export default function GoldenAnnotationWorkspace({ gateTemplate }: GoldenAnnotationWorkspaceProps) {
  const { parentPin } = useAppMode();
  const g2Minimums = Object.fromEntries(Object.entries(gateTemplate.g2_profile_ranges).map(([profile, [minimum]]) => [profile, minimum])) as Record<string, number>;
  const params = new URLSearchParams(window.location.search);
  const [workspace, setWorkspace] = useState<GoldenWorkspace | null>(null);
  const [review, setReview] = useState<GoldenReviewItem[]>([]);
  const [sourceHash, setSourceHash] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [frame, setFrame] = useState<{ sourceFrameIndex: number; pts: number; duration: number | null } | null>(null);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [sourceFrameImageUrl, setSourceFrameImageUrl] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [message, setMessage] = useState<string | null>(null);
  const [annotator, setAnnotator] = useState("owner");
  const [sessionAlias, setSessionAlias] = useState("");
  const [groupAlias, setGroupAlias] = useState("");
  const [sourceAlias, setSourceAlias] = useState("");
  const [sourceSession, setSourceSession] = useState("");
  const [sourceGroup, setSourceGroup] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [reviewType, setReviewType] = useState<"delayed_relabel" | "ambiguous_rotation" | "frozen_identity_crossing">("delayed_relabel");
  const [boxDraft, setBoxDraft] = useState({ left: "", top: "", right: "", bottom: "", state: "confirmed" as GoldenTrack["state"] });
  const [poseDraft, setPoseDraft] = useState({ joint: "nose" as typeof joints[number], x: "", y: "", visibility: "1", observability: "observable" as GoldenPose["observability"] });
  const [drawingBox, setDrawingBox] = useState(false);
  const [boxStart, setBoxStart] = useState<{ x: number; y: number } | null>(null);
  const [boxPreview, setBoxPreview] = useState<{ left: number; top: number; right: number; bottom: number } | null>(null);
  const editGeneration = useRef(0);
  const pendingFrameSeek = useRef<number | null>(null);
  const markDirty = () => { editGeneration.current += 1; setDirty(true); };

  const load = async (preferredSourceHash?: string) => {
    if (!parentPin) return;
    const requestedGeneration = editGeneration.current;
    try {
      const [next, queue] = await Promise.all([fetchGoldenWorkspace(parentPin), fetchGoldenReviewQueue(parentPin)]);
      if (editGeneration.current !== requestedGeneration) return;
      const requested = next.events.find((event) => event.event_id === params.get("event"));
      setWorkspace(next); setReview(queue);
      setSourceHash((previous) => preferredSourceHash ?? requested?.source_sha256 ?? previous ?? next.sources[0]?.source_sha256 ?? null);
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
  useEffect(() => () => { if (sourceFrameImageUrl) URL.revokeObjectURL(sourceFrameImageUrl); }, [sourceFrameImageUrl]);

  const source = workspace?.sources.find((item) => item.source_sha256 === sourceHash) ?? null;
  const events = useMemo(() => workspace?.events.filter((item) => item.source_sha256 === sourceHash) ?? [], [workspace, sourceHash]);
  const selected = events.find((item) => item.event_id === selectedEvent) ?? null;
  const tracks = useMemo(() => workspace?.tracks.filter((item) => item.event_id === selectedEvent) ?? [], [workspace, selectedEvent]);
  const poses = useMemo(() => workspace?.poses.filter((item) => item.event_id === selectedEvent) ?? [], [workspace, selectedEvent]);
  const exactTimeline = source?.source_timeline?.timestamp_status === "exact" ? source.source_timeline : null;
  const frameIndex = frame?.sourceFrameIndex ?? (exactTimeline?.frames.find((item) => item.pts_sec != null)?.source_frame_index ?? 0);
  const currentMoment = (): SourceMoment | null => frame ? { pts: frame.pts, source_frame_index: frame.sourceFrameIndex } : null;
  useEffect(() => {
    setSourceAlias(source?.redacted_alias ?? "");
    setSourceSession(source?.recording_session_id ?? "");
    setSourceGroup(source?.grouping_id ?? "");
  }, [source?.source_sha256]);

  const currentTracks = tracks.filter((item) => item.source_frame_index === frame?.sourceFrameIndex);
  const currentPoses = poses.filter((item) => item.source_frame_index === frame?.sourceFrameIndex);
  const displayWidth = source && [90, 270].includes(source.display_rotation_degrees) ? source.height : source?.width;
  const displayHeight = source && [90, 270].includes(source.display_rotation_degrees) ? source.width : source?.height;
  const markers = useMemo(() => {
    const output = events.flatMap((event) => [
      { id: `${event.event_id}-start`, timestamp: event.start_pts, label: `${profileNames[event.profile]}开始` },
      { id: `${event.event_id}-end`, timestamp: event.end_pts, label: `${profileNames[event.profile]}结束` },
    ]);
    if (selected?.jump) {
      for (const [key, label] of [["takeoff", "起跳"], ["apex", "最高点"], ["landing", "落冰"]] as const) {
        const moment = selected.jump[key];
        if (moment) output.push({ id: `${selected.event_id}-${key}`, timestamp: moment.pts, label });
      }
    }
    return output;
  }, [events, selected]);

  const pointerPosition = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!source || !displayWidth || !displayHeight) return null;
    const rect = event.currentTarget.getBoundingClientRect();
    const scale = Math.min(rect.width / displayWidth, rect.height / displayHeight);
    const renderedWidth = displayWidth * scale; const renderedHeight = displayHeight * scale;
    const offsetX = (rect.width - renderedWidth) / 2; const offsetY = (rect.height - renderedHeight) / 2;
    const x = (event.clientX - rect.left - offsetX) / renderedWidth;
    const y = (event.clientY - rect.top - offsetY) / renderedHeight;
    if (x < 0 || x > 1 || y < 0 || y > 1) return null;
    return displayToSource({ x, y }, source.display_rotation_degrees);
  };
  const startBox = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drawingBox || !frame) return;
    const point = pointerPosition(event); if (!point) return;
    event.currentTarget.setPointerCapture(event.pointerId); setBoxStart(point); setBoxPreview({ left: point.x, top: point.y, right: point.x, bottom: point.y });
  };
  const moveBox = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drawingBox || !boxStart) return;
    const point = pointerPosition(event); if (!point) return;
    setBoxPreview({ left: Math.min(boxStart.x, point.x), top: Math.min(boxStart.y, point.y), right: Math.max(boxStart.x, point.x), bottom: Math.max(boxStart.y, point.y) });
  };
  const finishBox = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drawingBox || !boxStart) return;
    const point = pointerPosition(event); setBoxStart(null); setDrawingBox(false);
    if (!point) { setBoxPreview(null); return; }
    const bbox = { left: Math.min(boxStart.x, point.x), top: Math.min(boxStart.y, point.y), right: Math.max(boxStart.x, point.x), bottom: Math.max(boxStart.y, point.y) };
    if (bbox.right - bbox.left < .005 || bbox.bottom - bbox.top < .005) { setBoxPreview(null); setMessage("人物框太小，请重新拖拽。"); return; }
    setBoxPreview(bbox); setBoxDraft({ ...boxDraft, left: bbox.left.toFixed(4), top: bbox.top.toFixed(4), right: bbox.right.toFixed(4), bottom: bbox.bottom.toFixed(4) }); setMessage("人物框已画好。确认位置后点击“添加到当前帧”。");
  };

  const annotationOverlay = source && frame && displayWidth && displayHeight ? <svg className={`golden-annotation__overlay${drawingBox ? " is-drawing" : ""}`} viewBox={`0 0 ${displayWidth} ${displayHeight}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="当前帧 Golden 标注叠加结果" onPointerDown={startBox} onPointerMove={moveBox} onPointerUp={finishBox} onPointerCancel={() => { setBoxStart(null); setBoxPreview(null); setDrawingBox(false); }}>
    {currentTracks.map((track) => { const box = sourceBoxToDisplay(track.bbox, source.display_rotation_degrees); return <g key={track.label_id} className={`golden-annotation__track golden-annotation__track--${track.state}`}>
      <rect x={box.left * displayWidth} y={box.top * displayHeight} width={(box.right - box.left) * displayWidth} height={(box.bottom - box.top) * displayHeight} />
      <text x={box.left * displayWidth + 6} y={Math.max(20, box.top * displayHeight - 6)}>主滑手 · {track.state}</text>
    </g>; })}
    {currentPoses.map((pose) => {
      const byName = new Map(pose.joints.map((joint) => [joint.joint, joint]));
      return <g key={pose.label_id} className="golden-annotation__pose">
        {jointConnections.map(([from, to]) => { const left = byName.get(from); const right = byName.get(to); if (!left || !right) return null; const displayLeft = sourceToDisplay(left, source.display_rotation_degrees); const displayRight = sourceToDisplay(right, source.display_rotation_degrees); return <line key={`${from}-${to}`} x1={displayLeft.x * displayWidth} y1={displayLeft.y * displayHeight} x2={displayRight.x * displayWidth} y2={displayRight.y * displayHeight} />; })}
        {pose.joints.map((joint) => { const point = sourceToDisplay(joint, source.display_rotation_degrees); return <circle key={joint.joint} cx={point.x * displayWidth} cy={point.y * displayHeight} r={Math.max(4, displayWidth / 240)} />; })}
      </g>;
    })}
    {boxPreview ? (() => { const box = sourceBoxToDisplay(boxPreview, source.display_rotation_degrees); return <rect className="golden-annotation__box-preview" x={box.left * displayWidth} y={box.top * displayHeight} width={(box.right - box.left) * displayWidth} height={(box.bottom - box.top) * displayHeight} />; })() : null}
  </svg> : null;
  const requireSourceFrame = () => {
    if (frame && frame.pts != null) return true;
    setMessage("Step to the exact private source frame before capturing a moment, box, or pose joint.");
    return false;
  };

  const step = async (direction: -1 | 1) => {
    if (!parentPin || !source) return;
    try {
      const next = await fetchGoldenSourceFrame(parentPin, source.source_sha256, Math.max(0, frameIndex + direction));
      pendingFrameSeek.current = next.pts; setFrame(next); setTime(next.pts);
      try {
        const imageUrl = await fetchGoldenSourceFrameImageUrl(parentPin, source.source_sha256, next.sourceFrameIndex);
        setSourceFrameImageUrl((previous) => { if (previous) URL.revokeObjectURL(previous); return imageUrl; });
      } catch {
        // Exact PTS/frame remains valid when optional image refinement is unavailable.
      }
      setMessage(`已定位到第 ${next.sourceFrameIndex} 帧（${next.pts.toFixed(6)} 秒）。`);
    } catch { setFrame(null); pendingFrameSeek.current = null; setMessage("源帧不可用，没有保存任何修改。"); }
  };
  const beginBoxDrawing = async () => {
    if (!parentPin || !source) return;
    let exactFrame = frame;
    if (!exactFrame) {
      try {
        exactFrame = await fetchGoldenSourceFrame(parentPin, source.source_sha256, frameIndex);
        pendingFrameSeek.current = exactFrame.pts; setFrame(exactFrame); setTime(exactFrame.pts);
      } catch {
        setMessage("无法锁定当前源帧，请先移动播放位置后重试。");
        return;
      }
    }
    setDrawingBox(true); setBoxPreview(null);
    setMessage(`已锁定第 ${exactFrame.sourceFrameIndex} 帧。请直接在上方视频中拖框。`);
  };
  const updateEvent = (change: Partial<GoldenEvent>) => {
    if (!workspace || !selected) return;
    setWorkspace({ ...workspace, events: workspace.events.map((event) => event.event_id === selected.event_id ? { ...event, ...change } : event) }); markDirty();
  };
  const updateTrack = (labelId: string, change: Partial<GoldenTrack>) => {
    if (!workspace) return;
    setWorkspace({ ...workspace, tracks: workspace.tracks.map((item) => item.label_id === labelId ? { ...item, ...change } : item) }); markDirty();
  };
  const updatePose = (labelId: string, change: Partial<GoldenPose>) => {
    if (!workspace) return;
    setWorkspace({ ...workspace, poses: workspace.poses.map((item) => item.label_id === labelId ? { ...item, ...change } : item) }); markDirty();
  };
  const deleteEvent = () => {
    if (!workspace || !selected) return;
    if (!window.confirm(`删除这个${profileNames[selected.profile]}事件及其人物框、姿态点吗？保存后生效。`)) return;
    setWorkspace({
      ...workspace,
      events: workspace.events.filter((event) => event.event_id !== selected.event_id),
      tracks: workspace.tracks.filter((track) => track.event_id !== selected.event_id),
      poses: workspace.poses.filter((pose) => pose.event_id !== selected.event_id),
    });
    setSelectedEvent(null); markDirty(); setMessage("事件已从草稿移除。点击保存后才会写入新 revision。");
  };
  const deleteTrack = (labelId: string) => { if (!workspace) return; setWorkspace({ ...workspace, tracks: workspace.tracks.filter((item) => item.label_id !== labelId) }); markDirty(); };
  const deletePose = (labelId: string) => { if (!workspace) return; setWorkspace({ ...workspace, poses: workspace.poses.filter((item) => item.label_id !== labelId) }); markDirty(); };
  const createEvent = () => {
    if (!workspace || !source) { setMessage("请先选择一个已上传视频。"); return; }
    const event = blankEvent(source.source_sha256, time);
    setWorkspace({ ...workspace, events: [...workspace.events, event] }); setSelectedEvent(event.event_id); markDirty();
    setMessage("动作草稿已创建。请在“人工真值”中选择类型和时间区间，然后添加主滑手框。");
  };
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
  const setRotation = (profile: "jump" | "spin", change: Partial<RotationLabel>) => {
    const current = { ...blankRotation(profile), ...((selected?.[profile] as JumpDetails | SpinDetails | null)?.rotation ?? {}), ...change };
    const normalized: RotationLabel = current.status === "exact"
      ? { ...current, observability: "observable", value_turns: current.reported_turns ?? current.observed_turns_min, reported_turns: current.reported_turns ?? current.observed_turns_min, observed_turns_max: current.reported_turns ?? current.observed_turns_min, observed_turns_min: current.reported_turns ?? current.observed_turns_min, range_turns: null }
      : current.status === "range"
        ? { ...current, observability: "uncertain", value_turns: null, reported_turns: null, range_turns: [current.observed_turns_min, current.observed_turns_max] }
        : { ...current, observability: "unobservable", value_turns: null, reported_turns: null, range_turns: null, observed_turns_min: 0, observed_turns_max: 0 };
    updateEvent({ [profile]: { ...(selected?.[profile] ?? {}), rotation: normalized } });
  };
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
    setWorkspace({ ...workspace, tracks: [...workspace.tracks, { label_id: uid("track"), event_id: selected.event_id, source_sha256: selected.source_sha256, source_frame_index: frame.sourceFrameIndex, pts: frame.pts, bbox, state: boxDraft.state }] }); markDirty(); setBoxPreview(null); setMessage(null);
  };
  const addPoseJoint = () => {
    if (!workspace || !selected) return;
    if (!requireSourceFrame() || !frame) return;
    const x = numberValue(poseDraft.x); const y = numberValue(poseDraft.y); const visibility = numberValue(poseDraft.visibility);
    if (![x, y, visibility].every(Number.isFinite) || x < 0 || x > 1 || y < 0 || y > 1 || visibility < 0 || visibility > 1) { setMessage("Enter observed normalized joint coordinates and visibility (0 to 1) before adding them."); return; }
    const existing = workspace.poses.find((item) => item.event_id === selected.event_id && item.source_frame_index === frame.sourceFrameIndex);
    if (existing && existing.joints.some((joint) => joint.joint === poseDraft.joint)) { setMessage("That joint already exists on this source frame. Edit it below instead."); return; }
    const joint = { joint: poseDraft.joint, x, y, visibility };
    setWorkspace({ ...workspace, poses: existing ? workspace.poses.map((item) => item.label_id === existing.label_id ? { ...item, joints: [...item.joints, joint] } : item) : [...workspace.poses, { label_id: uid("pose"), event_id: selected.event_id, source_sha256: selected.source_sha256, source_frame_index: frame.sourceFrameIndex, pts: frame.pts, observability: poseDraft.observability, joints: [joint] }] }); markDirty(); setMessage(null);
  };
  const save = async () => {
    if (!workspace || !parentPin || offline) return;
    const savedGeneration = editGeneration.current;
    setSaving(true); setMessage(null);
    try {
      const next = await saveGoldenAnnotations(parentPin, { expected_revision: workspace.revision, annotator_alias: annotator, change_note: changeNote.trim() || null, events: workspace.events, tracks: workspace.tracks, poses: workspace.poses });
      if (editGeneration.current === savedGeneration) {
        setWorkspace(next); setDirty(false); setChangeNote(""); setMessage("已保存为新的 Golden revision；旧版本仍保留在审计历史中。");
      } else {
        setWorkspace((current) => current ? { ...current, revision: next.revision } : next);
        setMessage("保存期间又有新修改：较早版本已保存，当前草稿仍需再保存一次。");
      }
      setReview(await fetchGoldenReviewQueue(parentPin));
    }
    catch (error) { const status = axios.isAxiosError(error) ? error.response?.status : 0; setMessage(status === 409 ? "Another save won. Reloaded data is required before retrying." : "Save failed. Nothing was marked confirmed. Check event bounds, profile fields, and label values."); }
    finally { setSaving(false); }
  };
  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file || !parentPin || !workspace) return;
    if (dirty) { setMessage("请先保存当前标注，再上传新视频。"); event.target.value = ""; return; }
    if (!sessionAlias.trim() || !groupAlias.trim()) { setMessage("Enter redacted recording-session and grouping aliases before import."); event.target.value = ""; return; }
    const form = new FormData(); form.set("file", file); form.set("recording_session_id", sessionAlias.trim()); form.set("grouping_id", groupAlias.trim()); form.set("redacted_alias", `source-${workspace.sources.length + 1}`); form.set("expected_revision", String(workspace.revision)); form.set("annotator_alias", annotator);
    try { const imported = await importGoldenSource(parentPin, form); await load(imported.source_sha256); setSelectedEvent(null); setTime(0); setFrame(null); setMessage("视频已导入。下一步：点击“在当前时间新建动作”，然后标动作类型和区间。"); } catch { setMessage("导入失败，没有注册私有视频。请检查格式或网络后重试。"); }
  };
  const saveSourceMetadata = async () => {
    if (dirty) { setMessage("请先保存当前动作标注，再修改视频信息。"); return; }
    if (!workspace || !source || !parentPin || !sourceAlias.trim() || !sourceSession.trim() || !sourceGroup.trim()) { setMessage("视频别名、录制场次和分组都不能为空。"); return; }
    try {
      const next = await updateGoldenSource(parentPin, source.source_sha256, { expected_revision: workspace.revision, annotator_alias: annotator, redacted_alias: sourceAlias.trim(), recording_session_id: sourceSession.trim(), grouping_id: sourceGroup.trim() });
      setWorkspace(next); setMessage("视频信息已保存。录制场次和分组将用于防止数据泄漏到不同 split。");
    } catch { setMessage("视频信息保存失败；如 revision 已变化，请刷新后重试。"); }
  };
  const deleteSource = async () => {
    if (!workspace || !source || !parentPin) return;
    if (dirty) { setMessage("请先保存或刷新当前动作标注，再删除视频。"); return; }
    const count = workspace.events.filter((event) => event.source_sha256 === source.source_sha256).length;
    if (!window.confirm(`确定删除“${source.redacted_alias}”吗？将同时删除 ${count} 个事件及其 bbox/pose 标签。历史 revision 仍保留，但视频文件不可恢复。`)) return;
    try {
      const next = await deleteGoldenSource(parentPin, source.source_sha256, { expected_revision: workspace.revision, annotator_alias: annotator, confirmation: "delete_source_and_labels" });
      const nextSource = next.sources[0]?.source_sha256 ?? null;
      setWorkspace(next); setSourceHash(nextSource); setSelectedEvent(null); setFrame(null); setTime(0); setDirty(false); setMessage("视频及当前标签已删除；旧评估结果已失效。");
    } catch { setMessage("删除失败，数据保持不变。请刷新 revision 后重试。"); }
  };
  const attestReview = async () => { if (!parentPin || !selected) return; const rotation = selected.jump?.rotation ?? selected.spin?.rotation; try { await attestGoldenReview(parentPin, selected.event_id, { reviewer_alias: annotator, review_type: reviewType, ...(reviewType === "ambiguous_rotation" && rotation ? { rotation_definition: rotation.definition, review_start_pts: rotation.review_start_pts ?? selected.start_pts, review_end_pts: rotation.review_end_pts ?? selected.end_pts, review_method: "source_frame_step" as const } : {}) }); await load(); setMessage("Review attestation recorded separately from Ground Truth."); } catch { setMessage("Review attestation was not eligible or could not be recorded."); } };

  const momentEditor = (label: string, key: "takeoff" | "apex" | "landing" | "representative_moment", value?: SourceMoment | null) => <div className="golden-annotation__capture"><span>{label}：{value ? `${value.pts.toFixed(6)} 秒 / 帧 ${value.source_frame_index ?? "未提供"}` : "未设置"}</span><IslandButton variant="secondary" onClick={() => setMoment(key)}>使用当前精确帧</IslandButton></div>;
  const phaseEditor = (label: string, key: "entry" | "main" | "exit" | "phase", value?: PhaseInterval | null) => <fieldset className="golden-annotation__phase"><legend>{label}</legend><label>开始（秒）<input aria-label={`${label} start PTS`} type="number" step="0.001" value={value?.start_pts ?? selected?.start_pts ?? 0} onChange={(event) => setPhase(key, "start_pts", numberValue(event.target.value))} /></label><label>结束（秒）<input aria-label={`${label} end PTS`} type="number" step="0.001" value={value?.end_pts ?? selected?.end_pts ?? 0} onChange={(event) => setPhase(key, "end_pts", numberValue(event.target.value))} /></label><IslandButton variant="secondary" onClick={() => capturePhaseStart(key)}>从当前时间开始</IslandButton></fieldset>;
  const rotationEditor = (profile: "jump" | "spin", value?: RotationLabel | null) => { const rotation = { ...blankRotation(profile), ...(value ?? {}) }; return <fieldset className="golden-annotation__rotation"><legend>旋转圈数 · 源帧逐帧复核</legend><p>clear 存 exact，partial 存 interval，否则存 unobservable；不要混用空中身体转体与比赛命名。</p><label>标签定义<select aria-label={`${profile} rotation definition`} value={rotation.definition} onChange={(event) => { const definition = event.target.value as RotationLabel["definition"]; setRotation(profile, { definition, convention: definition === "competition_naming" ? "axel_includes_forward_takeoff" : definition === "airborne_body_rotation" ? "non_axel_airborne" : "unknown" }); }}><option value="airborne_body_rotation">空中身体转体</option><option value="competition_naming">比赛命名（Axel 约定）</option>{profile === "spin" ? <option value="observed_spin_rotation">旋转主体观察圈数</option> : null}</select></label><label>标签状态<select aria-label={`${profile} rotation status`} value={rotation.status} onChange={(event) => setRotation(profile, { status: event.target.value as RotationLabel["status"] })}><option value="exact">clear · 精确值</option><option value="range">partial · 区间</option><option value="unobservable">画面不足 · 不判断</option></select></label>{rotation.status !== "unobservable" ? <><label>最少圈数<input aria-label={`${profile} minimum turns`} type="number" min="0" max="12" step="0.25" value={rotation.observed_turns_min} onChange={(event) => setRotation(profile, { observed_turns_min: numberValue(event.target.value) })} /></label><label>最多圈数<input aria-label={`${profile} maximum turns`} type="number" min="0" max="12" step="0.25" value={rotation.observed_turns_max} onChange={(event) => setRotation(profile, { observed_turns_max: numberValue(event.target.value) })} /></label></> : null}{rotation.status === "exact" ? <label>明确圈数<input aria-label={`${profile} reported turns`} type="number" min="0" max="12" step="0.25" value={rotation.reported_turns ?? rotation.observed_turns_min} onChange={(event) => setRotation(profile, { reported_turns: numberValue(event.target.value) })} /></label> : null}<label>复核开始 PTS<input aria-label={`${profile} rotation review start PTS`} type="number" step="0.001" value={rotation.review_start_pts ?? selected?.start_pts ?? 0} onChange={(event) => setRotation(profile, { review_start_pts: numberValue(event.target.value) })} /></label><label>复核结束 PTS<input aria-label={`${profile} rotation review end PTS`} type="number" step="0.001" value={rotation.review_end_pts ?? selected?.end_pts ?? 0} onChange={(event) => setRotation(profile, { review_end_pts: numberValue(event.target.value) })} /></label></fieldset>; };

  const gateGuidance = `G1 ${gateTemplate.required_source_videos}/${gateTemplate.required_valid_events}; G2 ${gateTemplate.g2_event_range[0]}-${gateTemplate.g2_event_range[1]}; Pose ${gateTemplate.pose_frame_range[0]}-${gateTemplate.pose_frame_range[1]}; profiles jump ${g2Minimums.jump}, spin ${g2Minimums.spin}, step ${g2Minimums.step}, spiral ${g2Minimums.spiral}`;
  return <div className="golden-annotation" data-testid="golden-annotation-workspace">
    <p data-testid="golden-gate-guidance">{gateGuidance}</p>
    <IslandCard className="modern-me-panel golden-annotation__guide" tone="sky"><IslandTitle>上传以后做什么？</IslandTitle><ol><li className={source ? "is-done" : ""}><strong>选择视频</strong><span>从下拉框打开刚上传或以前上传的视频。</span></li><li className={selected ? "is-done" : ""}><strong>新建一个动作</strong><span>播放到动作附近，点击“在当前时间新建动作”。</span></li><li className={selected?.profile !== "unknown" ? "is-done" : ""}><strong>标类型和区间</strong><span>选择跳跃、旋转、步法或燕式，并填写开始/结束时间。</span></li><li className={selected?.main_skater_confirmed ? "is-done" : ""}><strong>确认主滑手</strong><span>勾选主滑手，在动作中选 3-8 个清晰帧添加人物框。</span></li><li className={!dirty && Boolean(selected) ? "is-done" : ""}><strong>保存</strong><span>补动作专属时刻后保存。Pose 只需少量抽样，可以暂不标。</span></li></ol><p><strong>普通事件最少要标：</strong>动作区间、类型、可观察性、主滑手、动作专属时刻，以及 3-8 个主滑手框。场景标签、困难区间和 Pose 按实际情况补充。</p><p><strong>当前目标是 36 个真实动作事件。</strong>不用为了凑 60-80 个而重复素材；后续缺哪类，再补拍新的场次或难例。</p></IslandCard>
    <IslandCard className="modern-me-panel"><IslandTitle>1. 视频库</IslandTitle><div className="golden-annotation__source-fields"><label>标注人<input value={annotator} onChange={(event) => setAnnotator(event.target.value)} /></label><label>新视频录制场次<input aria-label="Recording-session alias" value={sessionAlias} onChange={(event) => setSessionAlias(event.target.value)} placeholder="例如 session-01" /></label><label>新视频分组<input aria-label="Grouping alias" value={groupAlias} onChange={(event) => setGroupAlias(event.target.value)} placeholder="同一次拍摄填相同分组" /></label><label>上传新视频<input aria-label="Import private source video" type="file" accept="video/*" onChange={upload} /></label></div><label>已上传视频<select aria-label="Golden source" value={sourceHash ?? ""} onChange={(event) => { setSourceHash(event.target.value); setSelectedEvent(null); setFrame(null); setTime(0); }}>{workspace?.sources.map((item) => <option key={item.source_sha256} value={item.source_sha256}>{item.redacted_alias} · {workspace.events.filter((entry) => entry.source_sha256 === item.source_sha256).length} 个动作</option>)}</select></label>{source ? <><div className="golden-annotation__source-edit"><label>显示名称<input value={sourceAlias} onChange={(event) => setSourceAlias(event.target.value)} /></label><label>录制场次<input value={sourceSession} onChange={(event) => setSourceSession(event.target.value)} /></label><label>分组<input value={sourceGroup} onChange={(event) => setSourceGroup(event.target.value)} /></label></div><div className="golden-annotation__actions"><IslandButton variant="secondary" onClick={() => void saveSourceMetadata()}>保存视频信息</IslandButton><IslandButton variant="quiet" className="golden-annotation__danger" onClick={() => void deleteSource()}>删除此视频和标签</IslandButton></div><p>时长 {source.duration_pts.toFixed(3)} 秒，{source.width}x{source.height}。私有路径不会显示或导出。</p></> : <p>请先上传一个新选择的视频。历史 debug 素材不能用于 V2 Golden。</p>}</IslandCard>
    {source ? <IslandCard className="modern-me-panel"><IslandTitle>2. 播放并观察标注</IslandTitle>{mediaUrl ? <IceMediaPlayer className={`golden-annotation__player${displayWidth && displayHeight && displayHeight > displayWidth ? " is-portrait" : " is-landscape"}`} fallbackSrc={mediaUrl} markers={markers} aspectRatio={displayWidth && displayHeight ? displayWidth / displayHeight : undefined} onTimeChange={(value) => { const pending = pendingFrameSeek.current; if (pending != null && Math.abs(value - pending) > .04) return; pendingFrameSeek.current = null; setTime(value); if (frame && Math.abs(frame.pts - value) > Math.max(frame.duration ?? .04, .04)) setFrame(null); }} seekTime={frame?.pts ?? null} sourceFrame={frame} onStepSourceFrame={step} unavailableFrame={message?.startsWith("源帧不可用") ?? false} overlay={annotationOverlay} /> : <p>正在授权私有视频…</p>}{sourceFrameImageUrl ? <img src={sourceFrameImageUrl} alt="Exact source frame refinement" className="mt-3 max-h-64 w-auto rounded" /> : null}<p>当前时间 {time.toFixed(6)} 秒；源帧 {frameIndex}。用上一帧/下一帧锁定精确帧后，当前帧的主滑手框和 Pose 会叠加显示。</p><div className="golden-annotation__legend"><span className="is-confirmed">主滑手框</span><span className="is-pose">Pose 抽样</span><span>时间轴圆点：动作与关键时刻</span></div></IslandCard> : null}
    <div className="golden-annotation__grid"><IslandCard className="modern-me-panel"><IslandTitle>3. 动作记录</IslandTitle><IslandButton onClick={createEvent} disabled={!source}>在当前时间新建动作</IslandButton><div className="golden-annotation__events">{events.map((event) => <button type="button" className={event.event_id === selectedEvent ? "is-active" : ""} key={event.event_id} onClick={() => setSelectedEvent(event.event_id)}>{profileNames[event.profile]} {event.start_pts.toFixed(2)}-{event.end_pts.toFixed(2)} 秒</button>)}</div>{selected ? <IslandButton variant="quiet" className="golden-annotation__danger" onClick={deleteEvent}>删除当前动作</IslandButton> : <p>{events.length ? "请选择上方已有动作继续编辑。" : "还没有动作。播放到动作附近后，点击上方按钮创建第一个动作。"}</p>}</IslandCard>
    <IslandCard className="modern-me-panel"><IslandTitle>4. 人工真值</IslandTitle>{selected ? <div className="golden-annotation__form"><label>动作类型<select aria-label="Profile" value={selected.profile} onChange={(event) => selectProfile(event.target.value as GoldenProfile)}>{profiles.map((profile) => <option key={profile} value={profile}>{profileNames[profile]}</option>)}</select></label><label>动作细分（可选）<input value={selected.subtype ?? ""} onChange={(event) => updateEvent({ subtype: event.target.value || null })} placeholder="不确定可留空" /></label><label>场景标签（可选）<input aria-label="Scene strata" value={selected.strata.join(", ")} onChange={(event) => updateEvent({ strata: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="normal, multi-skater, blur" /></label><label>数据分区<select value={selected.split ?? ""} onChange={(event) => updateEvent({ split: (event.target.value || null) as GoldenEvent["split"] })}><option value="">稍后分配</option><option value="development">开发集</option><option value="validation">验证集</option><option value="frozen_test">冻结测试集</option></select></label><label>动作开始（秒）<input type="number" step="0.001" value={selected.start_pts} onChange={(event) => updateEvent({ start_pts: numberValue(event.target.value) })} /></label><label>动作结束（秒）<input type="number" step="0.001" value={selected.end_pts} onChange={(event) => updateEvent({ end_pts: numberValue(event.target.value) })} /></label><label>可观察性<select value={selected.observability} onChange={(event) => updateEvent({ observability: event.target.value as GoldenObservability, ...(event.target.value === "unobservable" ? { jump: null, spin: null, step: null, spiral: null } : {}) })}><option value="observable">看得清</option><option value="uncertain">不太确定</option><option value="unobservable">画面不足，无法判断</option></select></label><label><input type="checkbox" checked={selected.main_skater_confirmed} onChange={(event) => updateEvent({ main_skater_confirmed: event.target.checked })} /> 已确认画面中的主滑手</label><label>我的把握（0-1）<input type="number" min="0" max="1" step="0.05" value={selected.annotator_confidence} onChange={(event) => updateEvent({ annotator_confidence: numberValue(event.target.value) })} /></label>
      {selected.observability !== "unobservable" && selected.profile === "jump" ? <section className="golden-annotation__details"><h3>跳跃关键时刻</h3>{momentEditor("起跳", "takeoff", selected.jump?.takeoff)}{momentEditor("最高点", "apex", selected.jump?.apex)}{momentEditor("落冰", "landing", selected.jump?.landing)}{rotationEditor("jump", selected.jump?.rotation)}</section> : null}
      {selected.observability !== "unobservable" && selected.profile === "spin" ? <section className="golden-annotation__details"><h3>旋转阶段</h3>{phaseEditor("进入", "entry", selected.spin?.entry)}{phaseEditor("主体", "main", selected.spin?.main)}{phaseEditor("退出", "exit", selected.spin?.exit)}{rotationEditor("spin", selected.spin?.rotation)}</section> : null}
      {selected.observability !== "unobservable" && intervalProfile ? <section className="golden-annotation__details"><h3>{profileNames[intervalProfile]}阶段</h3>{phaseEditor("动作阶段", "phase", intervalDetails?.phase)}{momentEditor("代表时刻", "representative_moment", intervalDetails?.representative_moment)}</section> : null}
      <section className="golden-annotation__details"><h3>困难区间（可选）</h3><IslandButton variant="secondary" onClick={addChallenge}>添加困难区间</IslandButton>{selected.challenge_intervals.map((challenge, index) => <div className="golden-annotation__challenge" key={`${challenge.category}-${index}`}><label>开始<input type="number" step="0.001" value={challenge.start_pts} onChange={(event) => updateChallenge(index, { start_pts: numberValue(event.target.value) })} /></label><label>结束<input type="number" step="0.001" value={challenge.end_pts} onChange={(event) => updateChallenge(index, { end_pts: numberValue(event.target.value) })} /></label><label>类型<select value={challenge.category} onChange={(event) => updateChallenge(index, { category: event.target.value as ChallengeInterval["category"] })}>{["crossing", "occlusion", "relock", "exit_reentry", "blur", "compression", "unknown"].map((item) => <option key={item}>{item}</option>)}</select></label><label>可观察性<select value={challenge.observability} onChange={(event) => updateChallenge(index, { observability: event.target.value as GoldenObservability })}><option>observable</option><option>uncertain</option><option>unobservable</option></select></label><button type="button" onClick={() => removeChallenge(index)}>移除</button></div>)}</section></div> : <p>请先选择或新建一个动作。这里保存的是人工真值，不会自动接受算法建议。</p>}</IslandCard></div>
    {selected ? <div className="golden-annotation__grid"><IslandCard className="modern-me-panel"><IslandTitle>5. 主滑手框（每个动作 3-8 帧）</IslandTitle><p>暂停在清晰画面后点击下方按钮，系统会自动锁定当前源帧。然后直接在上方视频中用鼠标、触控笔或手指拖框。</p><IslandButton variant="secondary" onClick={() => void beginBoxDrawing()}>{drawingBox ? "正在等待画框…" : "锁定当前画面并画主滑手框"}</IslandButton><div className="golden-annotation__label-draft"><label>左<input aria-label="Box left" value={boxDraft.left} onChange={(event) => setBoxDraft({ ...boxDraft, left: event.target.value })} /></label><label>上<input aria-label="Box top" value={boxDraft.top} onChange={(event) => setBoxDraft({ ...boxDraft, top: event.target.value })} /></label><label>右<input aria-label="Box right" value={boxDraft.right} onChange={(event) => setBoxDraft({ ...boxDraft, right: event.target.value })} /></label><label>下<input aria-label="Box bottom" value={boxDraft.bottom} onChange={(event) => setBoxDraft({ ...boxDraft, bottom: event.target.value })} /></label><label>状态<select value={boxDraft.state} onChange={(event) => setBoxDraft({ ...boxDraft, state: event.target.value as GoldenTrack["state"] })}><option value="confirmed">确认是主滑手</option><option value="uncertain">不确定</option><option value="lost">丢失</option></select></label><IslandButton variant="secondary" onClick={addBox}>添加到当前帧</IslandButton></div>{tracks.map((track) => <div className="golden-annotation__saved-label" key={track.label_id}><strong>帧 {track.source_frame_index ?? "旧数据"}，{track.pts.toFixed(3)} 秒</strong><label>状态<select value={track.state} onChange={(event) => updateTrack(track.label_id, { state: event.target.value as GoldenTrack["state"] })}><option>confirmed</option><option>uncertain</option><option>lost</option></select></label><label>左<input value={track.bbox.left} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, left: numberValue(event.target.value) } })} /></label><label>上<input value={track.bbox.top} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, top: numberValue(event.target.value) } })} /></label><label>右<input value={track.bbox.right} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, right: numberValue(event.target.value) } })} /></label><label>下<input value={track.bbox.bottom} onChange={(event) => updateTrack(track.label_id, { bbox: { ...track.bbox, bottom: numberValue(event.target.value) } })} /></label><button type="button" className="golden-annotation__danger" onClick={() => deleteTrack(track.label_id)}>删除</button></div>)}</IslandCard>
      <IslandCard className="modern-me-panel"><IslandTitle>6. Pose 抽样（可选）</IslandTitle><p>不需要每帧标，也不需要每个事件都标。只在少量清晰代表帧添加看得见的关节；看不清就留空。</p><div className="golden-annotation__label-draft"><label>关节<select value={poseDraft.joint} onChange={(event) => setPoseDraft({ ...poseDraft, joint: event.target.value as typeof joints[number] })}>{joints.map((joint) => <option key={joint}>{joint}</option>)}</select></label><label>X<input aria-label="Pose joint X" value={poseDraft.x} onChange={(event) => setPoseDraft({ ...poseDraft, x: event.target.value })} /></label><label>Y<input aria-label="Pose joint Y" value={poseDraft.y} onChange={(event) => setPoseDraft({ ...poseDraft, y: event.target.value })} /></label><label>可见度<input aria-label="Pose joint visibility" value={poseDraft.visibility} onChange={(event) => setPoseDraft({ ...poseDraft, visibility: event.target.value })} /></label><label>可观察性<select value={poseDraft.observability} onChange={(event) => setPoseDraft({ ...poseDraft, observability: event.target.value as GoldenPose["observability"] })}><option>observable</option><option>uncertain</option></select></label><IslandButton variant="secondary" onClick={addPoseJoint}>添加到当前帧</IslandButton></div>{poses.map((pose) => <div className="golden-annotation__saved-label" key={pose.label_id}><strong>帧 {pose.source_frame_index ?? "旧数据"}，{pose.pts.toFixed(3)} 秒</strong><label>可观察性<select value={pose.observability} onChange={(event) => updatePose(pose.label_id, { observability: event.target.value as GoldenPose["observability"] })}><option>observable</option><option>uncertain</option></select></label><button type="button" className="golden-annotation__danger" onClick={() => deletePose(pose.label_id)}>删除整帧 Pose</button>{pose.joints.map((joint, index) => <div className="golden-annotation__joint" key={joint.joint}><span>{joint.joint}</span><label>X<input value={joint.x} onChange={(event) => updatePose(pose.label_id, { joints: pose.joints.map((item, itemIndex) => itemIndex === index ? { ...item, x: numberValue(event.target.value) } : item) })} /></label><label>Y<input value={joint.y} onChange={(event) => updatePose(pose.label_id, { joints: pose.joints.map((item, itemIndex) => itemIndex === index ? { ...item, y: numberValue(event.target.value) } : item) })} /></label><label>可见度<input value={joint.visibility} onChange={(event) => updatePose(pose.label_id, { joints: pose.joints.map((item, itemIndex) => itemIndex === index ? { ...item, visibility: numberValue(event.target.value) } : item) })} /></label></div>)}</div>)}</IslandCard></div> : null}
    <IslandCard className="modern-me-panel"><IslandTitle>复核与修订</IslandTitle>{review.length ? <ul>{review.map((item) => <li key={`${item.event_id}-${item.status}`}>{item.event_id}: {item.message}</li>)}</ul> : <p>当前没有待处理的低把握、矛盾或二次复核项目。</p>}<p>每次保存都会创建新的 revision；历史标注不会被静默覆盖。</p>{selected ? <div className="golden-annotation__review"><label>复核类型<select value={reviewType} onChange={(event) => setReviewType(event.target.value as typeof reviewType)}><option value="delayed_relabel">24 小时后延迟复标</option><option value="ambiguous_rotation">模糊旋转二次复核</option><option value="frozen_identity_crossing">冻结集交叉场景复核</option></select></label><IslandButton variant="secondary" onClick={() => void attestReview()}>记录合格复核</IslandButton></div> : null}</IslandCard>
    <IslandCard className="modern-me-panel golden-annotation__save"><IslandTitle>保存当前 Golden</IslandTitle><label>修改说明（可选）<input value={changeNote} onChange={(event) => setChangeNote(event.target.value)} placeholder="例如：修正落冰帧" /></label>{message ? <p role="alert">{message}</p> : null}<IslandButton onClick={save} disabled={!dirty || saving || offline}>{saving ? "正在保存…" : offline ? "离线，联网后重试" : dirty ? "保存人工真值" : "当前修改已保存"}</IslandButton>{dirty ? <p>有未保存修改。离开页面前浏览器会提醒你。</p> : null}</IslandCard>
  </div>;
}
