import {
  canvasToCompressedBlob,
  createShareImageResult,
  drawWrappedText,
  ShareImageResult,
} from "./shareCanvas";
import type { GrowthMilestone } from "../api/client";

const WIDTH = 1080;
const HEIGHT = 1350;
const MAX_BYTES = 2_400_000;

const PHASE_BG = "#EEF2FF";
const PHASE_FG = "#4F46E5";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

const VERIFICATION_LABELS: Record<string, string> = {
  system_detected: "系统检测",
  parent_confirmed: "家长确认",
  coach_confirmed: "教练确认",
};

export interface MilestoneShareInput {
  skaterName: string;
  milestone: GrowthMilestone;
  frameUrl?: string | null;
  metric?: { label: string; value: string; definition: string } | null;
}

export async function createMilestoneShareImage(
  input: MilestoneShareInput,
): Promise<ShareImageResult> {
  const { skaterName, milestone, frameUrl, metric } = input;

  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("share_image_canvas_failed");

  // Background
  const gradient = ctx.createLinearGradient(0, 0, 0, HEIGHT);
  gradient.addColorStop(0, "#F0F9FF");
  gradient.addColorStop(0.45, "#F0FDF4");
  gradient.addColorStop(1, "#FFF7ED");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  let mediaY = 0;
  const mediaHeight = frameUrl ? 540 : 0;

  if (frameUrl) {
    ctx.fillStyle = "#E2E8F0";
    ctx.fillRect(80, 80, WIDTH - 160, mediaHeight);
    try {
      const img = await loadImage(frameUrl);
      const scale = Math.min(
        (WIDTH - 160) / img.naturalWidth,
        mediaHeight / img.naturalHeight,
      );
      const drawW = img.naturalWidth * scale;
      const drawH = img.naturalHeight * scale;
      const drawX = 80 + ((WIDTH - 160) - drawW) / 2;
      const drawY = 80 + (mediaHeight - drawH) / 2;
      ctx.drawImage(img, drawX, drawY, drawW, drawH);
    } catch {
      // Frame failed to load -> use gradient panel (already filled)
      ctx.fillStyle = "#F1F5F9";
      ctx.fillRect(80, 80, WIDTH - 160, mediaHeight);
      ctx.fillStyle = "#94A3B8";
      ctx.font = "500 28px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("暂无动作画面", WIDTH / 2, 80 + mediaHeight / 2);
      ctx.textAlign = "start";
    }
    mediaY = 80 + mediaHeight + 48;
  } else {
    mediaY = 120;
  }

  // Title
  ctx.fillStyle = "#0F172A";
  ctx.font = "800 52px system-ui, sans-serif";
  drawWrappedText(ctx, milestone.title ?? "", 112, mediaY, WIDTH - 224, 62, 2);

  // Date badge
  const dateStr = formatDate(milestone.occurred_at);
  let badgeY = mediaY + (milestone.title && milestone.title.length > 12 ? 150 : 90);
  if (dateStr) {
    ctx.fillStyle = "#DBEAFE";
    ctx.beginPath();
    ctx.arc(112 + 12, badgeY + 22, 16, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#1D4ED8";
    ctx.font = "700 22px system-ui, sans-serif";
    ctx.fillText("📅", 112, badgeY + 30);
    ctx.fillStyle = "#475569";
    ctx.font = "600 24px system-ui, sans-serif";
    ctx.fillText(dateStr, 150, badgeY + 30);
    badgeY += 56;
  }

  // Skater name
  ctx.fillStyle = "#64748B";
  ctx.font = "500 28px system-ui, sans-serif";
  ctx.fillText(skaterName, 112, badgeY);
  badgeY += 48;

  // Verification badge
  const vLabel = VERIFICATION_LABELS[milestone.verification] ?? "系统检测";
  ctx.fillStyle = PHASE_BG;
  const vTextWidth = ctx.measureText(vLabel).width + 48;
  ctx.beginPath();
  const vX = 112, vY = badgeY, vW = vTextWidth, vH = 44;
  ctx.moveTo(vX + 22, vY);
  ctx.lineTo(vX + vW - 22, vY);
  ctx.arcTo(vX + vW, vY, vX + vW, vY + 22, 22);
  ctx.arcTo(vX + vW, vY + vH, vX + vW - 22, vY + vH, 22);
  ctx.arcTo(vX, vY + vH, vX, vY + vH - 22, 22);
  ctx.arcTo(vX, vY, vX + 22, vY, 22);
  ctx.fill();
  ctx.fillStyle = PHASE_FG;
  ctx.font = "700 24px system-ui, sans-serif";
  ctx.fillText(vLabel, 136, badgeY + 30);
  badgeY += 66;

  // Note
  if (milestone.note) {
    ctx.fillStyle = "#334155";
    ctx.font = "500 28px system-ui, sans-serif";
    badgeY += drawWrappedText(ctx, `「${milestone.note}」`, 112, badgeY, WIDTH - 224, 42, 4) + 40;
  }

  // Metric panel
  if (metric) {
    ctx.fillStyle = "#FFFFFF";
    ctx.beginPath();
    const mH = 120;
    ctx.moveTo(112 + 28, badgeY);
    ctx.lineTo(WIDTH - 112 - 28, badgeY);
    ctx.arcTo(WIDTH - 112, badgeY, WIDTH - 112, badgeY + 28, 28);
    ctx.arcTo(WIDTH - 112, badgeY + mH, WIDTH - 112 - 28, badgeY + mH, 28);
    ctx.arcTo(112, badgeY + mH, 112, badgeY + mH - 28, 28);
    ctx.arcTo(112, badgeY, 112 + 28, badgeY, 28);
    ctx.fill();
    ctx.strokeStyle = "rgba(148,163,184,0.3)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#0F172A";
    ctx.font = "800 44px system-ui, sans-serif";
    ctx.fillText(metric.value, 152, badgeY + 56);
    ctx.fillStyle = "#475569";
    ctx.font = "600 26px system-ui, sans-serif";
    ctx.fillText(metric.label, 152 + ctx.measureText(metric.value).width + 24, badgeY + 56);
    ctx.fillStyle = "#94A3B8";
    ctx.font = "500 22px system-ui, sans-serif";
    ctx.fillText(metric.definition, 152, badgeY + 96);
    badgeY += 148;
  }

  // Footer
  const footerY = Math.max(badgeY + 40, HEIGHT - 120);
  ctx.strokeStyle = "rgba(148,163,184,0.24)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(112, footerY - 28);
  ctx.lineTo(WIDTH - 112, footerY - 28);
  ctx.stroke();
  ctx.fillStyle = "#94A3B8";
  ctx.font = "500 22px system-ui, sans-serif";
  ctx.fillText("由冰宝（IceBuddy）生成 · 仅供复盘参考", 112, footerY + 14);

  const blob = await canvasToCompressedBlob(canvas, {
    type: "image/jpeg",
    quality: 0.82,
    maxBytes: MAX_BYTES,
  });

  const safeName = (milestone.title ?? "milestone").replace(/[^a-zA-Z0-9一-鿿_-]/g, "_").slice(0, 40);
  return createShareImageResult(blob, `milestone-${safeName}.jpg`);
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}
