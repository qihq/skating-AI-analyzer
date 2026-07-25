import { useState } from "react";

import { MonthlyChapter } from "../api/client";
import { Button, Input } from "../modern/AnimalUi";
import ModernConfirmModal from "../modern/ModernConfirmModal";

const FINAL_TEXT_MAX_LEN = 2400;

interface MonthlyChapterEditorProps {
  chapter: MonthlyChapter;
  onSaveDraft: (finalText: string, title: string) => Promise<void>;
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
  const [title, setTitle] = useState(chapter.title || `${chapter.year_month} 月度成长记录`);
  const [confirmPublish, setConfirmPublish] = useState(false);

  return (
    <section className="app-card p-5 tablet:p-6">
      <h2 className="text-xl font-semibold text-slate-900">编辑与发布</h2>
      <p className="mt-2 text-sm text-slate-500">
        {isPublished
          ? "本修订已发布并锁定；保存修改会创建一个新的可编辑修订，旧版本保持不变。"
          : "“AI 初稿”为模型生成，“最终文字”为家长编辑结果；两版分别留存，发布后本修订只读。"}
      </p>

      {chapter.draft_text ? (
        <details className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600" open={!isPublished}>
          <summary className="cursor-pointer font-semibold text-slate-700">AI 初稿</summary>
          <pre className="mt-3 whitespace-pre-wrap font-sans leading-7">{chapter.draft_text}</pre>
        </details>
      ) : null}

      <label className="mt-5 block space-y-2">
        <span className="text-sm font-medium text-slate-700">月报标题</span>
        <Input aria-label="月报标题" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} disabled={saving} className="w-full" />
      </label>

      <label className="mt-5 block space-y-2">
        <span className="text-sm font-medium text-slate-700">最终文字（家长可编辑）</span>
        <textarea
          aria-label="最终文字"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={10}
          maxLength={FINAL_TEXT_MAX_LEN}
          disabled={saving}
          placeholder="可在 AI 初稿基础上编辑，保留本次成长记录。"
          className="app-textarea min-h-[220px] resize-y"
        />
        <span className="text-xs font-semibold text-slate-400">{draft.length}/{FINAL_TEXT_MAX_LEN}</span>
      </label>

      {error ? <p role="alert" className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</p> : null}

      <div className="mt-5 flex flex-wrap gap-3">
        <Button
          onClick={() => void onSaveDraft(draft, title)}
          disabled={saving}
          loading={saving}
        >
          {saving ? "保存中…" : isPublished ? "创建新版本" : "保存修改"}
        </Button>
        <Button
          type="primary"
          onClick={() => setConfirmPublish(true)}
          disabled={isPublished || saving}
        >
          确认发布
        </Button>
        {isPublished ? <span className="self-center text-sm font-semibold text-emerald-600">已发布</span> : null}
      </div>
      <ModernConfirmModal
        open={confirmPublish}
        title="确认发布月度报告"
        description="发布后本修订将锁定为只读；后续修改会创建新版本。"
        confirmLabel="确认发布"
        loading={saving}
        onCancel={() => setConfirmPublish(false)}
        onConfirm={() => void onPublish().finally(() => setConfirmPublish(false))}
      />
    </section>
  );
}
