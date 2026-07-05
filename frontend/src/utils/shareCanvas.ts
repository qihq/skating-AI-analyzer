declare global {
  interface Window {
    ClipboardItem?: typeof ClipboardItem;
  }
}

export type ShareImagePreview = {
  url: string;
  blob: Blob;
  filename: string;
  copiedToClipboard: boolean;
  mimeType: string;
  sizeBytes: number;
  canNativeShare: boolean;
};

export type CanvasBlobOptions = {
  type?: "image/jpeg" | "image/png" | "image/webp";
  quality?: number;
};

export type SharePosterSection = {
  label: string;
  title: string;
  body?: string | null;
  meta?: string | null;
  color?: string;
  bg?: string;
};

export type ShareImageResult = {
  blob: Blob;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  canNativeShare: boolean;
};

export function normalizeShareText(value: string | null | undefined, fallback = "") {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text || fallback;
}

function normalizePosterText(value: string | null | undefined, fallback = "") {
  const text = String(value ?? "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .filter(Boolean)
    .join("\n");
  return text || fallback;
}

export function wrapCanvasText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines = Number.POSITIVE_INFINITY) {
  const lines: string[] = [];
  const paragraphs = String(text ?? "").split("\n");
  let truncated = false;

  for (let paragraphIndex = 0; paragraphIndex < paragraphs.length; paragraphIndex += 1) {
    const chars = Array.from(paragraphs[paragraphIndex]);
    let current = "";
    if (!chars.length) {
      if (lines.length < maxLines) {
        lines.push("");
      } else {
        truncated = true;
        break;
      }
    }
    for (const char of chars) {
      const next = `${current}${char}`;
      if (ctx.measureText(next).width <= maxWidth || !current) {
        current = next;
        continue;
      }
      lines.push(current);
      current = char;
      if (lines.length >= maxLines) {
        truncated = true;
        break;
      }
    }
    if (truncated) {
      break;
    }
    if (current) {
      if (lines.length < maxLines) {
        lines.push(current);
      } else {
        truncated = true;
        break;
      }
    }
    if (paragraphIndex < paragraphs.length - 1 && lines.length >= maxLines) {
      truncated = true;
      break;
    }
  }
  if (Number.isFinite(maxLines) && truncated && lines.length) {
    const last = lines[maxLines - 1];
    lines[maxLines - 1] = `${last.slice(0, Math.max(last.length - 1, 0))}…`;
  }
  return lines;
}

export function measureWrappedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
  lineHeight: number,
  maxLines = Number.POSITIVE_INFINITY,
) {
  return wrapCanvasText(ctx, text, maxWidth, maxLines).length * lineHeight;
}

export function drawRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const normalizedRadius = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + normalizedRadius, y);
  ctx.arcTo(x + width, y, x + width, y + height, normalizedRadius);
  ctx.arcTo(x + width, y + height, x, y + height, normalizedRadius);
  ctx.arcTo(x, y + height, x, y, normalizedRadius);
  ctx.arcTo(x, y, x + width, y, normalizedRadius);
  ctx.closePath();
}

export function drawWrappedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  maxLines = Number.POSITIVE_INFINITY,
) {
  const lines = wrapCanvasText(ctx, text, maxWidth, maxLines);
  lines.forEach((line, index) => {
    ctx.fillText(line, x, y + index * lineHeight);
  });
  return lines.length * lineHeight;
}

