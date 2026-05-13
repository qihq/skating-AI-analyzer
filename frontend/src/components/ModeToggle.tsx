import { TouchEvent, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "react-router-dom";

import { childViewAvatarType, childViewLabel, childViewModeLabel } from "../utils/childView";
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
  const currentModeLabel = isParentMode ? "家长模式" : childViewModeLabel(childView);

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

  const options: Array<{
    key: "tantan" | "zhaozao" | "parent";
    title: string;
    detail: string;
    icon: JSX.Element;
  }> = [
    {
      key: "tantan",
      title: "切换到儿童模式",
      detail: currentChildLabel === "坦坦" ? "当前孩子：坦坦" : "切到坦坦视角",
      icon: <ZodiacAvatar avatarType="zodiac_rat" size="sm" />,
    },
    {
      key: "zhaozao",
      title: "切换到昭昭模式",
      detail: "切到昭昭视角",
      icon: <ZodiacAvatar avatarType="zodiac_tiger" size="sm" />,
    },
    {
      key: "parent",
      title: "进入家长模式",
      detail: "需要输入家长 PIN",
      icon: <ParentModeAvatar />,
    },
  ];

  const modeSheet =
    sheetOpen && typeof document !== "undefined"
      ? createPortal(
          <div className="fixed inset-0 z-[9999] tablet:hidden">
            <button
              type="button"
              aria-label="关闭模式切换"
              className="absolute inset-0 bg-black/40"
              onClick={closeSheet}
              onWheel={(event) => event.stopPropagation()}
            />

            <div className="absolute inset-x-0 bottom-0">
              <div
                role="dialog"
                aria-modal="true"
                aria-label="切换儿童模式和家长模式"
                className="max-h-[calc(100dvh-24px)] overflow-y-auto rounded-t-2xl bg-white px-4 pb-[calc(env(safe-area-inset-bottom,0px)+16px)] pt-2 shadow-[0_-18px_40px_rgba(15,23,42,0.18)]"
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
                <div className="px-2 pb-4 pt-5">
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">Mode Switch</p>
                  <h2 className="mt-2 text-xl font-semibold text-slate-900">切换儿童/家长模式</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-500">点击下面任意一行即可切换。进入家长模式会弹出 PIN 验证。</p>
                </div>

                <div className="space-y-2">
                  {options.map((option) => {
                    const selected = option.key === "parent" ? isParentMode : !isParentMode && childView === option.key;

                    return (
                      <button
                        key={option.key}
                        type="button"
                        onClick={() => void handleSelectView(option.key)}
                        className={`relative flex min-h-[72px] w-full items-center gap-3 rounded-2xl border px-4 py-3 text-left transition ${
                          selected ? "border-blue-200 bg-blue-50" : "border-slate-100 bg-white hover:border-blue-100 hover:bg-slate-50"
                        }`}
                      >
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center">{option.icon}</div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-base font-semibold text-slate-900">{option.title}</span>
                            {selected ? <span className="rounded-full bg-blue-500 px-2 py-0.5 text-xs font-semibold text-white">当前</span> : null}
                          </div>
                          <p className="mt-1 text-sm text-slate-500">{option.detail}</p>
                        </div>
                        <span className="shrink-0 text-lg text-slate-300">›</span>
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
          </div>,
          document.body,
        )
      : null;

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
          {childViewModeLabel(childView)}
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
        aria-label="切换儿童模式和家长模式"
        onClick={() => setSheetOpen(true)}
        className="flex min-h-11 shrink-0 items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-2.5 pr-3 text-sm font-semibold text-blue-700 shadow-sm transition hover:bg-blue-100 tablet:hidden"
      >
        {currentMobileAvatar}
        <span className="flex flex-col items-start leading-tight">
          <span className="text-[11px] font-medium text-blue-500">切换模式</span>
          <span>{currentModeLabel}</span>
        </span>
      </button>

      {modeSheet}
    </>
  );
}
