import axios from "axios";
import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { fetchHasPin, verifyPin } from "../api/client";
import { ChildView } from "../utils/childView";
import ParentUnlockModal from "./ParentUnlockModal";

type AppMode = "child" | "parent";

type AppModeContextValue = {
  mode: AppMode;
  isParentMode: boolean;
  childView: ChildView;
  hasPin: boolean | null;
  pinLength: number;
  openParentDialog: () => void;
  setChildView: (nextView: ChildView) => void;
  switchToChildView: (nextView: ChildView) => void;
  switchToChildMode: () => void;
  enterParentMode: () => Promise<void>;
  activateParentMode: () => void;
  refreshPinState: () => Promise<void>;
};

const AppModeContext = createContext<AppModeContextValue | null>(null);
const MODE_STORAGE_KEY = "icebuddy.account-mode";
const CHILD_VIEW_STORAGE_KEY = "icebuddy.child-view";
const LOCK_SECONDS = 30;

export function useAppMode() {
  const value = useContext(AppModeContext);
  if (!value) {
    throw new Error("useAppMode must be used inside AppModeProvider");
  }
  return value;
}

function readInitialMode(): AppMode {
  return window.localStorage.getItem(MODE_STORAGE_KEY) === "parent" ? "parent" : "child";
}

function readInitialChildView(): ChildView {
  return window.localStorage.getItem(CHILD_VIEW_STORAGE_KEY) === "zhaozao" ? "zhaozao" : "tantan";
}

export function AppModeProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState<AppMode>(readInitialMode);
  const [childView, setChildViewState] = useState<ChildView>(readInitialChildView);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [hasPin, setHasPin] = useState<boolean | null>(null);
  const [pinLength, setPinLength] = useState(4);
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [failedAttempts, setFailedAttempts] = useState(0);
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState(() => Date.now());

  const lockSecondsLeft = lockedUntil ? Math.max(0, Math.ceil((lockedUntil - nowTick) / 1000)) : 0;
  const isLocked = lockSecondsLeft > 0;

  useEffect(() => {
    if (!lockedUntil) {
      return;
    }
    const timer = window.setInterval(() => setNowTick(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [lockedUntil]);

  useEffect(() => {
    if (lockedUntil && Date.now() >= lockedUntil) {
      setLockedUntil(null);
      setFailedAttempts(0);
      setError(null);
      setNowTick(Date.now());
    }
  }, [lockedUntil, nowTick]);

  const setModeAndPersist = (nextMode: AppMode) => {
    setMode(nextMode);
    window.localStorage.setItem(MODE_STORAGE_KEY, nextMode);
  };

  const setChildViewAndPersist = (nextView: ChildView) => {
    setChildViewState(nextView);
    window.localStorage.setItem(CHILD_VIEW_STORAGE_KEY, nextView);
  };

  const refreshPinState = async () => {
    try {
      const data = await fetchHasPin();
      setHasPin(data.has_pin);
      setPinLength(data.pin_length ?? 4);
    } catch {
      setHasPin(false);
      setPinLength(4);
    }
  };

  useEffect(() => {
    void refreshPinState();
  }, []);

  useEffect(() => {
    setDialogOpen(false);
    setPin("");
    setError(null);
  }, [location.pathname]);

  const openParentDialog = () => {
    setError(null);
    setPin("");
    setDialogOpen(true);
  };

  const enterParentMode = async () => {
    let nextHasPin = hasPin;
    if (nextHasPin === null) {
      try {
        const data = await fetchHasPin();
        nextHasPin = data.has_pin;
        setHasPin(data.has_pin);
        setPinLength(data.pin_length ?? 4);
      } catch {
        nextHasPin = false;
        setHasPin(false);
        setPinLength(4);
      }
    }

    if (nextHasPin === false) {
      navigate("/parent/setup");
      return;
    }

    openParentDialog();
  };

  const switchToChildMode = () => {
    setModeAndPersist("child");
    setDialogOpen(false);
    setPin("");
    setError(null);
  };

  const switchToChildView = (nextView: ChildView) => {
    setChildViewAndPersist(nextView);
    switchToChildMode();
  };

  const handleSubmit = async () => {
    if (isLocked) {
      return;
    }
    if (!new RegExp(`^\\d{${pinLength}}$`).test(pin)) {
      setError(`请输入 ${pinLength} 位数字 PIN。`);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const data = await verifyPin(pin);
      if (!data.valid) {
        const nextAttempts = failedAttempts + 1;
        setFailedAttempts(nextAttempts);
        setPin("");
        if (nextAttempts >= 3) {
          setLockedUntil(Date.now() + LOCK_SECONDS * 1000);
          setError("PIN 已连续输错 3 次。");
        } else {
          setError("PIN 不正确，请再试一次。");
        }
        return;
      }

      setFailedAttempts(0);
      setLockedUntil(null);
      setModeAndPersist("parent");
      setDialogOpen(false);
      setPin("");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "家长模式验证失败，请稍后重试。"));
      } else {
        setError("家长模式验证失败，请稍后重试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AppModeContext.Provider
      value={{
        mode,
        isParentMode: mode === "parent",
        childView,
        hasPin,
        pinLength,
        openParentDialog,
        setChildView: setChildViewAndPersist,
        switchToChildView,
        switchToChildMode,
        enterParentMode,
        activateParentMode: () => setModeAndPersist("parent"),
        refreshPinState,
      }}
    >
      {children}

      {dialogOpen ? (
        <ParentUnlockModal
          pin={pin}
          pinLength={pinLength}
          error={error}
          failedAttempts={failedAttempts}
          isSubmitting={isSubmitting}
          locked={isLocked}
          lockSecondsLeft={lockSecondsLeft}
          onChangePin={setPin}
          onClose={() => setDialogOpen(false)}
          onSubmit={() => void handleSubmit()}
        />
      ) : null}
    </AppModeContext.Provider>
  );
}
