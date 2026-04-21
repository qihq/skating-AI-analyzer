import axios from "axios";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { setupPin } from "../api/client";
import { useAppMode } from "../components/AppModeContext";
import PinInput from "../components/PinInput";

type PinLengthOption = 4 | 5 | 6;

export default function ParentSetupPage() {
  const navigate = useNavigate();
  const { refreshPinState, activateParentMode } = useAppMode();
  const [pinLength, setPinLength] = useState<PinLengthOption>(4);
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleChangeLength = (nextLength: PinLengthOption) => {
    setPinLength(nextLength);
    setPin((current) => current.slice(0, nextLength));
    setConfirmPin((current) => current.slice(0, nextLength));
    setError(null);
  };

  const handleSubmit = async () => {
    if (!new RegExp(`^\\d{${pinLength}}$`).test(pin)) {
      setError(`PIN 必须是 ${pinLength} 位数字。`);
      return;
    }
    if (pin !== confirmPin) {
      setError("两次输入的 PIN 不一致。");
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await setupPin(pin);
      await refreshPinState();
      activateParentMode();
      navigate("/path");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "PIN 设置失败，请稍后重试。"));
      } else {
        setError("PIN 设置失败，请稍后重试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="app-shell min-h-screen">
      <section className="safe-bottom mx-auto flex min-h-screen max-w-5xl items-center px-4 py-10 phone:px-5 tablet:px-6">
        <div className="grid w-full gap-6 web:grid-cols-[1fr_420px]">
          <div className="app-card overflow-hidden p-8 tablet:p-10">
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Parent Setup</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">设置家长 PIN</h1>
            <p className="mt-4 max-w-2xl text-base leading-8 text-slate-500">
              首次进入家长模式前，请先设置 4 到 6 位数字 PIN。之后上传视频、手动点亮技能和查看完整报告都会通过这个 PIN 保护。
            </p>

            <div className="mt-8 max-w-md space-y-6">
              <div>
                <p className="text-sm font-medium text-slate-700">PIN 位数</p>
                <div className="mt-3 inline-flex rounded-full bg-slate-100 p-1">
                  {[4, 5, 6].map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => handleChangeLength(option as PinLengthOption)}
                      className={`min-h-[44px] rounded-full px-4 text-sm font-semibold transition ${
                        pinLength === option ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
                      }`}
                    >
                      {option}位
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-3 text-sm font-medium text-slate-700">输入 PIN</p>
                <PinInput length={pinLength} value={pin} onChange={setPin} autoFocus label="输入 PIN" />
              </div>

              <div>
                <p className="mb-3 text-sm font-medium text-slate-700">再次输入 PIN</p>
                <PinInput length={pinLength} value={confirmPin} onChange={setConfirmPin} error={Boolean(error && confirmPin.length === pinLength && pin !== confirmPin)} label="确认 PIN" />
              </div>
            </div>

            {error ? <div className="mt-5 rounded-[24px] bg-rose-50 px-4 py-3 text-sm text-rose-500">{error}</div> : null}

            <div className="mt-6 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleSubmit}
                disabled={isSubmitting || pin.length !== pinLength || confirmPin.length !== pinLength}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting ? "设置中..." : "保存 PIN"}
              </button>
              <button type="button" onClick={() => navigate("/path")} className="app-pill">
                稍后设置
              </button>
            </div>
          </div>

          <aside className="app-card p-6 tablet:p-7">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">为什么要设置</p>
            <div className="mt-4 space-y-4 text-sm leading-7 text-slate-500">
              <p>• 防止孩子误触上传或误改技能节点。</p>
              <p>• 保护完整技术诊断与系统设置入口。</p>
              <p>• 家庭局域网部署下依然保留基础权限边界。</p>
            </div>
          </aside>
        </div>
      </section>
    </main>
  );
}
