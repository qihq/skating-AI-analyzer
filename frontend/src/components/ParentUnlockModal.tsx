import PinInput from "./PinInput";

type ParentUnlockModalProps = {
  pin: string;
  pinLength: number;
  error: string | null;
  failedAttempts: number;
  isSubmitting: boolean;
  locked: boolean;
  lockSecondsLeft: number;
  onChangePin: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
};

export default function ParentUnlockModal({
  pin,
  pinLength,
  error,
  failedAttempts,
  isSubmitting,
  locked,
  lockSecondsLeft,
  onChangePin,
  onClose,
  onSubmit,
}: ParentUnlockModalProps) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/28 px-4 backdrop-blur-sm">
      <section className="app-card w-full max-w-md p-6 tablet:p-7">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Parent Unlock</p>
        <h2 className="mt-3 text-2xl font-semibold text-slate-900">输入家长 PIN</h2>
        <p className="mt-3 text-sm leading-6 text-slate-500">验证后可上传训练视频、管理技能解锁与查看完整诊断细节。</p>

        <div className="mt-6">
          <PinInput
            length={pinLength}
            value={pin}
            onChange={onChangePin}
            autoFocus
            error={Boolean(error)}
            locked={locked}
            lockSecondsLeft={lockSecondsLeft}
            label="家长 PIN"
          />
        </div>

        {error ? <p className="mt-4 text-center text-sm text-rose-500">{error}</p> : null}
        {failedAttempts > 0 && !error && !locked ? <p className="mt-4 text-center text-sm text-amber-500">已输错 {failedAttempts} 次。</p> : null}

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="app-pill">
            取消
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={isSubmitting || locked || pin.length !== pinLength}
            className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? "验证中..." : "进入家长模式"}
          </button>
        </div>
      </section>
    </div>
  );
}
