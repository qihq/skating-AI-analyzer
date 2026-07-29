import { createContext, ReactNode, useContext, useEffect, useState } from "react";

import { fetchRuntimeCapabilities } from "./api";
import { CapabilityLoadState, legacyFallbackCapabilities, RuntimeCapabilities } from "./contracts";

interface CapabilityContextValue { capabilities: RuntimeCapabilities; loadState: CapabilityLoadState }
const CapabilityContext = createContext<CapabilityContextValue | null>(null);

export function CapabilityProvider({ children }: { children: ReactNode }) {
  const [capabilities, setCapabilities] = useState(() => legacyFallbackCapabilities("loading"));
  const [loadState, setLoadState] = useState<CapabilityLoadState>("loading");
  useEffect(() => {
    let active = true;
    void fetchRuntimeCapabilities().then((next) => {
      if (!active) return;
      setCapabilities(next);
      setLoadState(next.compatible ? "ready" : "fallback");
    }).catch(() => {
      if (!active) return;
      setCapabilities(legacyFallbackCapabilities("unavailable"));
      setLoadState("fallback");
    });
    return () => { active = false; };
  }, []);
  return <CapabilityContext.Provider value={{ capabilities, loadState }}>{children}</CapabilityContext.Provider>;
}

export function useRuntimeCapabilities() {
  const value = useContext(CapabilityContext);
  if (!value) throw new Error("useRuntimeCapabilities must be used inside CapabilityProvider");
  return value;
}
