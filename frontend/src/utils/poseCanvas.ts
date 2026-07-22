import type { PoseFrame, PoseKeypoint } from "../api/client";

export type ContainRect = { x: number; y: number; width: number; height: number };

export function computeContainRect(
  containerWidth: number,
  containerHeight: number,
  mediaWidth: number,
  mediaHeight: number,
): ContainRect {
  if (containerWidth <= 0 || containerHeight <= 0 || mediaWidth <= 0 || mediaHeight <= 0) {
    return { x: 0, y: 0, width: containerWidth, height: containerHeight };
  }

  const scale = Math.min(containerWidth / mediaWidth, containerHeight / mediaHeight);
  const width = mediaWidth * scale;
  const height = mediaHeight * scale;
  return { x: (containerWidth - width) / 2, y: (containerHeight - height) / 2, width, height };
}

const UPPER_BODY = new Set([11, 12, 13, 14, 15, 16]);
const LOWER_BODY = new Set([23, 24, 25, 26, 27, 28, 29, 30, 31, 32]);
const AXIS_POINTS = new Set([0, 11, 12, 23, 24]);

function pointColor(point: PoseKeypoint) {
  if (AXIS_POINTS.has(point.id)) return "#F8FAFC";
  if (UPPER_BODY.has(point.id)) return "#34D399";
  if (LOWER_BODY.has(point.id)) return "#F59E0B";
  return "#38BDF8";
}

export function drawPoseOverlay(
  canvas: HTMLCanvasElement,
  frame: PoseFrame,
  connections: number[][],
  options: { mediaWidth: number; mediaHeight: number },
) {
  const context = canvas.getContext("2d");
  if (!context) return;

  const width = canvas.clientWidth || 720;
  const height = canvas.clientHeight || Math.round(width * 0.5625);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 3);
  canvas.width = Math.round(width * pixelRatio);
  canvas.height = Math.round(height * pixelRatio);
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  // The image uses object-contain, so landmarks must use the same contained area.
  const rect = computeContainRect(width, height, options.mediaWidth, options.mediaHeight);
  const x = (value: number) => rect.x + value * rect.width;
  const y = (value: number) => rect.y + value * rect.height;
  const points = new Map(frame.keypoints.map((point) => [point.id, point]));

  if (frame.target_bbox) {
    context.strokeStyle = "rgba(56, 189, 248, 0.95)";
    context.lineWidth = 2;
    context.strokeRect(
      x(frame.target_bbox.x),
      y(frame.target_bbox.y),
      frame.target_bbox.width * rect.width,
      frame.target_bbox.height * rect.height,
    );
  }

  for (const [from, to] of connections) {
    const a = points.get(from);
    const b = points.get(to);
    if (!a || !b || a.visibility < 0.5 || b.visibility < 0.5) continue;
    context.strokeStyle = "rgba(226, 232, 240, 0.82)";
    context.lineWidth = 3;
    context.beginPath();
    context.moveTo(x(a.x), y(a.y));
    context.lineTo(x(b.x), y(b.y));
    context.stroke();
  }

  for (const point of frame.keypoints) {
    if (point.visibility < 0.5) continue;
    context.fillStyle = pointColor(point);
    context.beginPath();
    context.arc(x(point.x), y(point.y), AXIS_POINTS.has(point.id) ? 5 : 4, 0, Math.PI * 2);
    context.fill();
  }
}
