import { ReactNode } from "react";

import { useAppearance } from "../components/AppearanceContext";

export default function ThemedPage({ classic, modern }: { classic: ReactNode; modern: ReactNode }) {
  const { isModern } = useAppearance();
  return <>{isModern ? modern : classic}</>;
}
