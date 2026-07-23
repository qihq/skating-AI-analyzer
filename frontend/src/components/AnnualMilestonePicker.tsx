import type { AnnualMilestone } from "../api/client";

interface AnnualMilestonePickerProps {
  milestones: AnnualMilestone[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

export default function AnnualMilestonePicker({ milestones, selectedIds, onChange }: AnnualMilestonePickerProps) {
  const selected = new Set(selectedIds);
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    onChange(milestones.filter((item) => next.has(item.id)).map((item) => item.id));
  };
  if (!milestones.length) return null;
  return (
    <fieldset className="space-y-3 border-t border-slate-100 pt-5">
      <legend className="text-sm font-semibold text-slate-800">选择年度里程碑</legend>
      <div className="grid gap-2">
        {milestones.map((milestone) => (
          <label key={milestone.id} className="flex cursor-pointer items-start gap-3 rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <input type="checkbox" aria-label={milestone.title} checked={selected.has(milestone.id)} onChange={() => toggle(milestone.id)} className="mt-1 accent-blue-600" />
            <span>{milestone.occurred_at.slice(0, 10)} - {milestone.title}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
