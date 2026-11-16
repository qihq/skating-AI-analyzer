"""Saved continuous geometry: offline images, exact bindings and actual GET consumers."""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from app.services.pose_geometry import recover_pose_geometry


def saved_case(root, source=(400,800), canvas=(800,400), origin=7., scale=4.):
    root.mkdir(exist_ok=True, parents=True)
    images=root/"frames";images.mkdir(exist_ok=True)
    vw,vh=source;sw,sh=canvas
    if sw*vh<=sh*vw:w,h=sw,(vh*sw+vw//2)//vw
    else:w,h=(vw*sh+vh//2)//vh,sh
    x,y=((sw-w)//2)//2*2,((sh-h)//2)//2*2
    observations=[];bindings=[];frames=[];selected=[]
    for i,playback in enumerate((0.,.1,.2,.8,.9)):
        name=f"frame_{i+1:04d}.jpg"
        Image.new("RGB",canvas,(i*30,0,0)).save(images/name)
        sha=hashlib.sha256((images/name).read_bytes()).hexdigest();pts=round((origin+playback)*600)
        observations.append(dict(index=i,file=f"observation_{i+1:04d}.jpg",sha256=sha,source_pts=pts,source_time_base="1/600",source_pts_time=pts/600.,timestamp=playback))
        binding=dict(frame=name,frame_id=Path(name).stem,observation_index=i,sha256=sha,source_pts=pts,source_time_base="1/600",source_origin_sec=origin)
        bindings.append(binding)
        selected.append(dict(frame_id=Path(name).stem,source_sample_index=i,sha256=sha,source_pts=pts,source_time_base="1/600",source_pts_time=pts/600.,timestamp=playback,analysis_timestamp=playback/scale))
        temporal=dict(time_source="bound_source_pts",playback_timestamp=playback,analysis_timestamp=playback/scale,slow_motion_scale=scale,binding=copy.deepcopy(binding),tracking_continuity_segment=0 if i<3 else 1,segment_id=0 if i<3 else 1,continuous=i in (1,2,4))
        frames.append(dict(frame=name,keypoints=[dict(id=11,name="left_shoulder",x=(x+w*.25)/sw,y=(y+h*.75)/sh,z=0.,visibility=1.)],tracking_state="tracked",tracker_state="tracked",input_binding_valid=True,temporal=temporal,projection_geometry=dict(schema_version="pose-projection.v1",coordinate_space="full_image_normalized",image_width=sw,image_height=sh,provenance="landmarks_mapped_to_full_image")))
    # An independently unconfirmed segment remains empty; geometry does not confer identity.
    frames[-1].update(keypoints=[],tracking_state="lost",tracker_state="relock_pending",input_binding_valid=False)
    frames[-1]["temporal"].update(time_source="binding_selected_mismatch",playback_timestamp=None,analysis_timestamp=None)
    filters=(f"trim=start={origin:.9f}:end={origin+1:.9f},select='isnan(prev_selected_t)+gte(t-prev_selected_t,{1/12:.9f})',scale={sw}:{sh}:force_original_aspect_ratio=decrease,showinfo,pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:black")
    manifest=dict(version=1,canvas=dict(width=sw,height=sh),geometry=dict(content_width=w,content_height=h,pad_left=x,pad_top=y,source_width=vw,source_height=vh,sample_aspect_ratio="1:1",rotation=[],autorotate=True,filter=filters),source_sha256="a"*64,source_origin_sec=origin,source_stream_time_base="1/600",window_start=0.,window_end=1.,nominal_hz=12.,observations=observations,pose_bindings=bindings)
    motion=dict(selection_strategy="motion_targets_bound_to_decoded_pool",video_identity=dict(sha256="a"*64),full_size=f"{sw}x{sh}",slow_motion_scale=scale,continuous_tracking=manifest,selected=selected)
    timeline=dict(schema_version="source-timeline.v1",source_video_hash="a"*64,width=vw,height=vh,rotation_degrees=0,timebase=dict(numerator=1,denominator=600),timestamp_status="exact",frames=[dict(source_frame_index=i,pts_sec=o["source_pts_time"]) for i,o in enumerate(observations)])
    media=dict(schema_version="analysis_media.v1",source_timeline=timeline)
    (root/"media-manifest.json").write_text(json.dumps(media),encoding="utf-8")
    row=SimpleNamespace(pipeline_version="legacy/local-r1",video_path=str(root/"source.mp4"),frame_motion_scores=motion,pose_data=dict(connections=[],frames=frames))
    return row,images,media


@pytest.mark.parametrize("source,canvas",[((400,800),(800,400)),((800,400),(400,800)),((600,300),(600,300)),((400,800),(802,400))])
def test_continuous_geometry_maps_known_marker(tmp_path,source,canvas):
    row,images,_=saved_case(tmp_path,source,canvas)
    before=copy.deepcopy(vars(row));g,reason=recover_pose_geometry(row,images)
    assert reason is None,reason
    p=row.pose_data["frames"][0]["keypoints"][0];r=g["content_rect"]
    assert (p["x"]*g["sample_width"]-r["x"])/r["width"]==pytest.approx(.25)
    assert (p["y"]*g["sample_height"]-r["y"])/r["height"]==pytest.approx(.75)
    assert vars(row)==before


@pytest.mark.parametrize("origin,scale",[(7.,4.),(-7.,4.),(0.,1.)])
def test_actual_builder_report_sqlite_get_geometry(tmp_path,origin,scale):
    from test_tal_persistence import consume_contract
    row,images,_=saved_case(tmp_path,origin=origin,scale=scale)
    (tmp_path/"absent-source.mp4").write_bytes(b"synthetic locator only; never decode")
    pose=copy.deepcopy(row.pose_data);motion=copy.deepcopy(row.frame_motion_scores)
    result=consume_contract(tmp_path,pose,motion,"step",name="geometry",pipeline_version=row.pipeline_version,saved_images={p.name:p.read_bytes() for p in images.iterdir()})
    assert result["pose"]["geometry_unavailable_reason"] is None
    assert result["pose"]["geometry"] is not None
    assert result["detail"]["pose_data"]==pose
    assert result["detail"]["frame_motion_scores"]==motion
    assert list(result["pose"]["frame_timestamps"].values())==[0.,.1,.2,.8,.9]
    assert result["detail"]["analysis_profile"]=="step"
    assert result["detail"]["report"]["jump_measurements"]["rotation_count"]["value"] is None
    out=os.getenv("SAVED_GEOMETRY_EVIDENCE")
    if out:
        p=Path(out);p.mkdir(parents=True,exist_ok=True)
        (p/f"chain-{origin}-{scale}.json").write_text(json.dumps(result,indent=2),encoding="utf-8")


# Mutate redundant provenance independently: matching dimensions are not identity.
@pytest.mark.parametrize("path,value,reason",[
 ("c.source_sha256","b"*64,"unverified_saved_source_identity"),
 ("m.video_identity.sha256","b"*64,"unverified_saved_source_identity"),
 ("c.version",True,"unsupported_saved_geometry_schema"),
 ("c.version",2,"unsupported_saved_geometry_schema"),
 ("g.sample_aspect_ratio",None,"unsupported_or_unknown_saved_sar"),
 ("g.sample_aspect_ratio","4:3","unsupported_or_unknown_saved_sar"),
 ("g.sample_aspect_ratio","0:1","unsupported_or_unknown_saved_sar"),
 ("g.rotation",[90],"unsupported_saved_source_orientation"),
 ("g.rotation",None,"unsupported_saved_source_orientation"),
 ("g.rotation",[False],"unsupported_saved_source_orientation"),
 ("g.autorotate",False,"unsupported_saved_source_orientation"),
 ("g.filter","hflip","unsupported_saved_transform"),
 ("g.source_width",401,"saved_geometry_dimension_mismatch"),
 ("g.pad_left",301,"unsupported_saved_content_rect"),
 ("g.pad_top",400,"unsupported_saved_content_rect"),
 ("g.content_width",199,"unsupported_saved_content_rect"),
 ("g.content_width",float("nan"),"invalid_saved_geometry_number"),
 ("g.content_height",float("inf"),"invalid_saved_geometry_number"),
 ("g.pad_left",True,"invalid_saved_geometry_number"),
 ("m.full_size","400x400","saved_geometry_dimension_mismatch"),
 ("b.sha256","b"*64,"saved_geometry_binding_mismatch"),
 ("b.source_pts",4201,"saved_geometry_binding_mismatch"),
 ("b.source_pts",True,"saved_geometry_binding_mismatch"),
 ("b.source_time_base","1/30","saved_geometry_binding_mismatch"),
 ("b.source_origin_sec",8.,"saved_geometry_clock_mismatch"),
 ("b.observation_index",True,"invalid_saved_geometry_number"),
 ("s.sha256","b"*64,"saved_geometry_binding_mismatch"),
 ("s.source_sample_index",1,"saved_geometry_binding_mismatch"),
 ("s.timestamp",7.,"saved_geometry_clock_mismatch"),
 ("s.analysis_timestamp",1.,"saved_geometry_clock_mismatch"),
 ("o.source_pts_time",0.,"saved_geometry_clock_mismatch"),
 ("o.source_time_base","0/0","invalid_saved_geometry_clock"),
 ("o.timestamp",True,"invalid_saved_geometry_number"),
 ("t.playback_timestamp",.1,"saved_geometry_clock_mismatch"),
 ("t.analysis_timestamp",.1,"saved_geometry_clock_mismatch"),
 ("t.slow_motion_scale",True,"invalid_saved_geometry_number"),
 ("t.time_source","index_derived","invalid_saved_geometry_clock"),
 ("p.schema_version","unknown","unverified_saved_projection_geometry"),
 ("p.coordinate_space","crop_normalized","unverified_saved_projection_geometry"),
 ("p.image_width",400,"unverified_saved_projection_geometry"),
])
def test_conflicting_saved_evidence_is_rejected(tmp_path,path,value,reason):
    row,images,_=saved_case(tmp_path)
    m=row.frame_motion_scores;c=m["continuous_tracking"];f=row.pose_data["frames"][0]
    roots=dict(m=m,c=c,g=c["geometry"],b=c["pose_bindings"][0],s=m["selected"][0],o=c["observations"][0],t=f["temporal"],p=f["projection_geometry"])
    keys=path.split(".");target=roots[keys.pop(0)]
    for key in keys[:-1]:target=target[key]
    target[keys[-1]]=value
    before=copy.deepcopy(row.pose_data)
    assert recover_pose_geometry(row,images)==(None,reason)
    assert row.pose_data==before


@pytest.mark.parametrize("damage",["same_size_other_jpeg","wrong_size","broken","missing","missing_projection","missing_geometry","missing_sar","source_hash","source_schema","source_rotation","source_bool","source_timebase","source_times"])
def test_missing_or_damaged_saved_evidence(tmp_path,damage):
    row,images,media=saved_case(tmp_path);m=row.frame_motion_scores;c=m["continuous_tracking"];path=images/"frame_0001.jpg"
    if damage=="same_size_other_jpeg":Image.new("RGB",(800,400),"blue").save(path)
    elif damage in ("wrong_size","broken"):
        if damage=="wrong_size":Image.new("RGB",(400,400)).save(path)
        else:path.write_bytes(b"not a JPEG")
        h=hashlib.sha256(path.read_bytes()).hexdigest()
        for r in (c["observations"][0],c["pose_bindings"][0],m["selected"][0],row.pose_data["frames"][0]["temporal"]["binding"]):r["sha256"]=h
    elif damage=="missing":path.unlink()
    elif damage=="missing_projection":row.pose_data["frames"][0].pop("projection_geometry")
    elif damage=="missing_geometry":c.pop("geometry")
    elif damage=="missing_sar":c["geometry"].pop("sample_aspect_ratio")
    else:
        field,value={"source_hash":("source_video_hash","b"*64),"source_schema":("schema_version","unknown"),"source_rotation":("rotation_degrees",90),"source_bool":("rotation_degrees",False),"source_timebase":("timebase",dict(numerator=1,denominator=30)),"source_times":("frames",[])}[damage]
        media["source_timeline"][field]=value
        (tmp_path/"media-manifest.json").write_text(json.dumps(media))
    assert recover_pose_geometry(row,images)[0] is None


def test_geometry_never_promotes_identity_or_changes_keypoints(tmp_path):
    row,images,_=saved_case(tmp_path)
    row.pose_data["frames"][1].update(tracker_state="relock_pending",input_binding_valid=False)
    before=copy.deepcopy(row.pose_data)
    assert recover_pose_geometry(row,images)[0] is not None
    assert row.pose_data==before


def test_producer_records_chroma_aligned_padding(tmp_path, monkeypatch):
    import asyncio
    from app.services import continuous_tracking, video
    source=tmp_path/"synthetic-source.bin";source.write_bytes(b"synthetic, never decoded")
    pool=tmp_path/"pool"
    monkeypatch.setattr(continuous_tracking,"_probe",lambda _:dict(time_base="1/600",start_pts=4200,width=400,height=800,sample_aspect_ratio="1:1"))
    monkeypatch.setattr(video,"_frame_dimensions",lambda:(802,400))
    async def synthetic_decode(args):
        Image.new("RGB",(802,400)).save(pool/"observation_0001.jpg")
        return "config in time_base: 1/600\n[Parsed_showinfo_0] n: 0 pts: 4200 pts_time:7 s:200x400"
    monkeypatch.setattr(video,"_run_ffmpeg",synthetic_decode)
    result=asyncio.run(continuous_tracking.extract_tracking_pool(source,pool,0.,1.))
    assert result["geometry"]["pad_left"]==300
    assert result["geometry"]["pad_top"]==0
    assert result["observations"][0]["source_pts"]==4200
    assert result["observations"][0]["timestamp"]==0
