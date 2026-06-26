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

export function wrapCanvasText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines = Number.POSITIVE_INFINITY) {
  const chars = Array.from(text);
  const lines: string[] = [];
  let current = "";

  for (const char of chars) {
    const next = `${current}${char}`;
    if (ctx.measureText(next).width <= maxWidth || !current) {
      current = next;
      continue;
    }
    lines.push(current);
    current = char;
    if (lines.length >= maxLines) {
      break;
    }
  }

  if (lines.length < maxLines && current) {
    lines.push(current);
  }
  if (lines.length > maxLines) {
    lines.length = maxLines;
  }
  if (Number.isFinite(maxLines) && lines.length === maxLines && chars.join("").length > lines.join("").length) {
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
