import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { fetchAnalysisExperienceV2 } from "../analysis-v2/api";
import { AnalysisExperienceV2 } from "../analysis-v2/contracts";
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
  const [experience, setExperience] = useState<AnalysisExperienceV2 | null>(null);
  const [params] = useSearchParams();
  const view = resolveAnalysisView({ initialView, view: params.get("view"), legacyTab: params.get("tab") });
  const sectionItems = ITEMS.map((item) => ({
    ...item,
    to: `/analysis/${id}?view=${item.to}${item.id === "more" ? "&tool=diagnostics" : ""}`,
  }));
  const workspaceTab: Record<Exclude<AnalysisView, "summary">, WorkspaceTab> = {
    moments: "evidence", body: "pose", ask: "followup", more: "diagnostics",
  };

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setExperience(null);
    void fetchAnalysisExperienceV2(id)
      .then((next) => { if (!cancelled) setExperience(next); })
      .catch(() => { if (!cancelled) setExperience(null); });
    return () => { cancelled = true; };
  }, [id]);

  return (
    <div className="modern-space modern-analysis-detail">
      <IslandPageHeader
        title="分析详情"
        description="结论、关键时刻、身体姿态和追问都集中在同一次复盘里。"
        action={<Link className="island-button island-button--secondary" to="/review">返回冰场小屋</Link>}
      />
      <SectionNav label="分析详情分区" items={sectionItems} activeId={view} />
      {experience ? (
        <section className="modern-analysis-detail__experience" data-testid="analysis-experience-contract" aria-label="分析契约状态">
          <strong>{experience.authority === "v2" ? "V2" : "Legacy"}</strong>
          <span>{experience.diagnosticOnly ? "Diagnostic only" : experience.familyUsable ? "Ready" : "Unavailable"}</span>
          {experience.claims.find((claim) => claim.claimType === "report_summary")?.value != null ? (
            <p>{String(experience.claims.find((claim) => claim.claimType === "report_summary")?.value)}</p>
          ) : null}
        </section>
      ) : null}
      <div className="modern-analysis-detail__content">
        {view === "summary" ? <ReportPage /> : <ReportWorkspacePage forcedTab={workspaceTab[view]} hideHeader />}
      </div>
    </div>
  );
}
