import { useAppearance } from "./AppearanceContext";

type UiThemeToggleProps = {
  variant?: "compact" | "hero";
};

export default function UiThemeToggle({ variant = "compact" }: UiThemeToggleProps) {
  const { isIceGlass, toggleTheme } = useAppearance();

  if (variant === "hero") {
    return (
      <button
        type="button"
        onClick={toggleTheme}
        aria-pressed={isIceGlass}
        className={`group flex w-full min-h-[72px] items-center justify-between gap-4 rounded-[28px] border px-5 py-4 text-left transition ${
          isIceGlass
            ? "border-cyan-200/40 bg-cyan-100/14 text-white shadow-[0_24px_70px_rgba(45,212,191,0.16)]"
            : "border-blue-100 bg-blue-50/90 text-slate-900 hover:border-blue-200"
        }`}
      >
        <span className="min-w-0">
          <span className={`block text-xs font-semibold uppercase tracking-[0.24em] ${isIceGlass ? "text-cyan-100" : "text-blue-500"}`}>
            New UI
          </span>
          <span className="mt-1 block text-lg font-semibold">{isIceGlass ? "冰场暗玻璃已开启" : "开启冰场暗玻璃界面"}</span>
          <span className={`mt-1 block text-sm leading-6 ${isIceGlass ? "text-cyan-50/78" : "text-slate-500"}`}>
            {isIceGlass ? "点击可回到当前经典界面。" : "参考沉浸式 B 端界面，保留全部业务流程。"}
          </span>
        </span>
        <span
          className={`relative h-8 w-14 shrink-0 rounded-full p-1 transition ${
            isIceGlass ? "bg-cyan-300/90" : "bg-white shadow-inner"
          }`}
          aria-hidden="true"
        >
          <span
            className={`block h-6 w-6 rounded-full bg-slate-950 shadow-sm transition-transform ${isIceGlass ? "translate-x-6" : "translate-x-0 bg-blue-500"}`}
          />
        </span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-pressed={isIceGlass}
      className={`min-h-[44px] shrink-0 rounded-full px-4 text-sm font-semibold transition ${
        isIceGlass
          ? "border border-cyan-200/40 bg-cyan-100/16 text-cyan-50 hover:bg-cyan-100/24"
          : "border border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-600"
      }`}
    >
      {isIceGlass ? "经典 UI" : "新 UI"}
    </button>
  );
}
