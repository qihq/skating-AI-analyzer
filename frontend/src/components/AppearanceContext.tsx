import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";

export type UiTheme = "classic" | "modern";

type AppearanceContextValue = {
  theme: UiTheme;
  isModern: boolean;
  isIceGlass: boolean;
  setTheme: (nextTheme: UiTheme) => void;
  toggleTheme: () => void;
};

const THEME_STORAGE_KEY = "icebuddy.ui-theme";
const AppearanceContext = createContext<AppearanceContextValue | null>(null);

function readInitialTheme(): UiTheme {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return stored === "modern" || stored === "ice-glass" ? "modern" : "classic";
}

export function useAppearance() {
  const value = useContext(AppearanceContext);
  if (!value) {
    throw new Error("useAppearance must be used inside AppearanceProvider");
  }
  return value;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<UiTheme>(readInitialTheme);

  const setTheme = (nextTheme: UiTheme) => {
    setThemeState(nextTheme);
    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
  };

  const value = useMemo<AppearanceContextValue>(
    () => ({
      theme,
      isModern: theme === "modern",
      isIceGlass: theme === "modern",
      setTheme,
      toggleTheme: () => setTheme(theme === "modern" ? "classic" : "modern"),
    }),
    [theme],
  );

  useEffect(() => {
    document.documentElement.dataset.uiTheme = theme;
  }, [theme]);

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}
