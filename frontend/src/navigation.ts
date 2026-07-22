export type PrimaryTab = "home" | "review" | "archive" | "path";

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
