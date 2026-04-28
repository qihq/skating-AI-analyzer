import ModeToggle from "./ModeToggle";

export default function AppHeader() {
  return (
    <header className="app-header fixed left-0 right-0 top-0 z-40 web:left-[240px]">
      <div className="mx-auto max-w-[1480px] px-4 phone:px-5 tablet:px-6 web:px-8">
        <div className="app-surface flex items-center justify-between gap-3 rounded-[28px] px-4 py-3 shadow-[0_18px_40px_rgba(15,23,42,0.08)] tablet:px-5">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-blue-500">IceBuddy</p>
            <h1 className="truncate text-base font-semibold text-slate-900 tablet:text-lg">花样滑冰训练分析系统</h1>
          </div>

          <ModeToggle />
        </div>
      </div>
    </header>
  );
}
