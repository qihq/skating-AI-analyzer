import { useAppMode } from "./AppModeContext";

export default function ModeToggle() {
  const { isParentMode, enterParentMode, switchToChildMode } = useAppMode();

  return (
    <div className="fixed right-4 top-4 z-40 tablet:right-6 tablet:top-6 web:right-8 web:top-8">
      <div className="app-surface flex items-center gap-1 rounded-full p-1 shadow-soft">
        <button
          type="button"
          onClick={switchToChildMode}
          className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
            !isParentMode ? "bg-kid-primary text-white shadow-sm" : "text-slate-500"
          }`}
        >
          坦坦模式
        </button>
        <button
          type="button"
          onClick={() => {
            if (!isParentMode) {
              void enterParentMode();
            }
          }}
          className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
            isParentMode ? "bg-blue-500 text-white shadow-sm" : "text-slate-500"
          }`}
        >
          家长模式
        </button>
      </div>
    </div>
  );
}
