import { Link, Outlet, useLocation } from "react-router-dom";

import ModeToggle from "../components/ModeToggle";
import UiThemeToggle from "../components/UiThemeToggle";
import { modernSpaceForPath } from "../navigation";
import IslandIcon from "./IslandIcon";
import { IslandThemeProvider, useIslandTheme } from "./IslandThemeContext";
import { IslandDock, IslandRail } from "./ModernNavigation";
import "./modern-island.css";
import NetworkStatus from "./NetworkStatus";

const PAGE_TITLES: Array<[string, string]> = [
  ["/analysis", "分析详情"], ["/report", "分析详情"], ["/review", "冰场小屋"],
  ["/growth", "成长群岛"], ["/archive", "成长群岛"], ["/history", "成长群岛"],
  ["/compare", "成长群岛"], ["/chapters", "成长群岛"], ["/annual", "成长群岛"],
  ["/path", "成长群岛"], ["/plan", "成长群岛"], ["/snowball", "成长群岛"],
  ["/me", "居民服务处"], ["/settings", "居民服务处"], ["/debug", "高级工具"],
  ["/golden", "高级工具"], ["/home", "今日岛屿"],
];

function ModernShellContent() {
  const location = useLocation();
  const { period } = useIslandTheme();
  const activeSpace = modernSpaceForPath(location.pathname);
  const title = PAGE_TITLES.find(([path]) => location.pathname.startsWith(path))?.[1] ?? "冰上成长岛";

  return (
    <div className="modern-island-shell" data-island-period={period}>
      <IslandRail activeSpace={activeSpace} />
      <div className="modern-island-shell__body">
        <header className="island-topbar">
          <div className="island-topbar__identity">
            <span className="island-topbar__leaf" aria-hidden="true">❄</span>
            <div><strong>{title}</strong><small>IceBuddy · 冰上成长岛</small></div>
          </div>
          <div className="island-topbar__actions">
            <Link to="/me?view=appearance" aria-label="外观与时段主题" className="island-icon-button"><IslandIcon name="sun" /></Link>
            <span className="island-ui-switch"><UiThemeToggle /></span>
            <ModeToggle variant="modern" />
          </div>
        </header>
        <NetworkStatus />
        <main className="modern-island-content"><Outlet /></main>
      </div>
      <IslandDock activeSpace={activeSpace} />
    </div>
  );
}

export default function ModernAppShell() {
  return <IslandThemeProvider><ModernShellContent /></IslandThemeProvider>;
}
