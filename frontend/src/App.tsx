import { lazy, Suspense, useEffect, useLayoutEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import AppLayout from "./components/AppLayout";
import ModernGrowthSpace, { ModernGrowthFrame } from "./modern/ModernGrowthSpace";
import ModernMeSpace, { ModernAdvancedTool } from "./modern/ModernMeSpace";
import ThemedPage from "./modern/ThemedPage";
import ModernReviewSpace from "./modern/ModernReviewSpace";
import ModernOnlyLayout from "./modern/ModernOnlyLayout";
import ModernAnalysisChatRoute from "./modern/ModernAnalysisChatRoute";

const AnalysisChatPage = lazy(() => import("./pages/AnalysisChatPage"));
const ApiSettingsPage = lazy(() => import("./pages/ApiSettingsPage"));
const ComparePage = lazy(() => import("./pages/ComparePage"));
const DebugPage = lazy(() => import("./pages/DebugPage"));
const ArchivePage = lazy(() => import("./pages/ArchivePage"));
const HistoryPage = lazy(() => import("./pages/HistoryPage"));
const GrowthHomePage = lazy(() => import("./pages/GrowthHomePage"));
const MonthlyChaptersPage = lazy(() => import("./pages/MonthlyChaptersPage"));
const AnnualCollectionPage = lazy(() => import("./pages/AnnualCollectionPage"));
const ParentSetupPage = lazy(() => import("./pages/ParentSetupPage"));
const PlanPage = lazy(() => import("./pages/PlanPage"));
const PoseDebugPage = lazy(() => import("./pages/PoseDebugPage"));
const ReportPage = lazy(() => import("./pages/ReportPage"));
const ReportWorkspacePage = lazy(() => import("./pages/ReportWorkspacePage"));
const ReviewPage = lazy(() => import("./pages/ReviewPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const SkillTreePage = lazy(() => import("./pages/SkillTreePage"));
const SnowballPage = lazy(() => import("./pages/SnowballPage"));
const TargetSelectionPage = lazy(() => import("./pages/TargetSelectionPage"));
const ModernAnalysisDetail = lazy(() => import("./modern/ModernAnalysisDetail"));
const AnalysisExperienceReport = lazy(() => import("./analysis-v2/components/AnalysisExperienceReport"));
const ModernTodayIsland = lazy(() => import("./modern/ModernTodayIsland"));

function ScrollToTopOnRouteChange() {
  const location = useLocation();

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [location.pathname]);

  return null;
}

function canScrollWithin(element: Element, deltaY: number) {
  let current: Element | null = element;

  while (current && current !== document.body && current !== document.documentElement) {
    if (current instanceof HTMLElement) {
      const style = window.getComputedStyle(current);
      const overflowY = style.overflowY;
      const allowsScroll = overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay";
      const maxScrollTop = current.scrollHeight - current.clientHeight;

      if (allowsScroll && maxScrollTop > 0) {
        if ((deltaY < 0 && current.scrollTop > 0) || (deltaY > 0 && current.scrollTop < maxScrollTop)) {
          return true;
        }
      }
    }

    current = current.parentElement;
  }

  return false;
}

function DesktopWheelScrollFallback() {
  useEffect(() => {
    if (!window.matchMedia("(pointer: fine)").matches) {
      return;
    }

    const handleWheel = (event: WheelEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || Math.abs(event.deltaY) < Math.abs(event.deltaX)) {
        return;
      }

      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }

      if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "TEXTAREA" || tag === "SELECT") {
          return;
        }
        if (tag === "INPUT" && (target as HTMLInputElement).type !== "range") {
          return;
        }
      }

      if (canScrollWithin(target, event.deltaY)) {
        return;
      }

      const scrollingElement = document.scrollingElement;
      if (!(scrollingElement instanceof HTMLElement)) {
        return;
      }

      const maxScrollTop = scrollingElement.scrollHeight - window.innerHeight;
      if (maxScrollTop <= 0) {
        return;
      }

      const canScrollUp = event.deltaY < 0 && scrollingElement.scrollTop > 0;
      const canScrollDown = event.deltaY > 0 && scrollingElement.scrollTop < maxScrollTop;
      if (!canScrollUp && !canScrollDown) {
        return;
      }

      event.preventDefault();
      window.scrollBy({ top: event.deltaY, left: 0, behavior: "auto" });
    };

    window.addEventListener("wheel", handleWheel, { capture: true, passive: false });
    return () => window.removeEventListener("wheel", handleWheel, true);
  }, []);

  return null;
}

