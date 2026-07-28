import { useMemo } from "react";
import PoseFrameCanvas from "../components/PoseFrameCanvas";
import type { PoseResponse } from "../api/client";
import { poseFrameIndexAtTime } from "./poseTimeline";

type Props = { pose: PoseResponse; timestamp: number; className?: string };

export function PoseSurface({ pose, timestamp, className }: Props) {
  const index = useMemo(() => poseFrameIndexAtTime(pose, timestamp), [pose, timestamp]);
  const frame = index >= 0 ? pose.frames[index] : null;
  const frameUrl = frame ? pose.frame_urls[frame.frame] ?? pose.frame_urls[frame.frame.replace(/\.jpg$/i, "")] ?? null : null;
  return <PoseFrameCanvas frame={frame} frameUrl={frameUrl} connections={pose.connections} alt="骨架姿态" className={className} />;
}
