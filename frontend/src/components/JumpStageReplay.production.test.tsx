// The Vitest Node runner provides fs; browser application types deliberately omit Node.
// @ts-expect-error Node builtin is available only in this test runner.
import { readFileSync } from "node:fs";
import { forwardRef, useImperativeHandle } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import * as experienceApi from "../analysis-v2/api";
import { decodeAnalysisExperienceV2 } from "../analysis-v2/contracts";
import { savedJumpReplayScope } from "../analysis-v2/useSavedJumpReplay";
import ModernAnalysisDetail from "../modern/ModernAnalysisDetail";
import AnalysisExperienceReport from "../analysis-v2/components/AnalysisExperienceReport";
import ActionPhaseStrip from "./ActionPhaseStrip";
const { seek } = vi.hoisted(() => ({ seek: vi.fn() }));
// Player substitute only: no browser/video playback is claimed by this suite.
vi.mock("../media/IceMediaPlayer", () => ({ IceMediaPlayer: forwardRef((_,ref) => {
 useImperativeHandle(ref,()=>({seek})); return <div data-testid="player-substitute"/>;
}) }));
vi.mock("../api/client", async importOriginal => ({...await importOriginal<typeof import("../api/client")>(),fetchAnalysis:vi.fn(),fetchAnalysisPose:vi.fn()}));
vi.mock("../analysis-v2/api", async importOriginal => ({...await importOriginal<typeof import("../analysis-v2/api")>(),fetchAnalysisExperienceV2:vi.fn()}));
vi.mock("./AppModeContext",()=>({useAppMode:()=>({isParentMode:false,parentPin:null})}));
const fixturePath=(globalThis as unknown as {process:{env:Record<string,string|undefined>}}).process.env.JUMP_REPLAY_FIXTURE;
const payloads=fixturePath ? JSON.parse(readFileSync(fixturePath,"utf8")) : null;
afterEach(()=>{cleanup();vi.clearAllMocks();});
describe.skipIf(!fixturePath)("production builder/report SQLite GET -> rendered saved replay",()=>{
 beforeEach(()=>{vi.mocked(client.fetchAnalysis).mockImplementation(async id=>structuredClone(payloads[id].detail));
  vi.mocked(client.fetchAnalysisPose).mockImplementation(async id=>structuredClone(payloads[id].pose));
  vi.mocked(experienceApi.fetchAnalysisExperienceV2).mockImplementation(async id=>decodeAnalysisExperienceV2(structuredClone(payloads[id].experience)));});
 it.each(["modern","report"])("opens the actual %s result route and reopens the same saved payload",async kind=>{
  const id="synthetic-slow-jump";const result=payloads[id];const node=result.detail.bio_data.jump_stages.takeoff;
  const open=()=>render(<MemoryRouter initialEntries={["/analysis/"+id+"?view=moments"]}><Routes><Route path="/analysis/:id" element={kind==="modern"?<ModernAnalysisDetail/>:<AnalysisExperienceReport/>}/></Routes></MemoryRouter>);
  const view=open(); await screen.findByAltText("起跳关键帧");
  expect(screen.getAllByRole("heading",{level:3}).map(e=>e.textContent)).toEqual(expect.arrayContaining(["起跳","收紧","最高点","旋转","落冰"]));
  expect(screen.getByAltText("起跳关键帧")).toHaveAttribute("src","/api/frames/"+id+"/"+node.frame_id+".jpg?saved_only=true");
  fireEvent.click(screen.getByRole("button",{name:/查看起跳/})); expect(seek).toHaveBeenLastCalledWith(node.playback_timestamp,{play:true});
  expect(node.playback_timestamp).not.toEqual(node.timestamp);
  expect(result.image_reads[node.frame_id+".jpg"]).toMatch(/^[a-f0-9]{64}$/);
  expect(screen.getByRole("button",{name:/查看收紧/})).toBeDisabled();expect(screen.getByRole("button",{name:/查看旋转/})).toBeDisabled();
  const snapshot=()=>screen.getAllByRole("article").map(e=>e.textContent);
  const before=snapshot();view.unmount();open();await screen.findByAltText("起跳关键帧");expect(snapshot()).toEqual(before);
  expect(client.fetchAnalysis).toHaveBeenCalledTimes(2);expect(client.fetchAnalysisPose).toHaveBeenCalledTimes(2);
 });
 it.each(["synthetic-unavailable","synthetic-step","saved38-actual-step"])("retains unavailable/N-A/null reasons in %s", id=>{
  const value=payloads[id];render(<ActionPhaseStrip analysis={value.detail} pose={value.pose}/>);
  if (id !== "synthetic-unavailable") {
   expect(screen.getAllByRole("article")).toHaveLength(1);
   expect(screen.getByRole("heading",{name:"步法区间"})).toBeInTheDocument();
   expect(screen.queryByAltText("起跳关键帧")).not.toBeInTheDocument();
   expect(value.detail.bio_data.jump_measurements.air_time.value).toBeNull();
   if(id.startsWith("saved38")){expect(value.pose.frames).toHaveLength(38);expect(value.pose.frames.reduce((n:number,f:any)=>n+f.keypoints.length,0)).toBe(1254);expect(Object.keys(value.image_reads)).toHaveLength(38);}
   return;
  }
  expect(screen.getAllByRole("article")).toHaveLength(5);
  for(const button of screen.getAllByRole("button",{name:/查看/}))expect(button).toBeDisabled();
  expect(screen.queryByAltText("起跳关键帧")).not.toBeInTheDocument();
  expect(value.detail.bio_data.jump_measurements.air_time.value).toBeNull();
  expect(screen.getAllByRole("listitem").find(e=>e.textContent?.startsWith("确认腾空时间"))).not.toHaveTextContent("0.000s");
  if(id.startsWith("saved38")){expect(value.pose.frames).toHaveLength(38);expect(value.pose.frames.reduce((n:number,f:any)=>n+f.keypoints.length,0)).toBe(1254);expect(Object.keys(value.image_reads)).toHaveLength(38);}
 });
 it("renders the separate saved38 jump diagnostic without granting playback mapping or changing actual step",()=>{
  const value=payloads["saved38-diagnostic-jump"];render(<ActionPhaseStrip analysis={value.detail} pose={value.pose}/>);
  expect(screen.getByAltText("起跳关键帧")).toHaveAttribute("src",expect.stringContaining("saved_only=true"));
  expect(screen.getByRole("button",{name:/查看起跳/})).toBeDisabled();expect(seek).not.toHaveBeenCalled();
  expect(payloads["saved38-actual-step"].detail.analysis_profile).toBe("step");
 });
 it("does not fetch whole-analysis TAL into V2, another selected event or independent moments",()=>{
  const value=decodeAnalysisExperienceV2(payloads["synthetic-slow-jump"].experience);const id=value.events[0].eventId;
  expect(savedJumpReplayScope(value,id)).toBe(true);
  expect(savedJumpReplayScope({...value,authority:"v2",pipelineMode:"v2"},id)).toBe(false);
  expect(savedJumpReplayScope(value,"other-event")).toBe(false);
  expect(savedJumpReplayScope({...value,events:[{...value.events[0],moments:{} as any}]},id)).toBe(false);
 });
 it("ignores a late response after its result scope changes",async()=>{
  let release!:(a:client.AnalysisDetail)=>void;
  vi.mocked(client.fetchAnalysis).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
  const {useSavedJumpReplay}=await import("../analysis-v2/useSavedJumpReplay");
  const value=decodeAnalysisExperienceV2(payloads["synthetic-slow-jump"].experience);
  function Probe({selected}:{selected:string}){const saved=useSavedJumpReplay(value,selected);return <div>{saved?.id??"no saved result"}</div>;}
  const view=render(<Probe selected={value.events[0].eventId}/>);await waitFor(()=>expect(release).toBeDefined());
  view.rerender(<Probe selected="different-event"/>);release(structuredClone(payloads["synthetic-slow-jump"].detail));
  await waitFor(()=>expect(client.fetchAnalysisPose).toHaveBeenCalled());expect(screen.getByText("no saved result")).toBeInTheDocument();
 });
});
