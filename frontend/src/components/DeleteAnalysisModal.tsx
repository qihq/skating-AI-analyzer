import PinInput from "./PinInput";

type DeleteAnalysisModalProps = {
  step: "confirm" | "pin";
  pin: string;
  pinLength: number;
  error: string | null;
  isSubmitting: boolean;
  onChangePin: (value: string) => void;
  onClose: () => void;
  onConfirmDelete: () => void;
  onSubmitPin: () => void;
};

export default function DeleteAnalysisModal({
  step,
  pin,
  pinLength,
  error,
  isSubmitting,
  onChangePin,
  onClose,
  onConfirmDelete,
  onSubmitPin,
}: DeleteAnalysisModalProps) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/36 px-4 backdrop-blur-sm">
      <section className="app-card w-full max-w-md p-6 tablet:p-7">
        {step === "confirm" ? (
          <>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-amber-500">Warning</p>
            <h2 className="mt-3 text-2xl font-semibold text-slate-900">确认删除？</h2>
            <p className="mt-4 text-sm leading-7 text-slate-500">删除后将同时移除视频文件和分析数据，无法恢复。</p>

            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
              <button type="button" onClick={onClose} className="app-pill">
                取消
              </button>
              <button
                type="button"
                onClick={onConfirmDelete}
                className="min-h-[44px] rounded-full bg-rose-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-rose-600"
              >
                确认删除
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Parent PIN</p>
            <h2 className="mt-3 text-2xl font-semibold text-slate-900">输入家长 PIN</h2>
            <p className="mt-4 text-sm leading-7 text-slate-500">验证通过后会删除这条分析记录，并同步清理相关视频和帧图。</p>

            <div className="mt-6">
              <PinInput
                length={pinLength}
                value={pin}
                onChange={onChangePin}
                autoFocus
                error={Boolean(error)}
                label="删除验证 PIN"
              />
            </div>

            {error ? <p className="mt-4 text-center text-sm text-rose-500">{error}</p> : null}

            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
              <button type="button" onClick={onClose} className="app-pill">
                取消
              </button>
              <button
                type="button"
                onClick={onSubmitPin}
                disabled={isSubmitting || pin.length !== pinLength}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting ? "删除中..." : "确认删除"}
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
