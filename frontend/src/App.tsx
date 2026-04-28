import { useEffect, useLayoutEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import AppLayout from "./components/AppLayout";
import ApiSettingsPage from "./pages/ApiSettingsPage";
import ComparePage from "./pages/ComparePage";
import ArchivePage from "./pages/ArchivePage";
import HistoryPage from "./pages/HistoryPage";
import ParentSetupPage from "./pages/ParentSetupPage";
import PlanPage from "./pages/PlanPage";
import ReportPage from "./pages/ReportPage";
import ReviewPage from "./pages/ReviewPage";
import SettingsPage from "./pages/SettingsPage";
import SkillTreePage from "./pages/SkillTreePage";
import SnowballPage from "./pages/SnowballPage";

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

      <Routes>
        <Route path="/" element={<Navigate to="/path" replace />} />
        <Route path="/upload" element={<Navigate to="/review" replace />} />
        <Route path="/skills" element={<Navigate to="/path" replace />} />
        <Route path="/progress" element={<Navigate to="/archive" replace />} />

        <Route element={<AppLayout />}>
          <Route path="/path" element={<SkillTreePage />} />
          <Route path="/snowball" element={<SnowballPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/archive" element={<ArchivePage />} />
          <Route path="/report/:id" element={<ReportPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/api" element={<ApiSettingsPage />} />
        </Route>

        <Route path="/history" element={<HistoryPage />} />
        <Route path="/parent/setup" element={<ParentSetupPage />} />
        <Route path="/compare/:id_a/:id_b" element={<ComparePage />} />
        <Route path="/plan/:plan_id" element={<PlanPage />} />
      </Routes>
    </>
  );
}
