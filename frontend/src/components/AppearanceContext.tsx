import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";

export type UiTheme = "classic" | "ice-glass";

type AppearanceContextValue = {
  theme: UiTheme;
  isIceGlass: boolean;
  setTheme: (nextTheme: UiTheme) => void;
  toggleTheme: () => void;
};

const THEME_STORAGE_KEY = "icebuddy.ui-theme";
const AppearanceContext = createContext<AppearanceContextValue | null>(null);

function readInitialTheme(): UiTheme {
  return window.localStorage.getItem(THEME_STORAGE_KEY) === "ice-glass" ? "ice-glass" : "classic";
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
      isIceGlass: theme === "ice-glass",
      setTheme,
      toggleTheme: () => setTheme(theme === "ice-glass" ? "classic" : "ice-glass"),
    }),
    [theme],
  );

  useEffect(() => {
    document.documentElement.dataset.uiTheme = theme;
  }, [theme]);

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}
