import { Outlet, useLocation } from "react-router-dom";

import AppHeader from "./AppHeader";
import BottomNav, { PrimaryTab } from "./BottomNav";

const TAB_MATCHERS: Array<{ tab: PrimaryTab; paths: string[] }> = [
  { tab: "path", paths: ["/path"] },
  { tab: "snowball", paths: ["/snowball"] },
  { tab: "review", paths: ["/review", "/report"] },
  { tab: "archive", paths: ["/archive"] },
  { tab: "settings", paths: ["/settings"] },
];

function activeTabForPath(pathname: string): PrimaryTab | undefined {
  return TAB_MATCHERS.find(({ paths }) => paths.some((path) => pathname.startsWith(path)))?.tab;
}

export default function AppLayout() {
  const location = useLocation();
  const activeTab = activeTabForPath(location.pathname);

  return (
    <div className="app-shell">
      <BottomNav activeTab={activeTab} />
      <div className="web:pl-[240px]">
        <AppHeader />

        <main className="page-content safe-bottom mx-auto w-full max-w-[1480px] px-4 pt-[96px] phone:px-5 tablet:px-6 tablet:pt-[108px] web:px-8 web:pb-10 web:pt-[112px]">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
