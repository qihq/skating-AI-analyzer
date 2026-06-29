import { NavLink } from "react-router-dom";

import { useAppMode } from "./AppModeContext";

export type PrimaryTab = "path" | "snowball" | "review" | "chat" | "archive" | "history" | "settings" | "debug";

type BottomNavProps = {
  activeTab?: PrimaryTab;
};

const PRIMARY_NAV_ITEMS: Array<{ tab: Exclude<PrimaryTab, "settings" | "debug" | "chat" | "history">; to: string; label: string; icon: string }> = [
  { tab: "path", to: "/path", label: "路径", icon: "⛸️" },
  { tab: "snowball", to: "/snowball", label: "冰宝", icon: "❄️" },
  { tab: "review", to: "/review", label: "复盘", icon: "🎬" },
  { tab: "archive", to: "/archive", label: "进展", icon: "📈" },
];

const PARENT_NAV_ITEMS: Array<{ tab: PrimaryTab; to: string; label: string; icon: string }> = [
  { tab: "review", to: "/review", label: "分析", icon: "📹" },
  { tab: "chat", to: "/analysis-chat", label: "追问", icon: "💬" },
  { tab: "path", to: "/path", label: "计划", icon: "📋" },
  { tab: "history", to: "/history", label: "历史", icon: "📜" },
  { tab: "archive", to: "/archive", label: "进展", icon: "📊" },
  { tab: "debug", to: "/debug", label: "调试", icon: "🧪" },
  { tab: "settings", to: "/settings", label: "设置", icon: "⚙️" },
];

export default function BottomNav({ activeTab }: BottomNavProps) {
  const { isParentMode } = useAppMode();
  const mobileNavItems = isParentMode ? PARENT_NAV_ITEMS : PRIMARY_NAV_ITEMS;
  const desktopNavItems = isParentMode ? PARENT_NAV_ITEMS : PRIMARY_NAV_ITEMS;

  return (
    <>
      <nav
        aria-label="主导航"
        className="bottom-nav fixed inset-x-0 bottom-0 z-30 border-t border-[#E5E7EB] bg-white/96 backdrop-blur web:hidden"
      >
        <div
          className="mx-auto grid h-full max-w-3xl"
          style={{ gridTemplateColumns: `repeat(${mobileNavItems.length}, minmax(0, 1fr))` }}
        >
          {mobileNavItems.map((item) => (
            <NavLink
              key={item.tab}
              to={item.to}
              className={({ isActive }) => {
                const selected = isActive || activeTab === item.tab;
                return `bottom-nav-item text-[#9CA3AF] transition ${selected ? "active" : ""}`;
              }}
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
          {desktopNavItems.map((item) => (
            <NavLink
              key={item.tab}
              to={item.to}
              className={({ isActive }) => {
                const selected = isActive || activeTab === item.tab;
                return `desktop-sidebar-link flex min-h-[56px] items-center gap-3 rounded-[20px] px-4 text-sm font-medium transition ${
                  selected ? "bg-blue-50 text-[#3B82F6]" : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
                }`;
              }}
            >
              <span className="text-xl">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="desktop-sidebar-note mt-auto rounded-[24px] border border-blue-100 bg-blue-50/80 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">家庭模式</p>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            手机与 iPad 使用底部导航，网页端使用左侧固定导航。家长模式会显示分析、追问、计划、历史、进展和设置入口。
          </p>
        </div>
      </aside>
    </>
  );
}
