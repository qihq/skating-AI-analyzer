import { useState } from "react";

import type { GrowthMilestone, MilestoneVerification } from "../api/client";
import MilestoneShareDialog from "./MilestoneShareDialog";

interface MilestoneTimelineProps {
  items: GrowthMilestone[];
  skaterName?: string;
}

const VERIFICATION_LABELS: Record<MilestoneVerification, string> = {
  system_detected: "系统检测",
  parent_confirmed: "家长确认",
  coach_confirmed: "教练确认",
};

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "日期待确认";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export default function MilestoneTimeline({ items, skaterName = "小滑手" }: MilestoneTimelineProps) {
  const [shareTarget, setShareTarget] = useState<GrowthMilestone | null>(null);

  return (
    <section className="app-card p-4 phone:p-5 tablet:p-6" aria-labelledby="milestone-title">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Highlights</p>
      <h2 id="milestone-title" className="mt-2 text-2xl font-semibold text-slate-900">成长里程碑</h2>
      {items.length ? (
        <ol className="mt-5 space-y-4">
          {items.map((item) => (
            <li key={item.id} className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <time dateTime={item.occurred_at} className="text-sm text-slate-500">
                  {formatDate(item.occurred_at)}
                </time>
                <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-blue-600">
                  {VERIFICATION_LABELS[item.verification]}
                </span>
              </div>
              <h3 className="mt-3 text-lg font-semibold text-slate-900">{item.title}</h3>
              {item.note ? <p className="mt-2 text-sm leading-6 text-slate-600">{item.note}</p> : null}
              <button
                type="button"
                className="mt-3 rounded-full px-4 py-1.5 text-xs font-semibold text-blue-600 transition hover:bg-blue-50"
                onClick={() => setShareTarget(item)}
              >
                分享
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-5 rounded-[20px] bg-slate-50 p-5 text-sm text-slate-500">还没有已确认的成长里程碑</p>
      )}

      {shareTarget ? (
        <MilestoneShareDialog
          open
          onClose={() => setShareTarget(null)}
          skaterName={skaterName}
          milestone={shareTarget}
        />
      ) : null}
    </section>
  );
}
