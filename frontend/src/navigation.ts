export type PrimaryTab = "home" | "review" | "archive" | "path";

export type ModernSpace = "home" | "review" | "growth" | "me";

export const MODERN_NAV_ITEMS = [
  { space: "home", to: "/home", label: "首页", detail: "今日岛屿", icon: "home", primary: false },
  { space: "review", to: "/review", label: "开始复盘", detail: "冰场小屋", icon: "review", primary: true },
  { space: "growth", to: "/growth", label: "成长", detail: "成长群岛", icon: "growth", primary: false },
  { space: "me", to: "/me", label: "我的", detail: "居民服务处", icon: "me", primary: false },
] as const;

export const PRIMARY_NAV_ITEMS = [
  { tab: "home", to: "/home", label: "首页", detail: "成长总览", icon: "🏠" },
  { tab: "review", to: "/review", label: "复盘", detail: "上传与分析", icon: "🎬" },
  { tab: "archive", to: "/archive", label: "进步", detail: "趋势与历史", icon: "📈" },
  { tab: "path", to: "/path", label: "档案", detail: "技能与目标", icon: "⛸️" },
] as const;

const TAB_PATHS: Record<PrimaryTab, string[]> = {
  home: ["/home"],
  review: ["/review", "/report", "/analysis-chat"],
  archive: ["/archive", "/history", "/compare"],
  path: ["/path", "/plan", "/snowball"],
};

export function primaryTabForPath(pathname: string): PrimaryTab | undefined {
  return (Object.entries(TAB_PATHS) as Array<[PrimaryTab, string[]]>).find(([, paths]) =>
    paths.some((path) => pathname.startsWith(path)),
  )?.[0];
}

export function modernSpaceForPath(pathname: string): ModernSpace | undefined {
  if (pathname.startsWith("/home")) return "home";
  if (pathname.startsWith("/review") || pathname.startsWith("/analysis") || pathname.startsWith("/report")) return "review";
  if (
    pathname.startsWith("/growth") ||
    pathname.startsWith("/archive") ||
    pathname.startsWith("/history") ||
    pathname.startsWith("/compare") ||
    pathname.startsWith("/chapters") ||
    pathname.startsWith("/annual") ||
    pathname.startsWith("/path") ||
    pathname.startsWith("/plan") ||
    pathname.startsWith("/snowball")
  ) return "growth";
  if (pathname.startsWith("/me") || pathname.startsWith("/settings") || pathname.startsWith("/debug") || pathname.startsWith("/golden")) return "me";
  return undefined;
}
