import { NavLink } from "react-router-dom";

import { useAppMode } from "./AppModeContext";

export type PrimaryTab = "path" | "snowball" | "review" | "archive" | "settings";

type BottomNavProps = {
  activeTab?: PrimaryTab;
};

const PRIMARY_NAV_ITEMS: Array<{ tab: Exclude<PrimaryTab, "settings">; to: string; label: string; icon: string }> = [
  { tab: "path", to: "/path", label: "路径", icon: "⛸️" },
  { tab: "snowball", to: "/snowball", label: "冰宝", icon: "❄️" },
  { tab: "review", to: "/review", label: "复盘", icon: "🎬" },
  { tab: "archive", to: "/archive", label: "进展", icon: "📈" },
];

export default function BottomNav({ activeTab }: BottomNavProps) {
  const { isParentMode } = useAppMode();
  const mobileNavItems = isParentMode
    ? [...PRIMARY_NAV_ITEMS.slice(0, 3), { tab: "settings" as const, to: "/settings", label: "设置", icon: "⚙️" }]
    : PRIMARY_NAV_ITEMS;
  const desktopNavItems = isParentMode
    ? [...PRIMARY_NAV_ITEMS, { tab: "settings" as const, to: "/settings", label: "家长设置", icon: "⚙️" }]
    : PRIMARY_NAV_ITEMS;

  return (
    <>
      <nav
        aria-label="主导航"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-[#E5E7EB] bg-white/96 backdrop-blur web:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className={`mx-auto grid h-[49px] max-w-3xl ${mobileNavItems.length === 4 ? "grid-cols-4" : "grid-cols-5"}`}>
          {mobileNavItems.map((item) => (
            <NavLink
              key={item.tab}
              to={item.to}
              className={({ isActive }) => {
                const selected = isActive || activeTab === item.tab;
                return `flex min-h-[49px] flex-col items-center justify-center gap-0.5 text-xs font-medium transition ${
                  selected ? "text-[#3B82F6]" : "text-[#9CA3AF]"
                }`;
              }}
            >
              <span className="text-base leading-none">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>

      <aside className="fixed inset-y-0 left-0 z-20 hidden w-[240px] border-r border-[#E5E7EB] bg-white/92 px-5 py-8 backdrop-blur web:flex web:flex-col">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-kid-primary">IceBuddy</p>
          <h1 className="mt-3 text-2xl font-semibold text-slate-900">花样滑冰训练分析系统</h1>
          <p className="mt-3 text-sm leading-6 text-slate-500">为家庭训练复盘、陪练建议和成长记录准备的滑冰助手。</p>
        </div>

        <div className="mt-10 space-y-2">
          {desktopNavItems.map((item) => (
            <NavLink
              key={item.tab}
              to={item.to}
              className={({ isActive }) => {
                const selected = isActive || activeTab === item.tab;
                return `flex min-h-[56px] items-center gap-3 rounded-[20px] px-4 text-sm font-medium transition ${
                  selected ? "bg-blue-50 text-[#3B82F6]" : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
                }`;
              }}
            >
              <span className="text-xl">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>

        <div className="mt-auto rounded-[24px] border border-blue-100 bg-blue-50/80 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">家庭模式</p>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            手机与 iPad 使用底部导航，网页端使用左侧固定导航。进入家长模式后，设置入口会自动出现在导航中。
          </p>
        </div>
      </aside>
    </>
  );
}