export async function createAdaptiveSharePoster({
  eyebrow,
  title,
  subtitle,
  scoreLabel,
  scoreValue,
  scoreMeta,
  intro,
  sections,
  footer = "由冰宝（IceBuddy）生成 · 仅供复盘参考",
  filename,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  scoreLabel?: string;
  scoreValue?: string;
  scoreMeta?: string;
  intro?: string;
  sections: SharePosterSection[];
  footer?: string;
  filename: string;
}) {
  const canvas = document.createElement("canvas");
  const width = 1080;
  const scale = 1;
  const measureCanvas = document.createElement("canvas");
  const measureCtx = measureCanvas.getContext("2d");
  if (!measureCtx) {
    throw new Error("share_image_canvas_failed");
  }

  const contentWidth = 856;
  const textWidth = 760;
  const safeTitle = normalizePosterText(title, "IceBuddy 分享");
  const safeSubtitle = normalizePosterText(subtitle, "");
  const safeIntro = normalizePosterText(intro, "");
  const posterSections = sections
    .map((section) => ({
      ...section,
      title: normalizePosterText(section.title, ""),
      body: normalizePosterText(section.body, ""),
      meta: normalizePosterText(section.meta, ""),
      color: section.color ?? "#2563EB",
      bg: section.bg ?? "#EFF6FF",
    }))
    .filter((section) => section.title || section.body || section.meta);

  measureCtx.font = "800 56px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const titleHeight = measureWrappedText(measureCtx, safeTitle, scoreValue ? 560 : contentWidth, 64);
  measureCtx.font = "500 28px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const subtitleHeight = measureWrappedText(measureCtx, safeSubtitle, scoreValue ? 560 : contentWidth, 38);
  measureCtx.font = "500 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  const introHeight = safeIntro ? measureWrappedText(measureCtx, safeIntro, contentWidth, 46) : 0;
  const sectionHeights = posterSections.map((section) => {
    measureCtx.font = "700 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const titleBlock = section.title ? measureWrappedText(measureCtx, section.title, textWidth, 40) : 0;
    measureCtx.font = "500 25px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const bodyBlock = section.body ? measureWrappedText(measureCtx, section.body, textWidth, 34) : 0;
    measureCtx.font = "600 23px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    const metaBlock = section.meta ? measureWrappedText(measureCtx, section.meta, textWidth, 30) : 0;
    return Math.max(138, 84 + titleBlock + (bodyBlock ? 16 + bodyBlock : 0) + (metaBlock ? 14 + metaBlock : 0) + 34);
  });
  const headerHeight = 64 + 86 + titleHeight + 28 + subtitleHeight + (scoreValue ? 0 : 18);
  const contentHeight = Math.max(
    980,
    headerHeight + (safeIntro ? 68 + introHeight : 36) + sectionHeights.reduce((sum, item) => sum + item + 28, 0) + 170,
  );
  const height = Math.min(contentHeight, 32000);
  const isHeightCapped = contentHeight > height;

  canvas.width = width * scale;
  canvas.height = height * scale;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("share_image_canvas_failed");
  }
  ctx.scale(scale, scale);

  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#F8FBFF");
  gradient.addColorStop(0.54, "#EEF7F4");
  gradient.addColorStop(1, "#FFF7ED");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "rgba(255,255,255,0.9)";
  drawRoundRect(ctx, 64, 64, width - 128, height - 128, 44);
  ctx.fill();
  ctx.strokeStyle = "rgba(148,163,184,0.32)";
  ctx.lineWidth = 2;
  ctx.stroke();

  let y = 142;
  ctx.fillStyle = "#2563EB";
  ctx.font = "800 30px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  ctx.fillText(eyebrow, 112, y);

  y += 84;
  ctx.fillStyle = "#0F172A";
  ctx.font = "800 56px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, safeTitle, 112, y, scoreValue ? 560 : contentWidth, 64);

  ctx.fillStyle = "#64748B";
  ctx.font = "500 28px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, safeSubtitle, 112, y + titleHeight + 28, scoreValue ? 560 : contentWidth, 38);

  if (scoreValue) {
    ctx.fillStyle = "#DBEAFE";
    drawRoundRect(ctx, 710, 142, 220, 220, 110);
    ctx.fill();
    ctx.strokeStyle = "#93C5FD";
    ctx.lineWidth = 5;
    ctx.stroke();
    ctx.fillStyle = "#1D4ED8";
    ctx.font = "800 66px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(scoreValue, 820, 244);
    ctx.font = "700 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.fillText(scoreLabel ?? "Score", 820, 288);
    if (scoreMeta) {
      ctx.fillStyle = "#64748B";
      ctx.font = "600 22px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.fillText(scoreMeta, 820, 322);
    }
    ctx.textAlign = "start";
  }

  y += titleHeight + 28 + subtitleHeight + 68;
  if (safeIntro) {
    ctx.fillStyle = "#334155";
    ctx.font = "500 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    y += drawWrappedText(ctx, safeIntro, 112, y, contentWidth, 46) + 60;
  }

  posterSections.forEach((section, index) => {
    const blockHeight = sectionHeights[index];
    if (isHeightCapped && y + blockHeight + 140 > height) {
      return;
    }
    ctx.fillStyle = section.bg;
    drawRoundRect(ctx, 112, y, contentWidth, blockHeight, 28);
    ctx.fill();
    ctx.fillStyle = section.color;
    ctx.font = "800 24px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.fillText(section.label, 152, y + 48);
    let textY = y + 94;
    if (section.title) {
      ctx.fillStyle = "#0F172A";
      ctx.font = "700 31px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      textY += drawWrappedText(ctx, section.title, 152, textY, textWidth, 40) + 16;
    }
    if (section.body) {
      ctx.fillStyle = "#475569";
      ctx.font = "500 25px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      textY += drawWrappedText(ctx, section.body, 152, textY, textWidth, 34) + 14;
    }
    if (section.meta) {
      ctx.fillStyle = "#64748B";
      ctx.font = "600 23px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      drawWrappedText(ctx, section.meta, 152, textY, textWidth, 30);
    }
    y += blockHeight + 28;
  });

  ctx.strokeStyle = "rgba(148,163,184,0.34)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(112, y + 26);
  ctx.lineTo(968, y + 26);
  ctx.stroke();
  ctx.fillStyle = "#94A3B8";
  ctx.font = "500 22px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  drawWrappedText(ctx, footer, 112, y + 82, contentWidth, 30);

  const blob = await canvasToCompressedBlob(canvas, { type: "image/jpeg", quality: 0.82, maxBytes: 2_400_000 });
  return createShareImageResult(blob, filename);
}

