import { Link, useParams, useSearchParams } from "react-router-dom";

import ReportPage from "../pages/ReportPage";
import ReportWorkspacePage, { WorkspaceTab } from "../pages/ReportWorkspacePage";
import { IslandPageHeader } from "./IslandSurface";
import SectionNav from "./SectionNav";
import { AnalysisView, resolveAnalysisView } from "./analysisNavigation";

const ITEMS = [
  { id: "summary", label: "总结", to: "summary" },
  { id: "moments", label: "关键时刻", to: "moments" },
  { id: "body", label: "身体与姿态", to: "body" },
  { id: "ask", label: "追问", to: "ask" },
  { id: "more", label: "更多", to: "more" },
] as const;

export default function ModernAnalysisDetail({ initialView }: { initialView?: AnalysisView }) {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const view = resolveAnalysisView({ initialView, view: params.get("view"), legacyTab: params.get("tab") });
  const sectionItems = ITEMS.map((item) => ({
    ...item,
    to: `/analysis/${id}?view=${item.to}${item.id === "more" ? "&tool=diagnostics" : ""}`,
  }));
  const workspaceTab: Record<Exclude<AnalysisView, "summary">, WorkspaceTab> = {
    moments: "evidence", body: "pose", ask: "followup", more: "diagnostics",
  };

  return (
    <div className="modern-space modern-analysis-detail">
      <IslandPageHeader
        title="分析详情"
        description="结论、关键时刻、身体姿态和追问都集中在同一次复盘里。"
        action={<Link className="island-button island-button--secondary" to="/review">返回冰场小屋</Link>}
      />
      <SectionNav label="分析详情分区" items={sectionItems} activeId={view} />
      <div className="modern-analysis-detail__content">
        {view === "summary" ? <ReportPage /> : <ReportWorkspacePage forcedTab={workspaceTab[view]} hideHeader />}
      </div>
    </div>
  );
}
