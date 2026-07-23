import { ReactNode } from "react";
import { Navigate, useSearchParams } from "react-router-dom";

import ModernReviewSpace from "./ModernReviewSpace";

export default function ModernAnalysisChatRoute({ children }: { children: ReactNode }) {
  const [params] = useSearchParams();
  const analysisId = params.get("analysis");

  if (analysisId) {
    return <Navigate replace to={`/analysis/${encodeURIComponent(analysisId)}?view=ask`} />;
  }

  return (
    <ModernReviewSpace
      title="选择一次复盘"
      description="选择已有分析后，会直接进入这次复盘的追问分区；所有结论和对话都留在同一个分析空间。"
    >
      {children}
    </ModernReviewSpace>
  );
}
