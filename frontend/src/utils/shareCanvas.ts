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
};

export function wrapCanvasText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines: number) {
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
  if (lines.length === maxLines && chars.join("").length > lines.join("").length) {
    const last = lines[maxLines - 1];
    lines[maxLines - 1] = `${last.slice(0, Math.max(last.length - 1, 0))}…`;
  }
  return lines;
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
  maxLines: number,
) {
  const lines = wrapCanvasText(ctx, text, maxWidth, maxLines);
  lines.forEach((line, index) => {
    ctx.fillText(line, x, y + index * lineHeight);
  });
  return lines.length * lineHeight;
}

export function canvasToBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
        return;
      }
      reject(new Error("share_image_blob_failed"));
    }, "image/png", 0.96);
  });
}

export async function copyImageBlobToClipboard(blob: Blob) {
  const ClipboardItemConstructor = window.ClipboardItem;
  if (!navigator.clipboard?.write || !ClipboardItemConstructor) {
    return false;
  }

  try {
    await navigator.clipboard.write([
      new ClipboardItemConstructor({
        [blob.type]: blob,
      }),
    ]);
    return true;
  } catch {
    return false;
  }
}
