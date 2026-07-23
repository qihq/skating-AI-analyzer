import { ReactNode } from "react";

import { IslandPageHeader } from "./IslandSurface";

export default function ModernReviewSpace({ children, title = "冰场小屋", description = "上传训练视频，确认滑冰者和分析目标，然后安心等待复盘结果。" }: { children: ReactNode; title?: string; description?: string }) {
  return <div className="modern-space modern-review-space"><IslandPageHeader title={title} description={description}/><div className="modern-legacy-surface">{children}</div></div>;
}
