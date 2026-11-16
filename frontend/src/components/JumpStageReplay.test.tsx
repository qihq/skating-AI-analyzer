import { forwardRef, useImperativeHandle } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AnalysisDetail } from "../api/client";
import type { ExperienceEvent } from "../analysis-v2/contracts";
import { buildCurrentKeyframeEvidenceItems } from "../utils/keyframeEvidence";
import { analysisMediaMarkers } from "../media/analysisMarkers";
import ActionPhaseStrip from "./ActionPhaseStrip";

const { seek } = vi.hoisted(() => ({ seek: vi.fn() }));
// Deliberate player substitute: these tests verify interaction wiring, not media playback.
vi.mock("../media/IceMediaPlayer", () => ({ IceMediaPlayer: forwardRef((_, ref) => {
  useImperativeHandle(ref, () => ({ seek })); return <div data-testid="player-substitute" />;
}) }));
afterEach(() => { cleanup(); seek.mockClear(); });
const node = (frame: string, analysis: number, playback: number) => ({ status: "candidate", frame_id: frame,
  timestamp: analysis, playback_timestamp: playback, source_timestamp: playback, time_source: "bound_source_pts",
  image_ref: { kind: "analysis_frame", frame_id: frame }, source: "key_frame_candidates", confidence: .7,
  reason: "weak_geometry_candidate_not_confirmed_contact" });
export function record(): AnalysisDetail { return {
  id: "generic", analysis_profile: "jump", facts_authority: "legacy", source_duration_sec: 10,
  bio_data: { jump_stage_contract: "tal-evidence.v1", key_frames: { T: "frame_9999" },
    jump_stages: { takeoff: node("frame_0003", 1.5, 3), apex: node("frame_0005", 2.5, 5), landing: node("frame_0007", 3.5, 7),
      "pull-in": { status: "not_implemented", frame_id: null, reason: "stage_evidence_extractor_not_implemented" },
      rotation: { status: "not_implemented", frame_id: null, reason: "stage_evidence_extractor_not_implemented" } },
    jump_measurements: { candidate_interval: { status: "candidate", value: 2, unit: "s", reason: "candidate_interval_not_confirmed_air_time" },
      air_time: { status: "unavailable", value: null, reason: "independent_contact_boundaries_and_speed_required" },
      physical_height: { status: "unavailable", value: null, reason: "calibration_reference_plane_and_method_required" } } },
  video_temporal_diagnostics: { selected_semantic_frames: [{frame_id: "frame_9999", timestamp: 9, phase_code: "T"}] }
} as unknown as AnalysisDetail; }
describe("saved five-node replay", () => {
 it("reads only authoritative stages; never backfills missing T or adds old semantic markers", () => {
  const a=record(); (a.bio_data!.jump_stages as any).takeoff = {status:"unavailable", reason:"stage_anchor_support_invalid"};
  const items=buildCurrentKeyframeEvidenceItems(a);
  expect(items.map(i=>i.key)).toEqual(["takeoff","pull-in","apex","rotation","landing"]);
  expect(items[0].frameId).toBeNull(); expect(items[0].status).toBe("unavailable");
  expect(analysisMediaMarkers(a).map(m=>m.timestamp)).toEqual([5,7]);
 });
 it("renders saved frames and seeks playback seconds; re-opening preserves status/time/reason/null", () => {
  const a=record(); const view=render(<ActionPhaseStrip analysis={a} pose={null} />);
  const snapshot=()=>screen.getAllByRole("article").map(e=>e.textContent);
  expect(screen.getAllByRole("article").map(e=>within(e).getByRole("heading",{level:3}).textContent)).toEqual(["起跳","收紧","最高点","旋转","落冰"]);
  expect(screen.getByAltText("起跳关键帧")).toHaveAttribute("src", "/api/frames/generic/frame_0003.jpg?saved_only=true");
  fireEvent.click(screen.getByRole("button",{name:/查看起跳/})); expect(seek).toHaveBeenCalledWith(3,{play:true});
  expect(screen.getByRole("button",{name:/查看收紧/})).toBeDisabled();
  expect(screen.getAllByRole("listitem").find(e=>e.textContent?.startsWith("起落候选区间"))).toHaveTextContent("2.000s");
  expect(screen.getAllByRole("listitem").find(e=>e.textContent?.startsWith("确认腾空时间"))).toHaveTextContent("不可用");
  expect(screen.getByText(/物理高度/)).not.toHaveTextContent("0 cm");
  const before=snapshot(); view.unmount(); render(<ActionPhaseStrip analysis={JSON.parse(JSON.stringify(a))} pose={null} />);
  expect(snapshot()).toEqual(before);
 });
 it("keeps an image without time, rejects out-of-range mapping and reports image failures", () => {
  const a=record(); const nodes=a.bio_data!.jump_stages as any;
  nodes.takeoff.playback_timestamp=null; nodes.apex.playback_timestamp=12;
  render(<ActionPhaseStrip analysis={a} pose={null} />);
  expect(screen.getByAltText("起跳关键帧")).toBeInTheDocument();
  expect(screen.getByRole("button",{name:/查看起跳/})).toBeDisabled();
  expect(screen.getByRole("button",{name:/查看最高点/})).toBeDisabled();
  fireEvent.error(screen.getByAltText("落冰关键帧")); expect(within(screen.getAllByRole("article")[4]).getByText("原帧不可用")).toBeInTheDocument();
  expect(seek).not.toHaveBeenCalled();
 });
 it("keeps independent V2 moments authoritative even beside a legacy TAL payload", () => {
  const event={eventId:"other",profile:"jump",moments:{moments:[],expectedKeys:[],missingKeys:[],completeness:"incomplete",definitionVersion:"jump.v1"}} as unknown as ExperienceEvent;
  render(<ActionPhaseStrip analysis={record()} event={event} pose={null} />);
  expect(screen.queryByAltText("起跳关键帧")).not.toBeInTheDocument();
  expect(screen.queryByText(/起落候选区间/)).not.toBeInTheDocument();
 });
});
