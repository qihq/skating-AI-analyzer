import type { MonthlyChapter } from "../api/client";

interface AnnualChapterPickerProps {
  chapters: MonthlyChapter[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

export default function AnnualChapterPicker({ chapters, selectedIds, onChange }: AnnualChapterPickerProps) {
  const selected = new Set(selectedIds);

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(chapters.filter((chapter) => next.has(chapter.id)).map((chapter) => chapter.id));
  };

  if (!chapters.length) {
    return <p className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-700">本年度还没有已发布的月度章节。请先发布至少一个章节，再生成年度合集。</p>;
  }

  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-semibold text-slate-800">选择已发布章节</legend>
      <p className="text-sm leading-6 text-slate-500">年度合集只会包含已发布的版本；之后仍可用相同快照重新生成。</p>
      <div className="grid gap-3">
        {chapters.map((chapter) => (
          <label key={chapter.id} className="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200 px-4 py-3 hover:border-blue-300">
            <input
              type="checkbox"
              aria-label={`${chapter.year_month} 第 ${chapter.revision} 版`}
              checked={selected.has(chapter.id)}
              onChange={() => toggle(chapter.id)}
              className="mt-1 h-4 w-4 accent-blue-600"
            />
            <span className="min-w-0">
              <span className="block font-semibold text-slate-800">{chapter.year_month} - 第 {chapter.revision} 版</span>
              <span className="mt-1 block line-clamp-2 text-sm leading-6 text-slate-500">{chapter.final_text || "未填写最终文字"}</span>
              {chapter.representative_frames.length === 0 ? <span className="mt-2 inline-block rounded-full bg-amber-50 px-2 py-1 text-xs text-amber-700">文字章节</span> : null}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
