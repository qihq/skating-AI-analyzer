import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";

export type IslandPeriod = "morning" | "day" | "sunset" | "night";
export type IslandThemePreference = "auto" | IslandPeriod;

type IslandThemeContextValue = {
  period: IslandPeriod;
  preference: IslandThemePreference;
  setPreference: (preference: IslandThemePreference) => void;
};

const STORAGE_KEY = "icebuddy.island-theme";
const IslandThemeContext = createContext<IslandThemeContextValue | null>(null);

export function periodForHour(hour: number): IslandPeriod {
  if (hour >= 5 && hour < 9) return "morning";
  if (hour >= 9 && hour < 17) return "day";
  if (hour >= 17 && hour < 20) return "sunset";
  return "night";
}

function readPreference(): IslandThemePreference {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "morning" || stored === "day" || stored === "sunset" || stored === "night" ? stored : "auto";
}

export function IslandThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<IslandThemePreference>(readPreference);
  const [currentHour, setCurrentHour] = useState(() => new Date().getHours());

  useEffect(() => {
    if (preference !== "auto") return;
    const timer = window.setInterval(() => setCurrentHour(new Date().getHours()), 60_000);
    return () => window.clearInterval(timer);
  }, [preference]);

  const value = useMemo<IslandThemeContextValue>(() => ({
    period: preference === "auto" ? periodForHour(currentHour) : preference,
    preference,
    setPreference: (next) => {
      setPreferenceState(next);
      window.localStorage.setItem(STORAGE_KEY, next);
    },
  }), [currentHour, preference]);

  return <IslandThemeContext.Provider value={value}>{children}</IslandThemeContext.Provider>;
}

export function useIslandTheme() {
  const value = useContext(IslandThemeContext);
  if (!value) throw new Error("useIslandTheme must be used inside IslandThemeProvider");
  return value;
}
