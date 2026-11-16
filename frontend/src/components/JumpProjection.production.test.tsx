// @ts-expect-error Node builtin is used only by the offline fixture test runner.
import {readFileSync} from 'node:fs';
import {forwardRef,useImperativeHandle} from 'react';
import {render,screen,cleanup,fireEvent,waitFor} from '@testing-library/react';
import {MemoryRouter,Routes,Route,useNavigate} from 'react-router-dom';
import {it,expect,vi,afterEach,beforeEach,describe} from 'vitest';
import {buildCurrentKeyframeEvidenceItems} from '../utils/keyframeEvidence';
import {analysisMediaMarkers} from '../media/analysisMarkers';
import {decodeAnalysisExperienceV2} from '../analysis-v2/contracts';
import * as client from '../api/client';
import * as expApi from '../analysis-v2/api';
import ActionPhaseStrip from './ActionPhaseStrip';
import ModernAnalysisDetail from '../modern/ModernAnalysisDetail';
const {seek,playerProps}=vi.hoisted(()=>({seek:vi.fn(),playerProps:[] as any[]}));
vi.mock('../media/IceMediaPlayer',()=>({IceMediaPlayer:forwardRef((props:any,ref)=>{playerProps.push(props);useImperativeHandle(ref,()=>({seek}));return <div data-testid="player-substitute" data-seek-time={String(props.seekTime)}/>;})}));
vi.mock('../api/client',async original=>({...await original<typeof import('../api/client')>(),fetchAnalysis:vi.fn(),fetchAnalysisPose:vi.fn()}));
vi.mock('../analysis-v2/api',async original=>({...await original<typeof import('../analysis-v2/api')>(),fetchAnalysisExperienceV2:vi.fn()}));
vi.mock('./AppModeContext',()=>({useAppMode:()=>({isParentMode:false,parentPin:null})}));
const fixturePath=(globalThis as unknown as {process:{env:Record<string,string|undefined>}}).process.env.JUMP_REPLAY_FIXTURE;
const fixtures=fixturePath ? JSON.parse(readFileSync(fixturePath,'utf8')) : null;
const evidence:any={};
function save() {} // Runtime review copy separately records these observations.
describe.skipIf(!fixturePath)("projection and replay production GET consumers",()=>{
afterEach(()=>{cleanup();vi.clearAllMocks();playerProps.length=0;});
beforeEach(()=>{vi.mocked(client.fetchAnalysis).mockImplementation(async id=>structuredClone(fixtures[id].detail));vi.mocked(client.fetchAnalysisPose).mockImplementation(async id=>structuredClone(fixtures[id].pose));vi.mocked(expApi.fetchAnalysisExperienceV2).mockImplementation(async id=>decodeAnalysisExperienceV2(structuredClone(fixtures[id].experience)));});
const specs=[['spin',['spin_entry','spin_main','spin_exit'],['入转','主转','出转']],['spiral',['spiral_hold'],['姿态保持']],['step',['step_sequence'],['步法区间']]] as const;
it.each(specs)('preserves existing %s saved evidence when jump stages are not applicable',(profile,keys,labels)=>{
 const value=structuredClone(fixtures['synthetic-step'].detail);value.analysis_profile=profile;value.pose_data=fixtures['synthetic-step'].pose;
 value.bio_data.key_frames=Object.fromEntries(keys.map((key,i)=>[key,{frame_id:'frame_000'+(i+1),timestamp:.1*(i+1)}]));
 const historical=structuredClone(value);delete historical.bio_data.jump_stage_contract;
 const baseline=buildCurrentKeyframeEvidenceItems(historical);expect(baseline.map(x=>x.label)).toEqual([...labels]);expect(baseline.every(x=>x.frameId)).toBe(true);
 const current=buildCurrentKeyframeEvidenceItems(value);evidence[profile]={baseline:baseline.map(x=>({key:x.key,label:x.label,frame:x.frameId})),current:current.map(x=>({key:x.key,label:x.label,frame:x.frameId,status:x.status})),baselineMarkers:analysisMediaMarkers(historical),currentMarkers:analysisMediaMarkers(value)};save();
 render(<ActionPhaseStrip analysis={value} pose={value.pose_data}/>);
 expect(current.map(x=>x.label)).toEqual([...labels]);expect(screen.getAllByRole('heading',{level:3}).map(e=>e.textContent)).toEqual([...labels]);expect(analysisMediaMarkers(value)).toHaveLength(keys.length);
});
it('keeps valid playback deep-link after actual saved jump data loads',async()=>{
 const id='synthetic-slow-jump',t=.5;
 render(<MemoryRouter initialEntries={['/analysis/'+id+'?view=moments&t='+t]}><Routes><Route path='/analysis/:id' element={<ModernAnalysisDetail/>}/></Routes></MemoryRouter>);
 await screen.findByAltText('起跳关键帧');expect(client.fetchAnalysisPose).toHaveBeenCalledWith(id);
 evidence.deep_link={requested_playback_time:t,player_seekTime:playerProps[playerProps.length - 1]?.seekTime,history:playerProps.map(p=>p.seekTime)};save();
 expect(playerProps[playerProps.length - 1]?.seekTime).toBe(t);
});
it('uses playback seconds for a valid saved stage and disables unimplemented stages',()=>{
 const v=fixtures['synthetic-slow-jump'];render(<ActionPhaseStrip analysis={v.detail} pose={v.pose}/>);
 fireEvent.click(screen.getByRole('button',{name:/查看起跳/}));expect(seek).toHaveBeenCalledWith(v.detail.bio_data.jump_stages.takeoff.playback_timestamp,{play:true});
 expect(screen.getByRole('button',{name:/查看收紧/})).toBeDisabled();expect(screen.getByRole('button',{name:/查看旋转/})).toBeDisabled();
});
it('keeps explicit V2 moments authoritative over legacy TAL',()=>{
 const v=fixtures['synthetic-slow-jump'];const event={eventId:'independent',profile:'jump',moments:{moments:[],expectedKeys:[],missingKeys:[],completeness:'incomplete',definitionVersion:'jump.v1'}} as any;
 render(<ActionPhaseStrip analysis={v.detail} pose={v.pose} event={event}/>);expect(screen.queryByAltText('起跳关键帧')).not.toBeInTheDocument();
});
it('keeps all-invalid production stages unavailable and does not seek',()=>{const v=fixtures['synthetic-unavailable'];render(<ActionPhaseStrip analysis={v.detail} pose={v.pose}/>);for(const b of screen.getAllByRole('button',{name:/查看/}))expect(b).toBeDisabled();expect(screen.queryByAltText('起跳关键帧')).not.toBeInTheDocument();expect(seek).not.toHaveBeenCalled();});

it.each([0,.5,-1,99])('keeps/clamps playback deep link %s after async loading and reopens it',async t=>{
 const id='synthetic-projection';
 const open=()=>render(<MemoryRouter initialEntries={['/analysis/'+id+'?view=moments&t='+t]}><Routes><Route path='/analysis/:id' element={<ModernAnalysisDetail/>}/></Routes></MemoryRouter>);
 const v=open();await screen.findByAltText('收紧关键帧');
 expect(playerProps[playerProps.length - 1]?.seekTime).toBe(Math.max(0,Math.min(t,2)));
 v.unmount();open();await screen.findByAltText('收紧关键帧');expect(playerProps[playerProps.length - 1]?.seekTime).toBe(Math.max(0,Math.min(t,2)));
});
it.each(['NaN','Infinity','bad',''])('rejects illegal playback deep link %s',async t=>{
 const id='synthetic-projection';render(<MemoryRouter initialEntries={['/analysis/'+id+'?view=moments&t='+t]}><Routes><Route path='/analysis/:id' element={<ModernAnalysisDetail/>}/></Routes></MemoryRouter>);
 await screen.findByAltText('收紧关键帧');expect(playerProps[playerProps.length - 1]?.seekTime).toBeNull();
});
it.each([['synthetic-spin',['入转','主转','出转']],['synthetic-spiral',['姿态保持']],['synthetic-step',['步法区间']]])('preserves actual production non-jump result %s',async(id,labels)=>{
 const value=fixtures[id as string];
 render(<MemoryRouter initialEntries={['/analysis/'+id+'?view=moments']}><Routes><Route path='/analysis/:id' element={<ModernAnalysisDetail/>}/></Routes></MemoryRouter>);
 await waitFor(()=>expect(client.fetchAnalysisPose).toHaveBeenCalledWith(id));
 await waitFor(()=>expect(screen.getAllByRole('heading',{level:3}).map(e=>e.textContent)).toEqual(labels));
 expect(buildCurrentKeyframeEvidenceItems(value.detail).every(p=>!!p.frameId)).toBe(true);
 expect(screen.queryByAltText('起跳关键帧')).not.toBeInTheDocument();
 await waitFor(()=>expect(screen.getAllByRole('img').every(p=>p.getAttribute('src')?.includes('saved_only=true'))).toBe(true));
 expect(analysisMediaMarkers({...value.detail,pose_data:value.pose}).length).toBe((labels as string[]).length);
});
it('renders saved projection and pull-in original frame and seeks playback seconds',()=>{
 const value=fixtures['synthetic-projection']; const tr=value.detail.bio_data.jump_measurements.trajectory;
 render(<ActionPhaseStrip analysis={value.detail} pose={value.pose}/>);
 expect(screen.getByText('髋中点投影轨迹（未消除镜头运动）')).toBeInTheDocument();
 expect(screen.getAllByTestId('trajectory-segment')).toHaveLength(tr.segments.length);
 const p=tr.points[3];fireEvent.click(screen.getByRole('button',{name:'轨迹点 '+p.frame_id}));
 fireEvent.load(screen.getByAltText('髋轨迹原帧 '+p.frame_id));
 expect(seek).toHaveBeenLastCalledWith(p.playback_timestamp,{play:true});
 expect(screen.getByAltText('髋轨迹原帧 '+p.frame_id)).toHaveAttribute('src',expect.stringContaining('saved_only=true'));
 const pull=value.detail.bio_data.jump_stages['pull-in'];
 fireEvent.click(screen.getByRole('button',{name:/查看收紧/}));expect(seek).toHaveBeenLastCalledWith(pull.playback_timestamp,{play:true});
 expect(screen.getByAltText('收紧关键帧')).toHaveAttribute('src',expect.stringContaining(pull.frame_id+'.jpg?saved_only=true'));
 expect(value.image_reads[pull.frame_id+'.jpg']).toMatch(/^[a-f0-9]{64}$/);
 expect(value.detail.report.jump_measurements).toEqual(value.detail.bio_data.jump_measurements);
});
it('draws separate production gap segments, and a single point without any line',()=>{
 const value=fixtures['synthetic-projection-gap'];
 const v=render(<ActionPhaseStrip analysis={value.detail} pose={value.pose}/>);
 expect(screen.getAllByTestId('trajectory-segment')).toHaveLength(2);
 v.unmount();const single=structuredClone(value.detail);const tr=single.bio_data.jump_measurements.trajectory;
 tr.points=tr.points.slice(0,1);tr.segments=[{segment_id:tr.points[0].segment_id,point_indices:[0]}];
 render(<ActionPhaseStrip analysis={single} pose={value.pose}/>);
 expect(screen.queryByTestId('trajectory-segment')).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'轨迹点 '+tr.points[0].frame_id})).toBeInTheDocument();
});
it('displays points but disables seeking without reliable playback mapping',()=>{
 const value=structuredClone(fixtures['synthetic-projection']);
 for(const p of value.detail.bio_data.jump_measurements.trajectory.points){p.source_timestamp=null;p.time_source='legacy_or_sampling_time_unverified';}
 render(<ActionPhaseStrip analysis={value.detail} pose={value.pose}/>);
 for(const point of screen.getAllByRole('button',{name:/轨迹点/})){expect(point).not.toHaveAttribute('aria-disabled','true');fireEvent.click(point);}
 const last=value.detail.bio_data.jump_measurements.trajectory.points.at(-1);
 expect(screen.getByAltText('髋轨迹原帧 '+last.frame_id)).toHaveAttribute('src',expect.stringContaining(last.frame_id+'.jpg?saved_only=true'));
 expect(seek).not.toHaveBeenCalled();expect(screen.getAllByText(/缺少可信播放时间/).length).toBeGreaterThan(0);
});
it('clears previous saved projection when analysis route changes',async()=>{
 function Switch(){const navigate=useNavigate();return <button onClick={()=>navigate('/analysis/synthetic-unavailable?view=moments&t=0.2')}>切换分析</button>;}
 render(<MemoryRouter initialEntries={['/analysis/synthetic-projection?view=moments&t=0.5']}><Switch/><Routes><Route path='/analysis/:id' element={<ModernAnalysisDetail/>}/></Routes></MemoryRouter>);
 await screen.findByAltText('收紧关键帧');
 fireEvent.click(screen.getByRole('button',{name:'切换分析'}));
 await waitFor(()=>expect(client.fetchAnalysisPose).toHaveBeenCalledWith('synthetic-unavailable'));
 await waitFor(()=>expect(screen.queryByAltText('收紧关键帧')).not.toBeInTheDocument());
 expect(screen.queryByRole('button',{name:/轨迹点/})).not.toBeInTheDocument();
 await waitFor(()=>expect(playerProps[playerProps.length-1]?.seekTime).toBe(.2));
});

});
