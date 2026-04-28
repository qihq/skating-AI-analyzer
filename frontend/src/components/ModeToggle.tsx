import { TouchEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { childViewAvatarType, childViewLabel } from "../utils/childView";
import { useAppMode } from "./AppModeContext";
import ZodiacAvatar from "./ZodiacAvatar";

function ParentModeAvatar() {
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-900 text-[15px] text-white shadow-sm" aria-hidden="true">
      🔐
    </div>
  );
}

export default function ModeToggle() {
  const location = useLocation();
  const { isParentMode, childView, enterParentMode, switchToChildMode, switchToChildView } = useAppMode();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [dragOffset, setDragOffset] = useState(0);
  const touchStartYRef = useRef<number | null>(null);
  const currentChildLabel = childViewLabel(childView);

  const currentMobileAvatar = useMemo(() => {
    if (isParentMode) {
      return <ParentModeAvatar />;
    }

    return <ZodiacAvatar avatarType={childViewAvatarType(childView)} size="sm" />;
  }, [childView, isParentMode]);

  useEffect(() => {
    setSheetOpen(false);
    setDragOffset(0);
    touchStartYRef.current = null;
  }, [location.pathname]);

  useEffect(() => {
    if (!sheetOpen) {
      return;
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSheetOpen(false);
        setDragOffset(0);
      }
    };

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [sheetOpen]);

  const closeSheet = () => {
    setSheetOpen(false);
    setDragOffset(0);
    touchStartYRef.current = null;
  };

  const handleSelectView = async (nextView: "tantan" | "zhaozao" | "parent") => {
    if (nextView === "parent") {
      closeSheet();
      if (!isParentMode) {
        await enterParentMode();
      }
      return;
    }

    switchToChildView(nextView);
    closeSheet();
  };

  const handleTouchStart = (event: TouchEvent<HTMLDivElement>) => {
    touchStartYRef.current = event.touches[0]?.clientY ?? null;
  };

  const handleTouchMove = (event: TouchEvent<HTMLDivElement>) => {
    if (touchStartYRef.current === null) {
      return;
    }

    const currentY = event.touches[0]?.clientY ?? touchStartYRef.current;
    setDragOffset(Math.max(0, currentY - touchStartYRef.current));
  };

  const handleTouchEnd = () => {
    if (dragOffset > 96) {
      closeSheet();
      return;
    }

    setDragOffset(0);
    touchStartYRef.current = null;
  };

  return (
    <>
      <div className="hidden items-center gap-1 rounded-full bg-slate-100 p-1 shadow-sm tablet:flex">
        <button
          type="button"
          onClick={switchToChildMode}
          className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
            !isParentMode ? "bg-kid-primary text-white shadow-sm" : "text-slate-500"
          }`}
        >
          {currentChildLabel}模式
        </button>
        <button
          type="button"
          onClick={() => {
            if (!isParentMode) {
              void enterParentMode();
            }
          }}
          className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
            isParentMode ? "bg-blue-500 text-white shadow-sm" : "text-slate-500"
          }`}
        >
          家长模式
        </button>
      </div>

      <button
        type="button"
        aria-label="选择视角"
        onClick={() => setSheetOpen(true)}
        className="flex h-10 w-10 items-center justify-center rounded-full transition hover:bg-slate-100 tablet:hidden"
      >
        {currentMobileAvatar}
      </button>

      {sheetOpen ? (
        <div className="fixed inset-0 z-[70] tablet:hidden">
          <button
            type="button"
            aria-label="关闭视角选择"
            className="absolute inset-0 bg-black/40"
            onClick={closeSheet}
            onWheel={(event) => event.stopPropagation()}
          />

          <div className="absolute inset-x-0 bottom-0">
            <div
              role="dialog"
              aria-modal="true"
              aria-label="选择视角"
              className="rounded-t-2xl bg-white px-4 pb-[calc(env(safe-area-inset-bottom,0px)+16px)] pt-2 shadow-[0_-18px_40px_rgba(15,23,42,0.18)]"
              style={{
                transform: `translateY(${dragOffset}px)`,
                transition: dragOffset ? "none" : "transform 0.2s ease-out",
                touchAction: "none",
              }}
              onTouchStart={handleTouchStart}
              onTouchMove={handleTouchMove}
              onTouchEnd={handleTouchEnd}
            >
              <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-slate-300" />
              <h2 className="px-2 pb-4 pt-5 text-lg font-semibold text-slate-900">选择视角</h2>

              <div className="space-y-1">
                {[
                  { key: "tantan", label: "坦坦", icon: <ZodiacAvatar avatarType="zodiac_rat" size="sm" /> },
                  { key: "zhaozao", label: "昭昭", icon: <ZodiacAvatar avatarType="zodiac_tiger" size="sm" /> },
                  { key: "parent", label: "家长", note: "输入 PIN", icon: <ParentModeAvatar /> },
                ].map((option) => {
                  const selected = option.key === "parent" ? isParentMode : !isParentMode && childView === option.key;

                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => void handleSelectView(option.key as "tantan" | "zhaozao" | "parent")}
                      className="relative flex min-h-[56px] w-full items-center gap-3 overflow-hidden rounded-2xl px-4 py-3 text-left transition hover:bg-slate-50"
                    >
                      {selected ? <span className="absolute inset-y-2 left-0 w-1 rounded-r-full bg-blue-500" /> : null}
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center">{option.icon}</div>
                      <div className="flex items-baseline gap-2">
                        <span className="text-base font-medium text-slate-900">{option.label}</span>
                        {option.note ? <span className="text-sm text-slate-400">{option.note}</span> : null}
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="mt-4 border-t border-slate-200 pt-4">
                <button
                  type="button"
                  onClick={closeSheet}
                  className="min-h-[48px] w-full rounded-full bg-slate-100 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-200"
                >
                  取消
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
