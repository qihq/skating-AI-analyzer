import { Navigate, Route, Routes } from "react-router-dom";

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

export default function App() {
  return (
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
  );
}
