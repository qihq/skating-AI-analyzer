import { useAppearance } from "./AppearanceContext";

type UiThemeToggleProps = {
  variant?: "compact" | "hero";
};

export default function UiThemeToggle({ variant = "compact" }: UiThemeToggleProps) {
  const { isModern, toggleTheme } = useAppearance();

  if (variant === "hero") {
    return (
      <button
        type="button"
        onClick={toggleTheme}
        aria-pressed={isModern}
        className={`group flex w-full min-h-[72px] items-center justify-between gap-4 rounded-[28px] border px-5 py-4 text-left transition ${
          isModern
            ? "border-blue-200/30 bg-blue-500/12 text-white shadow-[0_24px_70px_rgba(37,99,235,0.16)]"
            : "border-blue-100 bg-blue-50/90 text-slate-900 hover:border-blue-200"
        }`}
      >
        <span className="min-w-0">
          <span className={`block text-xs font-semibold uppercase tracking-[0.24em] ${isModern ? "text-blue-100" : "text-blue-500"}`}>
            界面模式
          </span>
          <span className="mt-1 block text-lg font-semibold">{isModern ? "现代界面已开启" : "切换到现代界面"}</span>
          <span className={`mt-1 block text-sm leading-6 ${isModern ? "text-blue-50/80" : "text-slate-500"}`}>
            {isModern ? "点击可返回经典界面。" : "使用专业视频分析工作站。"}
          </span>
        </span>
        <span
          className={`relative h-8 w-14 shrink-0 rounded-full p-1 transition ${
            isModern ? "bg-blue-500" : "bg-white shadow-inner"
          }`}
          aria-hidden="true"
        >
          <span
            className={`block h-6 w-6 rounded-full bg-white shadow-sm transition-transform ${
              isModern ? "translate-x-6" : "translate-x-0 bg-blue-500"
            }`}
          />
        </span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-pressed={isModern}
      className={`min-h-[44px] shrink-0 rounded-full px-4 text-sm font-semibold transition ${
        isModern
          ? "border border-cyan-400/25 bg-white/8 text-cyan-50 shadow-sm hover:bg-white/12"
          : "border border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-600"
      }`}
    >
      {isModern ? "经典界面" : "现代界面"}
    </button>
  );
}
