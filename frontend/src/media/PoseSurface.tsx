import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import PoseFrameCanvas from "../components/PoseFrameCanvas";
import type { PoseResponse } from "../api/client";
import { drawPoseOverlay, isDisplayFrame, isDisplayPoint, validVideoGeometry } from "../utils/poseCanvas";
import { poseFrameIndexAtTime, poseFrameTimestamp } from "./poseTimeline";

type Props = { pose: PoseResponse; timestamp: number; className?: string; videoRef?: RefObject<HTMLVideoElement | null> };

function VideoPoseOverlay({pose, videoRef, className}: Props & {videoRef: RefObject<HTMLVideoElement | null>}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [clock, setClock] = useState({time: NaN, width: 0, height: 0, ready: false});
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let pendingSeek = false; let waiting = false; let stopped = false; let callback = 0; let animation = 0;
    const read = () => {
      if (stopped) return;
      const next = {time: video.currentTime, width: video.videoWidth, height: video.videoHeight,
        ready: !pendingSeek && !waiting && !video.seeking && video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0};
      setClock(old => old.time === next.time && old.width === next.width && old.height === next.height && old.ready === next.ready ? old : next);
    };
    const seek = () => {pendingSeek = true; read();};
    const available = () => {pendingSeek = false; waiting = false; read();};
    const unavailable = () => {waiting = true; read();};
    const events = ["timeupdate", "loadedmetadata", "resize", "pause", "play"];
    events.forEach(event => video.addEventListener(event, read));
    ["seeked", "loadeddata", "playing", "canplay"].forEach(event => video.addEventListener(event, available));
    ["emptied", "error", "waiting", "loadstart"].forEach(event => video.addEventListener(event, unavailable));
    video.addEventListener("seeking", seek);
    const tick = () => {read(); if (!stopped) {
      if (video.requestVideoFrameCallback) callback = video.requestVideoFrameCallback(tick);
      else animation = requestAnimationFrame(tick);
    }};
    tick();
    return () => {
      stopped = true;
      events.forEach(event => video.removeEventListener(event, read));
      ["seeked", "loadeddata", "playing", "canplay"].forEach(event => video.removeEventListener(event, available));
      ["emptied", "error", "waiting", "loadstart"].forEach(event => video.removeEventListener(event, unavailable));
      video.removeEventListener("seeking", seek);
      if (callback) video.cancelVideoFrameCallback(callback);
      if (animation) cancelAnimationFrame(animation);
    };
  }, [videoRef, pose]);
  const index = clock.ready ? poseFrameIndexAtTime(pose, clock.time) : -1;
  const frame = index >= 0 ? pose.frames[index] : null;
  const geometryReady = validVideoGeometry(pose.geometry, clock.width, clock.height);
  const drawable = geometryReady && frame && isDisplayFrame(frame) && frame.keypoints.some(point => isDisplayPoint(point) && frame.usable_joint_mask?.[String(point.id)] !== false);
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !frame || !drawable) return;
    const draw = () => drawPoseOverlay(canvas, frame, pose.connections, {mediaWidth: clock.width, mediaHeight: clock.height, coordinateTarget: "video", geometry: pose.geometry});
    draw();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(draw);
    observer?.observe(canvas);
    window.addEventListener("resize", draw);
    return () => {observer?.disconnect(); window.removeEventListener("resize", draw);};
  }, [frame, drawable, pose.connections, pose.geometry, clock.width, clock.height]);
  const sample = frame ? poseFrameTimestamp(pose, frame, index) : null;
  const reason = !clock.ready ? "视频定位或加载中，骨架暂不可用" : !geometryReady ? `保存几何不可用，不能叠加（${pose.geometry_unavailable_reason ?? "尺寸或变换不受支持"}）；可查看采样图参考` : !frame ? "无匹配保存姿态（时间缺失、越界或采样间隙）" : !isDisplayFrame(frame) ? "跟踪丢失或姿态不可用" : !drawable ? "此采样无可用关键点" : `采样参考 ${sample?.toFixed(3)} 秒；仅显示通过质量筛选的点`;
  return <div className={className} style={{position: "absolute", inset: 0, pointerEvents: "none", background: "transparent"}}>
    {!geometryReady && clock.ready && <details style={{pointerEvents: "auto", position: "absolute", top: 0, left: 0, width: "45%", background: "#111", color: "white"}}><summary>保存采样图参考</summary><StaticPoseSurface pose={pose} timestamp={clock.time} /></details>}
    {drawable && <canvas ref={canvasRef} aria-label="保存骨架叠加" style={{width: "100%", height: "100%", display: "block", background: "transparent"}} />}
    <p role="status" style={{position: "absolute", bottom: 0, left: 8, right: 8, margin: 0, color: "white", background: "rgba(0,0,0,.65)"}}>{reason}。保存采样时间不代表逐源帧实测 PTS；旧记录缺少质量标记时仅按可见度筛选。</p>
  </div>;
}

export function PoseSurface(props: Props) {
  if (props.videoRef) return <VideoPoseOverlay {...props} videoRef={props.videoRef} />;
  return <StaticPoseSurface {...props} />;
}
function StaticPoseSurface({pose, timestamp, className}: Props) {
  const index = poseFrameIndexAtTime(pose, timestamp);
  const frame = index >= 0 ? pose.frames[index] : null;
  const frameUrl = frame ? pose.frame_urls[frame.frame] ?? pose.frame_urls[frame.frame.replace(/\.jpg$/i, "")] ?? null : null;
  return <PoseFrameCanvas frame={frame} frameUrl={frameUrl} connections={pose.connections} alt="骨架姿态" className={className} />;
}
