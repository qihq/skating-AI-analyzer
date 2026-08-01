import { sourceTimelineFrameAt as selectSourceTimelineFrameAt, sourceTimelineFrameByIndex as selectSourceTimelineFrameByIndex, type SourceTimeline, type SourceTimelineFrame } from "./contracts";

export type NormalizedPoint = { x: number; y: number };
export type NormalizedBox = { left: number; top: number; right: number; bottom: number };
export type Rotation = 0 | 90 | 180 | 270;

export function sourceToDisplay(point: NormalizedPoint, rotation: Rotation): NormalizedPoint {
  if (rotation === 90) return { x: 1 - point.y, y: point.x };
  if (rotation === 180) return { x: 1 - point.x, y: 1 - point.y };
  if (rotation === 270) return { x: point.y, y: 1 - point.x };
  return point;
}

export function displayToSource(point: NormalizedPoint, rotation: Rotation): NormalizedPoint {
  if (rotation === 90) return { x: point.y, y: 1 - point.x };
  if (rotation === 180) return { x: 1 - point.x, y: 1 - point.y };
  if (rotation === 270) return { x: 1 - point.y, y: point.x };
  return point;
}

export function sourceBoxToDisplay(box: NormalizedBox, rotation: Rotation): NormalizedBox {
  const corners = [
    sourceToDisplay({ x: box.left, y: box.top }, rotation),
    sourceToDisplay({ x: box.right, y: box.top }, rotation),
    sourceToDisplay({ x: box.left, y: box.bottom }, rotation),
    sourceToDisplay({ x: box.right, y: box.bottom }, rotation),
  ];
  return {
    left: Math.min(...corners.map((point) => point.x)),
    top: Math.min(...corners.map((point) => point.y)),
    right: Math.max(...corners.map((point) => point.x)),
    bottom: Math.max(...corners.map((point) => point.y)),
  };
}

export function sourceTimelineFrameAt(timeline: SourceTimeline | null | undefined, pts: number): SourceTimelineFrame | null {
  return selectSourceTimelineFrameAt(timeline, pts);
}

export function sourceTimelineFrameByIndex(timeline: SourceTimeline | null | undefined, index: number): SourceTimelineFrame | null {
  return selectSourceTimelineFrameByIndex(timeline, index);
}

export function sourceTimelineNextFrame(timeline: SourceTimeline | null | undefined, currentIndex: number, direction: -1 | 1): SourceTimelineFrame | null {
  if (!timeline) return null;
  const next = sourceTimelineFrameByIndex(timeline, currentIndex + direction);
  return next && next.ptsSec != null ? next : null;
}
