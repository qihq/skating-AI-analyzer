import type { PoseFrame, PoseKeypoint, PoseGeometry } from "../api/client";

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

export function isLimbUncertain(point: PoseKeypoint): boolean {
  return point.quality?.limb_consistency?.status === "uncertain";
}

export function isDisplayPoint(point: PoseKeypoint): boolean {
  return Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1
    && Number.isFinite(point.visibility) && point.visibility >= 0.5 && point.interpolated !== true && point.usable !== false
    && !["interpolated-display-only", "missing", "clipped", "identity-blocked"].includes(point.provenance ?? "");
}

export function isDisplayFrame(frame: PoseFrame): boolean {
  return frame.input_binding_valid !== false
    && frame.image_binding_valid !== false
    && frame.identity_status !== "identity_unconfirmed"
    && !["lost", "interpolated", "low_confidence"].includes(frame.tracking_state ?? "")
    && !["full_frame_yolo_relock_pending", "local_zoom_yolo_relock_pending", "relock_pending", "detector_relocked", "relocked", "continuity_rejected", "relock_rejected", "lost_reused", "input_unreliable"].includes(frame.tracker_state ?? "")
    && (!frame.temporal?.binding || frame.temporal.time_source === "bound_source_pts")
    && frame.identity_state !== "lost"
    && !["missing", "identity-blocked", "interpolated-display-only"].includes(frame.pose_provenance ?? "");
}

// A rendition can round its width by up to two encoded pixels. Reject aspect
// changes beyond that allowance (rotation/crop cannot be guessed from dimensions).
export function validVideoGeometry(g: PoseGeometry | null | undefined, mw: number, mh: number): g is PoseGeometry {
  if (!g || g.schema_version !== "pose-geometry.v1" || g.coordinate_space !== "sample_normalized" || g.rotation_degrees !== 0 || g.crop !== "none" || g.provenance !== "saved_metadata_verified_frames") return false;
  const r = g.content_rect;
  if (!r || ![g.sample_width,g.sample_height,g.source_width,g.source_height,r.width,r.height,mw,mh].every(v => Number.isFinite(v) && v > 0) || ![r.x,r.y].every(v => Number.isFinite(v) && v >= 0)) return false;
  return r.x+r.width <= g.sample_width && r.y+r.height <= g.sample_height
    && Math.abs(r.width - g.source_width/g.source_height*r.height) <= 1
    && Math.abs(mw-g.source_width/g.source_height*mh) <= 2;
}

export function drawPoseOverlay(
  canvas: HTMLCanvasElement,
  frame: PoseFrame,
  connections: number[][],
  options: { mediaWidth: number; mediaHeight: number; coordinateTarget?: "video"; geometry?: PoseGeometry | null },
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
  if (!isDisplayFrame(frame)) return;
  const geometry = options.geometry;
  if (options.coordinateTarget === "video" && !validVideoGeometry(geometry, options.mediaWidth, options.mediaHeight)) return;
  const visible = frame.keypoints.filter(point => isDisplayPoint(point) && frame.usable_joint_mask?.[String(point.id)] !== false);
  const mapped = options.coordinateTarget === "video" && geometry ? visible.map(point => ({...point,
    x: (point.x*geometry.sample_width-geometry.content_rect.x)/geometry.content_rect.width,
    y: (point.y*geometry.sample_height-geometry.content_rect.y)/geometry.content_rect.height,
  })).filter(point => isDisplayPoint(point)) : visible;
  const points = new Map(mapped.map(point => [point.id,point]));


  for (const [from, to] of connections) {
    const a = points.get(from);
    const b = points.get(to);
    if (!a || !b) continue;
    const uncertain = isLimbUncertain(a) || isLimbUncertain(b);
    context.strokeStyle = uncertain ? "rgba(249, 115, 22, 0.95)" : "rgba(226, 232, 240, 0.82)";
    context.setLineDash?.(uncertain ? [4,3] : []);
    context.lineWidth = 3;
    context.beginPath();
    context.moveTo(x(a.x), y(a.y));
    context.lineTo(x(b.x), y(b.y));
    context.stroke();
  }

  context.setLineDash?.([]);
  if (mapped.some(isLimbUncertain)) {
    context.fillStyle = "#F97316";
    context.font = "12px sans-serif";
    context.fillText("虚线：肢体位置存疑，原始点未用于分析", rect.x + 6, rect.y + 16);
  }

  for (const point of points.values()) {
    context.fillStyle = isLimbUncertain(point) ? "#F97316" : pointColor(point);
    context.beginPath();
    context.arc(x(point.x), y(point.y), AXIS_POINTS.has(point.id) ? 5 : 4, 0, Math.PI * 2);
    context.fill();
  }
}
