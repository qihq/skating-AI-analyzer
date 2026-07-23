import { lazy, ReactNode, Suspense } from "react";
import { useSearchParams } from "react-router-dom";

import { IslandPageHeader } from "./IslandSurface";
import SectionNav from "./SectionNav";

const AnnualCollectionPage = lazy(() => import("../pages/AnnualCollectionPage"));
const ArchivePage = lazy(() => import("../pages/ArchivePage"));
const ComparePage = lazy(() => import("../pages/ComparePage"));
const HistoryPage = lazy(() => import("../pages/HistoryPage"));
const MonthlyChaptersPage = lazy(() => import("../pages/MonthlyChaptersPage"));
const PlanPage = lazy(() => import("../pages/PlanPage"));
const SkillTreePage = lazy(() => import("../pages/SkillTreePage"));
const SnowballPage = lazy(() => import("../pages/SnowballPage"));

export type GrowthView = "overview" | "timeline" | "compare" | "chapters" | "annual" | "skills" | "plans" | "snowball";

const ITEMS = [
  { id: "overview", label: "总览", to: "/growth" },
  { id: "timeline", label: "时间线", to: "/growth?view=timeline" },
  { id: "compare", label: "对比", to: "/growth?view=compare" },
  { id: "chapters", label: "月度故事", to: "/growth?view=chapters" },
  { id: "annual", label: "年度合辑", to: "/growth?view=annual" },
  { id: "skills", label: "技能与目标", to: "/growth?view=skills" },
  { id: "plans", label: "训练计划", to: "/growth?view=plans" },
  { id: "snowball", label: "雪球记忆", to: "/growth?view=snowball" },
] as const;

export function ModernGrowthFrame({ view, children }: { view: GrowthView; children: ReactNode }) {
  return (
    <div className="modern-space modern-growth-space">
      <IslandPageHeader title="成长群岛" description="把趋势、历史、故事、技能与训练计划收在同一片群岛。" />
      <SectionNav label="成长群岛分区" items={[...ITEMS]} activeId={view} />
      <div className="modern-legacy-surface"><Suspense fallback={<div className="island-route-loading">正在前往这片岛屿…</div>}>{children}</Suspense></div>
    </div>
  );
}

export default function ModernGrowthSpace() {
  const [params] = useSearchParams();
  const requested = params.get("view") as GrowthView | null;
  const view = ITEMS.some((item) => item.id === requested) ? requested! : "overview";
  const content: Record<GrowthView, ReactNode> = {
    overview: <ArchivePage />,
    timeline: <HistoryPage />,
    compare: <ComparePage />,
    chapters: <MonthlyChaptersPage />,
    annual: <AnnualCollectionPage />,
    skills: <SkillTreePage />,
    plans: <PlanPage />,
    snowball: <SnowballPage />,
  };
  return <ModernGrowthFrame view={view}>{content[view]}</ModernGrowthFrame>;
}
