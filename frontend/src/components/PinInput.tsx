import { useId, useRef } from "react";

type PinInputProps = {
  length: number;
  value: string;
  onChange: (pin: string) => void;
  onComplete?: (pin: string) => void;
  error?: boolean;
  locked?: boolean;
  lockSecondsLeft?: number;
  autoFocus?: boolean;
  label?: string;
};

export default function PinInput({
  length,
  value,
  onChange,
  onComplete,
  error = false,
  locked = false,
  lockSecondsLeft,
  autoFocus = false,
  label = "PIN",
}: PinInputProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const digits = Array.from({ length }, (_, index) => value[index] ?? "");

  const handleChange = (nextValue: string) => {
    const normalized = nextValue.replace(/\D/g, "").slice(0, length);
    onChange(normalized);
    if (normalized.length === length) {
      onComplete?.(normalized);
    }
  };

  return (
    <div>
      <label className="block cursor-text" htmlFor={inputId} onClick={() => inputRef.current?.focus()}>
        <span className="sr-only">{label}</span>
        <input
          ref={inputRef}
          id={inputId}
          value={value}
          onChange={(event) => handleChange(event.target.value)}
          inputMode="numeric"
          type="password"
          autoFocus={autoFocus}
          disabled={locked}
          className="sr-only"
        />
        <div className="flex flex-wrap justify-center gap-3">
          {digits.map((digit, index) => (
            <div
              key={index}
              className={`flex h-14 w-14 items-center justify-center rounded-2xl border-2 text-2xl font-bold transition-all duration-150 tablet:h-16 tablet:w-16 ${
                error
                  ? "animate-shake border-rose-400 bg-rose-50 text-rose-500"
                  : digit
                    ? "border-kid-primary bg-violet-50 text-kid-primary"
                    : "border-slate-200 bg-slate-50 text-slate-300"
              } ${locked ? "cursor-not-allowed opacity-60" : ""}`}
            >
              {digit ? "•" : ""}
            </div>
          ))}
        </div>
      </label>

      {locked ? (
        <p className="mt-4 text-center text-sm text-amber-500">🔒 已锁定，请 {Math.max(lockSecondsLeft ?? 0, 0)} 秒后重试</p>
      ) : null}
    </div>
  );
}
