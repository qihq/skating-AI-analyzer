import { describe, expect, it, vi } from "vitest";
import { computeContainRect, drawPoseOverlay } from "./poseCanvas";

describe("computeContainRect", () => {
  it("letterboxes portrait media without stretching it", () => {
    expect(computeContainRect(320, 180, 90, 160)).toEqual({
      x: 109.375,
      y: 0,
      width: 101.25,
      height: 180,
    });
  });

  it("pillarboxes wide media inside a square", () => {
    expect(computeContainRect(200, 200, 400, 100)).toEqual({
      x: 0,
      y: 75,
      width: 200,
      height: 50,
    });
  });
});

it("hides high-visibility interpolated/unusable points and incident lines, retaining other joints", () => {
  const ctx = {setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), arc: vi.fn(), fill: vi.fn(), strokeRect: vi.fn()};
  const canvas = document.createElement("canvas");
  vi.spyOn(canvas, "getContext").mockReturnValue(ctx as never);
  const point = {id: 11, name: "joint", x: .2, y: .3, z: 0, visibility: .99};
  drawPoseOverlay(canvas, {frame: "synthetic.jpg", keypoints: [point, {...point, id: 12, interpolated: true}, {...point, id: 13, usable: false}, {...point, id: 14, visibility: NaN}, {...point, id: 15, x: Infinity}, {...point, id: 16}]}, [[11,12], [11,13], [11,16]], {mediaWidth: 406, mediaHeight: 720});
  expect(ctx.arc).toHaveBeenCalledTimes(2);
  expect(ctx.lineTo).toHaveBeenCalledTimes(1);
});

function geometry(sw: number, sh: number, x: number, y: number, w: number, h: number, vw = w, vh = h) {
  return {schema_version: "pose-geometry.v1", coordinate_space: "sample_normalized", sample_width: sw, sample_height: sh,
    content_rect: {x,y,width:w,height:h}, source_width: vw, source_height: vh, rotation_degrees: 0, crop: "none", provenance: "saved_metadata_verified_frames"} as const;
}
function renderPoint(g: unknown, cw: number, ch: number, mw: number, mh: number, px: number, py: number) {
  const ctx = {setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), arc: vi.fn(), fill: vi.fn()};
  const canvas = document.createElement("canvas");
  Object.defineProperties(canvas, {clientWidth: {value:cw}, clientHeight: {value:ch}});
  vi.spyOn(canvas,"getContext").mockReturnValue(ctx as never);
  drawPoseOverlay(canvas, {frame:"generic.jpg",keypoints:[{id:0,name:"nose",x:px,y:py,z:0,visibility:1}]}, [], {mediaWidth:mw,mediaHeight:mh,coordinateTarget:"video",geometry:g} as never);
  return ctx;
}
describe("sample canvas to decoded video geometry", () => {
  it.each([
    [geometry(800,400,300,0,200,400),200,400,200,400,.4375,.25,50,100],
    [geometry(400,800,0,300,400,200),400,200,400,200,.25,.4375,100,50],
    [geometry(600,300,0,0,600,300),600,300,600,300,.25,.25,150,75],
    [geometry(800,400,300,0,200,400),600,600,400,800,.4375,.25,225,150],
    [geometry(800,400,300,0,200,400),300,600,202,400,.4375,.25,75,151.48514851485],
  ])("undoes padding then CSS contain, including resize and rendition rounding %#", (g,cw,ch,mw,mh,px,py,x,y) => {
    const ctx=renderPoint(g,cw,ch,mw,mh,px,py); expect(ctx.arc).toHaveBeenCalledTimes(1);
    expect(ctx.arc.mock.calls[0][0]).toBeCloseTo(x,6); expect(ctx.arc.mock.calls[0][1]).toBeCloseTo(y,6);
  });
  it.each([undefined, {}, {...geometry(800,400,300,0,200,400), sample_width:0}, {...geometry(800,400,300,0,200,400), rotation_degrees:90}, {...geometry(800,400,300,0,200,400),crop:"unknown"}, {...geometry(800,400,300,0,200,400),content_rect:{x:700,y:0,width:200,height:400}}])("clears unsupported or missing geometry %#", g => {expect(renderPoint(g,200,400,200,400,.5,.5).arc).not.toHaveBeenCalled();});
  it("filters points outside content and rejects mismatching decoded aspect", () => {
    const g=geometry(800,400,300,0,200,400);
    expect(renderPoint(g,200,400,200,400,.1,.5).arc).not.toHaveBeenCalled();
    expect(renderPoint(g,400,200,400,200,.5,.5).arc).not.toHaveBeenCalled();
  });
  it("leaves sampled-image drawing in its original coordinates", () => {
    const ctx={setTransform:vi.fn(),clearRect:vi.fn(),beginPath:vi.fn(),arc:vi.fn(),fill:vi.fn()}; const canvas=document.createElement("canvas");
    Object.defineProperties(canvas,{clientWidth:{value:800},clientHeight:{value:400}}); vi.spyOn(canvas,"getContext").mockReturnValue(ctx as never);
    drawPoseOverlay(canvas,{frame:"sample",keypoints:[{id:0,name:"n",x:.4375,y:.25,z:0,visibility:1}]},[],{mediaWidth:800,mediaHeight:400});
    expect(ctx.arc.mock.calls[0].slice(0,2)).toEqual([350,100]);
  });
});


it("retains uncertain raw limbs visibly with a distinct style and an evidence label", () => {
  const ctx = {setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), arc: vi.fn(), fill: vi.fn(), setLineDash: vi.fn(), fillText: vi.fn(), strokeStyle: "", fillStyle: ""};
  const canvas = document.createElement("canvas");
  vi.spyOn(canvas,"getContext").mockReturnValue(ctx as never);
  const point = {id:27,name:"ankle",x:.4,y:.8,z:0,visibility:.99,quality:{source:"limb_uncertain",analysis_usable:false,limb_consistency:{status:"uncertain"}}};
  drawPoseOverlay(canvas,{frame:"generic.jpg",keypoints:[point,{...point,id:25,quality:undefined}]},[[25,27]],{mediaWidth:600,mediaHeight:400});
  expect(ctx.arc).toHaveBeenCalledTimes(2);
  expect(ctx.lineTo).toHaveBeenCalledTimes(1);
  expect(ctx.setLineDash).toHaveBeenCalledWith([4,3]);
  expect(ctx.fillText).toHaveBeenCalledWith(expect.stringContaining("未用于分析"),expect.any(Number),expect.any(Number));
});
