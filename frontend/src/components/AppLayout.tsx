import { Outlet, useLocation } from "react-router-dom";

import BottomNav, { PrimaryTab } from "./BottomNav";
import ModeToggle from "./ModeToggle";

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
      <ModeToggle />

      <div className="min-h-screen web:pl-[240px]">
        <div className="safe-bottom mx-auto min-h-screen w-full max-w-[1480px] px-4 pt-20 phone:px-5 tablet:px-6 tablet:pt-24 web:px-8 web:pb-10">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
