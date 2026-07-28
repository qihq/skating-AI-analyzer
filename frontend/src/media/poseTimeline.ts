import type { PoseFrame, PoseResponse } from "../api/client";

export function poseFrameTimestamp(pose: PoseResponse, frame: PoseFrame, index: number): number {
  const id = frame.frame.replace(/\.jpg$/i, "");
  const timestamp = pose.frame_timestamps?.[frame.frame] ?? pose.frame_timestamps?.[id];
  return typeof timestamp === "number" && Number.isFinite(timestamp) ? timestamp : index / Math.max(pose.effective_fps ?? 5, 1);
}

export function poseFrameIndexAtTime(pose: PoseResponse, timestamp: number): number {
  const frames = pose.frames;
  if (!frames.length) return -1;
  let low = 0; let high = frames.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (poseFrameTimestamp(pose, frames[middle], middle) < timestamp) low = middle + 1;
    else high = middle - 1;
  }
  if (low === 0) return 0;
  if (low >= frames.length) return frames.length - 1;
  const before = poseFrameTimestamp(pose, frames[low - 1], low - 1);
  const after = poseFrameTimestamp(pose, frames[low], low);
  return timestamp - before <= after - timestamp ? low - 1 : low;
}
