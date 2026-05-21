import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAppearance } from "./AppearanceContext";
import AppHeader from "./AppHeader";
import BottomNav, { PrimaryTab } from "./BottomNav";
import ModeToggle from "./ModeToggle";
import UiThemeToggle from "./UiThemeToggle";

const TAB_MATCHERS: Array<{ tab: PrimaryTab; paths: string[] }> = [
  { tab: "path", paths: ["/path"] },
  { tab: "snowball", paths: ["/snowball"] },
  { tab: "review", paths: ["/review", "/report"] },
  { tab: "archive", paths: ["/archive"] },
  { tab: "history", paths: ["/history"] },
  { tab: "settings", paths: ["/settings"] },
  { tab: "debug", paths: ["/debug"] },
];

const MODERN_NAV_ITEMS = [
  { to: "/path", label: "仪表盘", detail: "训练路径", icon: "仪" },
  { to: "/review", label: "视频上传", detail: "新建分析", icon: "传" },
  { to: "/history", label: "历史分析", detail: "分析记录", icon: "历" },
  { to: "/archive", label: "统计报表", detail: "进度概览", icon: "统" },
];

function activeTabForPath(pathname: string): PrimaryTab | undefined {
  return TAB_MATCHERS.find(({ paths }) => paths.some((path) => pathname.startsWith(path)))?.tab;
}

function modernTitleForPath(pathname: string) {
  if (pathname.startsWith("/report")) {
    return "分析详情";
  }
  if (pathname.startsWith("/review")) {
    return "视频上传";
  }
  if (pathname.startsWith("/history")) {
    return "历史分析";
  }
  if (pathname.startsWith("/archive")) {
    return "统计报表";
  }
  if (pathname.startsWith("/settings")) {
    return "设置";
  }
  if (pathname.startsWith("/debug")) {
    return "诊断调试";
  }
  return "仪表盘";
}

function ModernLayout() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-[#101826] text-slate-100">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[260px] flex-col border-r border-white/10 bg-[#0B1220] px-5 py-5 text-white shadow-[24px_0_70px_rgba(2,6,23,0.35)] web:flex">
        <div className="flex h-14 items-center gap-3 border-b border-white/10">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/15 text-sm font-bold text-cyan-200 ring-1 ring-cyan-300/25">AI</div>
          <div>
            <p className="text-sm font-bold tracking-[0.18em]">SKATING AI</p>
            <p className="text-xs text-slate-400">运动科学分析平台</p>
          </div>
        </div>

        <nav aria-label="现代模式导航" className="mt-8 space-y-2">
          {MODERN_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => {
                const selected = isActive || (item.to === "/review" && location.pathname.startsWith("/report"));
                return `flex min-h-[56px] items-center gap-3 rounded-lg px-3 text-sm transition ${
                  selected
                    ? "bg-cyan-500/14 text-cyan-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_12px_34px_rgba(34,211,238,0.12)] ring-1 ring-cyan-300/18"
                    : "text-slate-400 hover:bg-white/7 hover:text-white"
                }`;
              }}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-white/8 text-xs font-bold text-cyan-100">{item.icon}</span>
              <span className="min-w-0">
                <span className="block font-semibold">{item.label}</span>
                <span className="block text-xs text-slate-400">{item.detail}</span>
              </span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto rounded-lg border border-white/10 bg-white/[0.04] p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">用户档案</p>
          <p className="mt-2 text-sm font-semibold">教练工作台</p>
          <p className="mt-1 text-xs text-slate-400">运动科学分析空间</p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col web:pl-[260px]">
        <header className="sticky top-0 z-20 h-16 border-b border-white/10 bg-[#111A2A]/92 px-4 backdrop-blur tablet:px-6 web:px-8">
          <div className="flex h-full items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="hidden text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300 tablet:block">Skating AI Analyzer</p>
              <h1 className="truncate text-lg font-semibold text-white">{modernTitleForPath(location.pathname)}</h1>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="hidden text-sm text-slate-400 tablet:inline">现代视图</span>
              <UiThemeToggle />
              <ModeToggle variant="modern" />
            </div>
          </div>
        </header>

        <main className="safe-bottom min-w-0 flex-1 overflow-x-hidden px-4 py-6 tablet:px-6 web:px-8">
          <div className="mx-auto w-full max-w-[1480px]">
            <Outlet />
          </div>
        </main>
      </div>

      <BottomNav activeTab={activeTabForPath(location.pathname)} />
    </div>
  );
}

export default function AppLayout() {
  const location = useLocation();
  const { theme, isModern } = useAppearance();
  const activeTab = activeTabForPath(location.pathname);

  if (isModern) {
    return <ModernLayout />;
  }

  return (
    <div className="app-shell" data-ui-theme={theme}>
      <BottomNav activeTab={activeTab} />
      <div className="min-w-0 overflow-x-hidden web:pl-[240px]">
        <AppHeader />

        <main className="page-content safe-bottom mx-auto min-w-0 overflow-x-hidden w-full max-w-[1480px] px-4 pt-[96px] phone:px-5 tablet:px-6 tablet:pt-[108px] web:px-8 web:pb-10 web:pt-[112px]">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