export function canvasToBlob(canvas: HTMLCanvasElement, options: CanvasBlobOptions = {}) {
  const type = options.type ?? "image/jpeg";
  const quality = options.quality ?? 0.82;
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
        return;
      }
      reject(new Error("share_image_blob_failed"));
    }, type, quality);
  });
}

export async function canvasToCompressedBlob(
  canvas: HTMLCanvasElement,
  options: CanvasBlobOptions & { maxBytes?: number } = {},
) {
  const type = options.type ?? "image/jpeg";
  let quality = options.quality ?? 0.82;
  let blob = await canvasToBlob(canvas, { type, quality });
  const maxBytes = options.maxBytes ?? 1_500_000;

  while (type !== "image/png" && blob.size > maxBytes && quality > 0.62) {
    quality = Math.max(0.62, quality - 0.08);
    blob = await canvasToBlob(canvas, { type, quality });
  }

  return blob;
}

export async function copyImageBlobToClipboard(blob: Blob) {
  const ClipboardItemConstructor = window.ClipboardItem;
  if (!navigator.clipboard?.write || !ClipboardItemConstructor) {
    return false;
  }

  try {
    const clipboardBlob = blob.type === "image/png" ? blob : await convertImageBlob(blob, "image/png");
    await navigator.clipboard.write([
      new ClipboardItemConstructor({
        [clipboardBlob.type]: clipboardBlob,
      }),
    ]);
    return true;
  } catch {
    return false;
  }
}

async function convertImageBlob(blob: Blob, type: "image/png" | "image/jpeg", quality = 0.92) {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    bitmap.close();
    throw new Error("share_image_canvas_failed");
  }
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  return canvasToBlob(canvas, { type, quality });
}

export function canNativeShareImage(blob: Blob, filename: string) {
  if (!navigator.canShare || !navigator.share) {
    return false;
  }
  try {
    const file = new File([blob], filename, { type: blob.type });
    return navigator.canShare({ files: [file] });
  } catch {
    return false;
  }
}

export async function shareImageFile(blob: Blob, filename: string, title = "IceBuddy 分享图", text?: string) {
  if (!navigator.share) {
    return false;
  }
  try {
    const file = new File([blob], filename, { type: blob.type });
    if (navigator.canShare && !navigator.canShare({ files: [file] })) {
      return false;
    }
    await navigator.share({ title, text, files: [file] });
    return true;
  } catch {
    return false;
  }
}

export function createShareImageResult(blob: Blob, filename: string): ShareImageResult {
  return {
    blob,
    filename,
    mimeType: blob.type,
    sizeBytes: blob.size,
    canNativeShare: canNativeShareImage(blob, filename),
  };
}

export function createShareImagePreview(result: ShareImageResult, copiedToClipboard: boolean): ShareImagePreview {
  return {
    ...result,
    url: URL.createObjectURL(result.blob),
    copiedToClipboard,
  };
}
