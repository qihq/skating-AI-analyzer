import { NavLink } from "react-router-dom";

import { PRIMARY_NAV_ITEMS, PrimaryTab } from "../navigation";

export type { PrimaryTab } from "../navigation";

type BottomNavProps = {
  activeTab?: PrimaryTab;
};

export default function BottomNav({ activeTab }: BottomNavProps) {
  return (
    <>
      <nav
        aria-label="主导航"
        className="bottom-nav fixed inset-x-0 bottom-0 z-30 border-t border-[#E5E7EB] bg-white/96 backdrop-blur web:hidden"
      >
        <div className="mx-auto grid h-full max-w-3xl grid-cols-4">
          {PRIMARY_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.tab}
              to={item.to}
              className={({ isActive }) => `bottom-nav-item text-[#9CA3AF] transition ${isActive || activeTab === item.tab ? "active" : ""}`}
            >
              <span className="icon">{item.icon}</span>
              <span className="label">{item.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>

      <aside className="desktop-sidebar fixed inset-y-0 left-0 z-20 hidden h-dvh w-[240px] overflow-hidden overscroll-contain border-r border-[#E5E7EB] bg-white/92 px-5 py-8 backdrop-blur web:flex web:flex-col">
        <div className="desktop-sidebar-brand">
          <p className="desktop-sidebar-kicker text-xs font-semibold uppercase tracking-[0.3em] text-kid-primary">IceBuddy</p>
          <h1 className="desktop-sidebar-title mt-3 text-2xl font-semibold text-slate-900">花样滑冰训练分析系统</h1>
          <p className="desktop-sidebar-description mt-3 text-sm leading-6 text-slate-500">为家庭训练复盘、陪练建议和成长记录准备的滑冰助手。</p>
        </div>

        <nav className="desktop-sidebar-nav mt-10 flex flex-col gap-2" aria-label="桌面主导航">
          {PRIMARY_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.tab}
              to={item.to}
              className={({ isActive }) => `desktop-sidebar-link flex min-h-[56px] items-center gap-3 rounded-[20px] px-4 text-sm font-medium transition ${
                isActive || activeTab === item.tab ? "bg-blue-50 text-[#3B82F6]" : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
              }`}
            >
              <span className="text-xl">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="desktop-sidebar-note mt-auto rounded-[24px] border border-blue-100 bg-blue-50/80 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">家庭模式</p>
          <p className="mt-2 text-sm leading-6 text-slate-600">首页、复盘、进步和档案构成主线；设置里保留标注与调试工具。</p>
        </div>
      </aside>
    </>
  );
}
