import TrialBanner from "./TrialBanner";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { PRIMARY_NAV_ITEMS, primaryTabForPath } from "../navigation";
import { useAppearance } from "./AppearanceContext";
import AppHeader from "./AppHeader";
import BottomNav from "./BottomNav";
import ModeToggle from "./ModeToggle";
import UiThemeToggle from "./UiThemeToggle";
import ModernAppShell from "../modern/ModernAppShell";

function modernTitleForPath(pathname: string) {
  if (pathname.startsWith("/report")) return "分析详情";
  if (pathname.startsWith("/review")) return "视频上传";
  if (pathname.startsWith("/history")) return "历史分析";
  if (pathname.startsWith("/archive")) return "进步";
  if (pathname.startsWith("/settings")) return "设置";
  if (pathname.startsWith("/debug")) return "诊断调试";
  if (pathname.startsWith("/home")) return "成长首页";
  return "成长档案";
}

function ModernLayout() {
  const location = useLocation();
  const activeTab = primaryTabForPath(location.pathname);

  return (
    <div className="min-h-screen bg-[#101826] text-slate-100">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[260px] flex-col border-r border-white/10 bg-[#0B1220] px-5 py-5 text-white shadow-[24px_0_70px_rgba(2,6,23,0.35)] web:flex">
        <div className="flex h-14 items-center gap-3 border-b border-white/10">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/15 text-sm font-bold text-cyan-200 ring-1 ring-cyan-300/25">AI</div>
          <div><p className="text-sm font-bold tracking-[0.18em]">SKATING AI</p><p className="text-xs text-slate-400">运动科学分析平台</p></div>
        </div>

        <nav aria-label="现代模式导航" className="mt-8 space-y-2">
          {PRIMARY_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.tab}
              to={item.to}
              className={({ isActive }) => `flex min-h-[56px] items-center gap-3 rounded-lg px-3 text-sm transition ${
                isActive || activeTab === item.tab ? "bg-cyan-500/14 text-cyan-50 ring-1 ring-cyan-300/18" : "text-slate-400 hover:bg-white/7 hover:text-white"
              }`}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/8 text-base">{item.icon}</span>
              <span className="min-w-0"><span className="block font-semibold">{item.label}</span><span className="block text-xs text-slate-400">{item.detail}</span></span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto rounded-lg border border-white/10 bg-white/[0.04] p-4"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">成长主线</p><p className="mt-2 text-sm leading-6 text-slate-300">设置中保留高级标注、调试与 API 工具。</p></div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col web:pl-[260px]">
        <header className="sticky top-0 z-20 h-16 border-b border-white/10 bg-[#111A2A]/92 px-4 backdrop-blur tablet:px-6 web:px-8">
          <div className="flex h-full items-center justify-between gap-3">
            <div className="min-w-0"><p className="hidden text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300 tablet:block">Skating AI Analyzer</p><h1 className="truncate text-lg font-semibold text-white">{modernTitleForPath(location.pathname)}</h1></div>
            <div className="flex shrink-0 items-center gap-2"><Link aria-label="打开设置" to="/settings" className="flex h-11 w-11 items-center justify-center rounded-full text-lg text-slate-200 hover:bg-white/10">⚙️</Link><UiThemeToggle /><ModeToggle variant="modern" /></div>
          </div>
        </header>

        <main className="safe-bottom min-w-0 flex-1 overflow-x-hidden px-4 py-6 tablet:px-6 web:px-8"><div className="mx-auto w-full max-w-[1480px]"><Outlet /></div></main>
      </div>
      <BottomNav activeTab={activeTab} />
    </div>
  );
}

export default function AppLayout() {
  const location = useLocation();
  const { theme, isModern } = useAppearance();
  const activeTab = primaryTabForPath(location.pathname);

  if (isModern) return <ModernAppShell />;

  return (
    <div className="app-shell" data-ui-theme={theme}>
      <BottomNav activeTab={activeTab} />
      <div className="min-w-0 overflow-x-hidden web:pl-[240px]">
        <AppHeader />
        <main className="page-content safe-bottom mx-auto min-w-0 w-full max-w-[1480px] overflow-x-hidden px-4 pt-[96px] phone:px-5 tablet:px-6 tablet:pt-[108px] web:px-8 web:pb-10 web:pt-[112px]"><TrialBanner /><Outlet /></main>
      </div>
    </div>
  );
}
