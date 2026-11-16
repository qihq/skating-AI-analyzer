import type { PoseFrame, PoseResponse } from "../api/client";

export function poseFrameTimestamp(pose: PoseResponse, frame: PoseFrame, _index: number): number | null {
  const id = frame.frame.replace(/\.jpg$/i, "");
  const timestamp = pose.frame_timestamps?.[frame.frame] ?? pose.frame_timestamps?.[id];
  if (typeof timestamp === "number" && Number.isFinite(timestamp)) return timestamp;
  if (Number.isInteger(frame.source_frame_index)) {
    const source = pose.source_timeline?.frames.find(item => item.source_frame_index === frame.source_frame_index);
    if (typeof source?.pts_sec === "number" && Number.isFinite(source.pts_sec)) return source.pts_sec;
  }
  return null;
}

export function poseFrameIndexAtTime(pose: PoseResponse, timestamp: number): number {
  if (!Number.isFinite(timestamp) || !pose.frames.length) return -1;
  const times = pose.frames.map((frame, index) => poseFrameTimestamp(pose, frame, index));
  let interval = Infinity;
  for (let i = 0; i < times.length; i++) {
    const t = times[i];
    if (t == null || t < 0 || (i > 0 && t <= times[i - 1]!)) return -1;
    if (i) interval = Math.min(interval, t - times[i - 1]!);
  }
  if (timestamp < times[0]! || timestamp > times[times.length - 1]!) return -1;
  // Half the smallest saved sampling interval avoids filling sparse gaps.
  // 100 ms is a conservative display ceiling, not a claim of PTS precision.
  const tolerance = times.length === 1 ? 0 : Math.min(interval / 2, 0.1);
  let nearest = -1; let distance = Infinity;
  times.forEach((t, i) => { const d = Math.abs(t! - timestamp); if (d < distance) { nearest = i; distance = d; } });
  return distance <= tolerance + 1e-9 ? nearest : -1;
}
