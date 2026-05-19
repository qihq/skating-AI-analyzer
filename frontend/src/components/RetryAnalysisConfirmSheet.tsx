type RetryAnalysisConfirmSheetProps = {
  isSubmitting: boolean;
  retryFromStage?: string | null;
  mode?: "analysis" | "report";
  onClose: () => void;
  onConfirm: () => void;
};

export default function RetryAnalysisConfirmSheet({
  isSubmitting,
  retryFromStage,
  mode = "analysis",
  onClose,
  onConfirm,
}: RetryAnalysisConfirmSheetProps) {
  const isReportOnly = mode === "report";

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/36 px-4 backdrop-blur-sm">
      <section
        className="w-full max-w-lg rounded-t-[2rem] bg-white px-6 pt-4 shadow-[0_-18px_50px_rgba(15,23,42,0.2)]"
        style={{ paddingBottom: "calc(1.5rem + env(safe-area-inset-bottom))" }}
      >
        <div className="mx-auto h-1.5 w-14 rounded-full bg-slate-200" />
        <p className="mt-5 text-xs font-semibold uppercase tracking-[0.32em] text-amber-500">{isReportOnly ? "Regenerate Report" : "Retry Analysis"}</p>
        <h2 className="mt-3 text-2xl font-semibold text-slate-900">{isReportOnly ? "重新生成这份报告？" : "重新分析这个视频？"}</h2>
        <p className="mt-4 text-sm leading-7 text-slate-500">
          {isReportOnly ? "将复用已保存的视觉和生物力学结果，只重新生成文字报告并覆盖当前报告。" : "将消耗一次 AI 调用额度，原有报告将被覆盖。"}
        </p>
        {retryFromStage ? (
          <div className="mt-4 rounded-[22px] border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            将从 {retryFromStage} 阶段继续重试，尽量复用已完成的结果。
          </div>
        ) : null}

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} disabled={isSubmitting} className="app-pill">
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting}
            className="min-h-[44px] rounded-full bg-amber-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? "提交中..." : isReportOnly ? "确认生成" : "确认分析"}
          </button>
        </div>
      </section>
    </div>
  );
}
