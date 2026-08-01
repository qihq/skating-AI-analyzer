import type { PoseFrame, PoseResponse } from "../api/client";

export function poseFrameTimestamp(pose: PoseResponse, frame: PoseFrame, index: number): number | null {
  const id = frame.frame.replace(/\.jpg$/i, "");
  const timestamp = pose.frame_timestamps?.[frame.frame] ?? pose.frame_timestamps?.[id];
  if (typeof timestamp === "number" && Number.isFinite(timestamp)) return timestamp;
  const sourceFrameIndex = (frame as PoseFrame & { source_frame_index?: number }).source_frame_index;
  if (Number.isInteger(sourceFrameIndex)) {
    const source = pose.source_timeline?.frames.find((item) => item.source_frame_index === sourceFrameIndex);
    return source?.pts_sec ?? null;
  }
  return null;
}

export function poseFrameIndexAtTime(pose: PoseResponse, timestamp: number): number {
  const frames = pose.frames;
  if (!frames.length) return -1;
  let low = 0; let high = frames.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const middleTimestamp = poseFrameTimestamp(pose, frames[middle], middle);
    if (middleTimestamp == null || middleTimestamp < timestamp) low = middle + 1;
    else high = middle - 1;
  }
  if (low === 0) return 0;
  if (low >= frames.length) return frames.length - 1;
  const before = poseFrameTimestamp(pose, frames[low - 1], low - 1);
  const after = poseFrameTimestamp(pose, frames[low], low);
  if (before == null || after == null) return -1;
  return timestamp - before <= after - timestamp ? low - 1 : low;
}
