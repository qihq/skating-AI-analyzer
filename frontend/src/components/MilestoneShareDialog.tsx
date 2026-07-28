import { useEffect, useState } from "react";

import type { GrowthMilestone } from "../api/client";
import { createShareImagePreview, ShareImagePreview } from "../utils/shareCanvas";
import { exportShareDocument } from "../utils/shareExport";
import IslandShareDialog from "../modern/IslandShareDialog";

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
  const [previews, setPreviews] = useState<ShareImagePreview[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setPreviews([]);
      setError(null);
      return;
    }

    let cancelled = false;
    setBusy(true);
    setError(null);

    exportShareDocument({
      eyebrow: "Animal Island · 里程碑",
      title: milestone.title ?? "成长里程碑",
      subtitle: skaterName,
      intro: milestone.note ?? "每一次小进步都值得被记住。",
      sections: [{ label: metric?.label ?? "成长记录", title: metric?.value ?? milestone.title ?? "解锁新进步", body: metric?.definition ?? milestone.note ?? "", meta: milestone.occurred_at }],
      filename: `milestone-${milestone.id}.jpg`,
    })
      .then((res) => {
        if (cancelled) return;
        setPreviews(res.pages.map((page) => createShareImagePreview(page, false)));
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

  return <IslandShareDialog preview={null} previews={previews} title="分享里程碑" onClose={onClose} extraActions={busy ? <span>正在生成…</span> : error ? <span role="alert">{error}</span> : null} />;
}
