import { NavLink } from "react-router-dom";

import { useAppMode } from "./AppModeContext";

export default function TopNav() {
  const { isParentMode, enterParentMode, switchToChildMode } = useAppMode();
  const navItems = [
    { to: "/upload", label: "上传" },
    { to: "/skills", label: "技能树" },
    { to: "/history", label: "历史" },
    { to: "/archive", label: "进展" },
    { to: "/progress", label: "趋势" },
    ...(isParentMode ? [{ to: "/settings", label: "设置" }] : []),
  ];

  return (
    <header className="sticky top-0 z-20 mb-8 pt-2">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 rounded-[2rem] border border-white/10 bg-slate-950/65 px-4 py-3 backdrop-blur xl:px-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-cyan-200/80">IceBuddy</p>
          <h1 className="text-base font-semibold text-white sm:text-lg">花样滑冰训练分析系统</h1>
        </div>

        <nav className="flex flex-wrap items-center gap-2 lg:justify-end">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-full px-4 py-2 text-sm transition ${
                  isActive ? "bg-cyan-300 text-slate-950" : "bg-white/5 text-slate-200 hover:bg-white/10"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}

          <button
            type="button"
            onClick={isParentMode ? switchToChildMode : enterParentMode}
            className={`rounded-full px-4 py-2 text-sm font-medium transition ${
              isParentMode
                ? "bg-amber-300 text-slate-950 hover:bg-amber-200"
                : "border border-white/10 bg-white/5 text-slate-200 hover:bg-white/10"
            }`}
          >
            {isParentMode ? "切回坦坦模式" : "进入家长模式"}
          </button>
        </nav>
      </div>
    </header>
  );
}
