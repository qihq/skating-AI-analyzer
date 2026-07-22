import { useEffect, useRef, useState } from "react";

import type { GrowthMilestone } from "../api/client";
import { createMilestoneShareImage, MilestoneShareInput } from "../utils/milestoneShareCanvas";
import {
  canNativeShareImage,
  copyImageBlobToClipboard,
  shareImageFile,
  ShareImageResult,
} from "../utils/shareCanvas";

interface MilestoneShareDialogProps {
  open: boolean;
  onClose: () => void;
  skaterName: string;
  milestone: GrowthMilestone;
  frameUrl?: string | null;
  metric?: { label: string; value: string; definition: string } | null;
}

export default function MilestoneShareDialog({
  open,
  onClose,
  skaterName,
  milestone,
  frameUrl,
  metric,
}: MilestoneShareDialogProps) {
  const [result, setResult] = useState<ShareImageResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previewUrl = useRef<string | null>(null);

  useEffect(() => {
    if (!open) {
      setResult(null);
      setError(null);
      setCopied(false);
      if (previewUrl.current) {
        URL.revokeObjectURL(previewUrl.current);
        previewUrl.current = null;
      }
      return;
    }

    let cancelled = false;
    setBusy(true);
    setError(null);

    const input: MilestoneShareInput = { skaterName, milestone, frameUrl, metric };
    createMilestoneShareImage(input)
      .then((res) => {
        if (cancelled) return;
        setResult(res);
        previewUrl.current = URL.createObjectURL(res.blob);
        setBusy(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "生成分享图失败。");
        setBusy(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, skaterName, milestone, frameUrl, metric]);

  if (!open) return null;

  const handleDownload = () => {
    if (!result) return;
    const link = document.createElement("a");
    link.href = previewUrl.current ?? URL.createObjectURL(result.blob);
    link.download = result.filename;
    link.click();
  };

  const handleCopy = async () => {
    if (!result) return;
    const ok = await copyImageBlobToClipboard(result.blob);
    setCopied(ok);
    if (ok) window.setTimeout(() => setCopied(false), 2200);
  };

  const handleShare = async () => {
    if (!result) return;
    await shareImageFile(result.blob, result.filename, milestone.title ?? "里程碑");
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="分享里程碑"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="max-h-[90vh] w-full max-w-md overflow-auto rounded-[28px] bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-900">分享里程碑</h2>
          <button type="button" onClick={onClose} className="rounded-full px-3 py-1 text-sm font-semibold text-slate-500 hover:bg-slate-100">
            ✕
          </button>
        </div>

        {busy ? (
          <p className="mt-8 py-12 text-center text-sm text-slate-500">正在生成分享图…</p>
        ) : error ? (
          <p role="alert" className="mt-6 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</p>
        ) : previewUrl.current ? (
          <>
            <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
              <img src={previewUrl.current} alt="里程碑分享预览" className="w-full" />
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                className="app-pill min-h-[44px] px-5 text-sm font-semibold"
                onClick={() => void handleCopy()}
              >
                {copied ? "已复制" : "复制到剪贴板"}
              </button>
              <button
                type="button"
                className="app-pill min-h-[44px] px-5 text-sm font-semibold"
                onClick={handleDownload}
              >
                保存图片
              </button>
              {result && canNativeShareImage(result.blob, result.filename) ? (
                <button
                  type="button"
                  className="app-pill min-h-[44px] px-5 text-sm font-semibold"
                  onClick={() => void handleShare()}
                >
                  系统分享
                </button>
              ) : null}
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
