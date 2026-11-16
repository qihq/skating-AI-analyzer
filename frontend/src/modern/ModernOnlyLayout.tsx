import TrialBanner from "../components/TrialBanner";
import { Outlet } from "react-router-dom";

import { useAppearance } from "../components/AppearanceContext";
import ModernAppShell from "./ModernAppShell";

export default function ModernOnlyLayout() {
  const { isModern } = useAppearance();
  return isModern ? <ModernAppShell /> : <><TrialBanner /><Outlet /></>;
}