export default function App() {
  return (
    <>
      <ScrollToTopOnRouteChange />
      <DesktopWheelScrollFallback />

      <Suspense fallback={<div className="app-route-loading" role="status">正在打开 IceBuddy…</div>}>
      <Routes>
        <Route path="/" element={<Navigate to="/home" replace />} />
        <Route path="/upload" element={<Navigate to="/review" replace />} />
        <Route path="/skills" element={<Navigate to="/path" replace />} />
        <Route path="/progress" element={<Navigate to="/archive" replace />} />

        <Route element={<AppLayout />}>
          <Route path="/home" element={<ThemedPage classic={<GrowthHomePage />} modern={<ModernTodayIsland />} />} />
          <Route path="/growth" element={<ModernGrowthSpace />} />
          <Route path="/chapters" element={<ThemedPage classic={<MonthlyChaptersPage />} modern={<ModernGrowthFrame view="chapters"><MonthlyChaptersPage /></ModernGrowthFrame>} />} />
          <Route path="/annual" element={<ThemedPage classic={<AnnualCollectionPage />} modern={<ModernGrowthFrame view="annual"><AnnualCollectionPage /></ModernGrowthFrame>} />} />
          <Route path="/path" element={<ThemedPage classic={<SkillTreePage />} modern={<ModernGrowthFrame view="skills"><SkillTreePage /></ModernGrowthFrame>} />} />
          <Route path="/snowball" element={<ThemedPage classic={<SnowballPage />} modern={<ModernGrowthFrame view="snowball"><SnowballPage /></ModernGrowthFrame>} />} />
          <Route path="/review" element={<ThemedPage classic={<ReviewPage />} modern={<ModernReviewSpace><ReviewPage /></ModernReviewSpace>} />} />
          <Route path="/analysis-chat" element={<ThemedPage classic={<AnalysisChatPage />} modern={<ModernAnalysisChatRoute><AnalysisChatPage autoSelectFirst={false} showSelectorWhenEmpty /></ModernAnalysisChatRoute>} />} />
          <Route path="/archive" element={<ThemedPage classic={<ArchivePage />} modern={<ModernGrowthFrame view="timeline"><ArchivePage /></ModernGrowthFrame>} />} />
          <Route path="/history" element={<ThemedPage classic={<HistoryPage />} modern={<ModernGrowthFrame view="timeline"><HistoryPage /></ModernGrowthFrame>} />} />
          <Route path="/compare/results/:comparison_id" element={<ThemedPage classic={<ComparePage />} modern={<ModernGrowthFrame view="compare"><ComparePage /></ModernGrowthFrame>} />} />
          <Route path="/compare/:id_a/:id_b" element={<ThemedPage classic={<ComparePage />} modern={<ModernGrowthFrame view="compare"><ComparePage /></ModernGrowthFrame>} />} />
          <Route path="/analysis/:id" element={<ModernAnalysisDetail />} />
          {/* Ordinary report/history links use one authority-backed presenter in both themes. */}
          <Route path="/report/:id" element={<AnalysisExperienceReport />} />
          <Route path="/report/:id/workspace" element={<ThemedPage classic={<ReportWorkspacePage />} modern={<ModernAnalysisDetail />} />} />
          <Route path="/report/:id/pose-debug" element={<ThemedPage classic={<PoseDebugPage />} modern={<ModernAnalysisDetail initialView="more" />} />} />
          <Route path="/report/:id/target" element={<ThemedPage classic={<TargetSelectionPage />} modern={<ModernReviewSpace title="确认主滑行者" description="确认这次要分析的滑行者，然后继续生成同一份复盘。"><TargetSelectionPage hideHeader /></ModernReviewSpace>} />} />
          <Route path="/me" element={<ModernMeSpace />} />
          <Route path="/me/advanced" element={<ModernAdvancedTool />} />
          <Route path="/settings" element={<ThemedPage classic={<SettingsPage />} modern={<ModernMeSpace />} />} />
          <Route path="/settings/api" element={<ThemedPage classic={<ApiSettingsPage />} modern={<ModernAdvancedTool />} />} />
          <Route path="/debug" element={<ThemedPage classic={<DebugPage />} modern={<ModernAdvancedTool initialTool="debug" />} />} />
          <Route path="/golden" element={<ThemedPage classic={<DebugPage workspace="golden" />} modern={<ModernAdvancedTool initialTool="golden" />} />} />
        </Route>
        <Route element={<ModernOnlyLayout />}>
          <Route path="/parent/setup" element={<ThemedPage classic={<ParentSetupPage />} modern={<ModernMeSpace />} />} />
          <Route path="/plan/:plan_id" element={<ThemedPage classic={<PlanPage />} modern={<ModernGrowthFrame view="plans"><PlanPage /></ModernGrowthFrame>} />} />
        </Route>
      </Routes>
      </Suspense>
    </>
  );
}
