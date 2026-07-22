import { useState } from "react";

import { MonthlyChapter } from "../api/client";

const FINAL_TEXT_MAX_LEN = 2400;

interface MonthlyChapterEditorProps {
  chapter: MonthlyChapter;
  onSaveDraft: (finalText: string) => Promise<void>;
  onPublish: () => Promise<void>;
  saving: boolean;
  error: string | null;
}

export default function MonthlyChapterEditor({
  chapter,
  onSaveDraft,
  onPublish,
  saving,
  error,
}: MonthlyChapterEditorProps) {
  const isPublished = chapter.status === "published";
  const [draft, setDraft] = useState(chapter.final_text ?? chapter.draft_text ?? "");

  return (
    <section className="app-card p-5 tablet:p-6">
      <h2 className="text-xl font-semibold text-slate-900">编辑与发布</h2>
      <p className="mt-2 text-sm text-slate-500">
        {isPublished
          ? "本修订已发布并锁定，不可再修改。如需更新，请新建下一个修订。"
          : "“AI 初稿”为模型生成，“最终文字”为家长编辑结果；两版分别留存，发布后本修订只读。"}
      </p>

      {chapter.draft_text ? (
        <details className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600" open={!isPublished}>
          <summary className="cursor-pointer font-semibold text-slate-700">AI 初稿</summary>
          <pre className="mt-3 whitespace-pre-wrap font-sans leading-7">{chapter.draft_text}</pre>
        </details>
      ) : null}

      <label className="mt-5 block space-y-2">
        <span className="text-sm font-medium text-slate-700">最终文字（家长可编辑）</span>
        <textarea
          aria-label="最终文字"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={10}
          maxLength={FINAL_TEXT_MAX_LEN}
          disabled={isPublished || saving}
          placeholder="可在 AI 初稿基础上编辑，保留本次成长记录。"
          className="app-textarea min-h-[220px] resize-y"
        />
        <span className="text-xs font-semibold text-slate-400">{draft.length}/{FINAL_TEXT_MAX_LEN}</span>
      </label>

      {error ? <p role="alert" className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</p> : null}

      <div className="mt-5 flex flex-wrap gap-3">
        <button
          type="button"
          className="app-pill min-h-[44px] px-5 text-sm font-semibold"
          onClick={() => void onSaveDraft(draft)}
          disabled={isPublished || saving}
        >
          保存修改
        </button>
        <button
          type="button"
          className="min-h-[44px] rounded-full bg-blue-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-55"
          onClick={() => {
            if (window.confirm("发布后本修订将只读，确定发布吗？")) {
              void onPublish();
            }
          }}
          disabled={isPublished || saving}
        >
          确认发布
        </button>
        {isPublished ? <span className="self-center text-sm font-semibold text-emerald-600">已发布</span> : null}
      </div>
    </section>
  );
}