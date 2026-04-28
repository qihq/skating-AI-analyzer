import axios from "axios";
import { useEffect, useState } from "react";

import { verifyPin } from "../api/client";
import PinInput from "./PinInput";

const LOCK_SECONDS = 30;

type ParentPinVerifyModalProps = {
  pinLength: number;
  title?: string;
  description?: string;
  confirmLabel?: string;
  onClose: () => void;
  onVerified: () => void | Promise<void>;
};

export default function ParentPinVerifyModal({
  pinLength,
  title = "输入家长 PIN",
  description = "验证通过后才会继续执行这个操作。",
  confirmLabel = "继续",
  onClose,
  onVerified,
}: ParentPinVerifyModalProps) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [failedAttempts, setFailedAttempts] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState(() => Date.now());

  const lockSecondsLeft = lockedUntil ? Math.max(0, Math.ceil((lockedUntil - nowTick) / 1000)) : 0;
  const isLocked = lockSecondsLeft > 0;

  useEffect(() => {
    if (!lockedUntil) {
      return;
    }
    const timer = window.setInterval(() => setNowTick(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [lockedUntil]);

  useEffect(() => {
    if (lockedUntil && Date.now() >= lockedUntil) {
      setLockedUntil(null);
      setFailedAttempts(0);
      setError(null);
      setNowTick(Date.now());
    }
  }, [lockedUntil, nowTick]);

  const handleSubmit = async () => {
    if (isLocked) {
      return;
    }
    if (!new RegExp(`^\\d{${pinLength}}$`).test(pin)) {
      setError(`请输入 ${pinLength} 位数字 PIN。`);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const data = await verifyPin(pin);
      if (!data.valid) {
        const nextAttempts = failedAttempts + 1;
        setFailedAttempts(nextAttempts);
        setPin("");
        if (nextAttempts >= 3) {
          setLockedUntil(Date.now() + LOCK_SECONDS * 1000);
          setError("PIN 已连续输错 3 次。");
        } else {
          setError("PIN 不正确，请再试一次。");
        }
        return;
      }

      setPin("");
      setFailedAttempts(0);
      setLockedUntil(null);
      await onVerified();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "PIN 验证失败，请稍后重试。"));
      } else {
        setError("PIN 验证失败，请稍后重试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/28 px-4 backdrop-blur-sm">
      <section className="app-card w-full max-w-md p-6 tablet:p-7">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Parent PIN</p>
        <h2 className="mt-3 text-2xl font-semibold text-slate-900">{title}</h2>
        <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p>

        <div className="mt-6">
          <PinInput
            length={pinLength}
            value={pin}
            onChange={setPin}
            autoFocus
            error={Boolean(error)}
            locked={isLocked}
            lockSecondsLeft={lockSecondsLeft}
            label={title}
          />
        </div>

        {error ? <p className="mt-4 text-center text-sm text-rose-500">{error}</p> : null}
        {failedAttempts > 0 && !error && !isLocked ? (
          <p className="mt-4 text-center text-sm text-amber-500">已输错 {failedAttempts} 次。</p>
        ) : null}

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="app-pill">
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={isSubmitting || isLocked || pin.length !== pinLength}
            className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? "验证中..." : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
