import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { extendPlan, fetchPlan, TrainingPlanDetail, updatePlanSession } from "../api/client";

const LOCATION_MODE_STORAGE_KEY = "plan_location_mode";

type LocationMode = "home" | "rink";
type PlanLocationState = {
  focusSessionId?: string;
  focusDay?: number;
} | null;

function sessionTypeLabel(isOfficeTrainable: boolean) {
  return isOfficeTrainable ? "居家可练" : "需上冰";
}

function sessionTypeTone(isOfficeTrainable: boolean) {
  return isOfficeTrainable ? "bg-emerald-50 text-emerald-600" : "bg-sky-50 text-sky-600";
}

export default function PlanPage() {
  const { plan_id } = useParams<{ plan_id: string }>();
  const location = useLocation();
  const [plan, setPlan] = useState<TrainingPlanDetail | null>(null);
  const [expandedDays, setExpandedDays] = useState<number[]>([1]);
  const [savingSessionIds, setSavingSessionIds] = useState<string[]>([]);
  const [locationMode, setLocationMode] = useState<LocationMode>(() => {
    const stored = window.localStorage.getItem(LOCATION_MODE_STORAGE_KEY);
    return stored === "rink" ? "rink" : "home";
  });
  const [notice, setNotice] = useState<string | null>(null);
  const [isExtending, setIsExtending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focusedSessionId, setFocusedSessionId] = useState<string | null>(null);
  const [hasAppliedFocusTarget, setHasAppliedFocusTarget] = useState(false);
  const routeState = location.state as PlanLocationState;
  const focusSessionId = routeState?.focusSessionId ?? null;
  const focusDay = routeState?.focusDay ?? null;

  useEffect(() => {
    if (!plan_id) {
      setError("无效的训练计划 ID。");
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchPlan(plan_id);
        if (!cancelled) {
          setPlan(data);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("训练计划加载失败，请稍后重试。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [plan_id]);

  useEffect(() => {
    window.localStorage.setItem(LOCATION_MODE_STORAGE_KEY, locationMode);
  }, [locationMode]);

  useEffect(() => {
    setHasAppliedFocusTarget(false);
  }, [focusSessionId]);

  useEffect(() => {
    if (typeof focusDay !== "number") {
      return;
    }
    setExpandedDays((current) => (current.includes(focusDay) ? current : [...current, focusDay]));
  }, [focusDay]);

  useEffect(() => {
    if (!plan || !focusSessionId || hasAppliedFocusTarget) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const target = document.querySelector<HTMLElement>(`[data-plan-session-id="${focusSessionId}"]`);
      const scrollContainer = document.querySelector<HTMLElement>(".page-scroll-container");
      if (!target) {
        return;
      }

      setFocusedSessionId(focusSessionId);
      setHasAppliedFocusTarget(true);
      window.setTimeout(() => setFocusedSessionId((current) => (current === focusSessionId ? null : current)), 2200);

      if (scrollContainer) {
        const containerRect = scrollContainer.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const nextTop = scrollContainer.scrollTop + (targetRect.top - containerRect.top) - 92;
        scrollContainer.scrollTo({ top: Math.max(nextTop, 0), behavior: "smooth" });
        return;
      }

      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    return () => window.cancelAnimationFrame(frame);
  }, [expandedDays, focusSessionId, hasAppliedFocusTarget, plan]);

  const progress = useMemo(() => {
    if (!plan) {
      return { completed: 0, total: 0, percent: 0 };
    }
    const total = plan.plan_json.days.reduce((sum, day) => sum + day.sessions.length, 0);
    const completed = plan.plan_json.days.reduce(
      (sum, day) => sum + day.sessions.filter((session) => session.completed).length,
      0,
    );
    return {
      completed,
      total,
      percent: total ? Math.round((completed / total) * 100) : 0,
    };
  }, [plan]);

  const completedDays = useMemo(() => {
    if (!plan) {
      return [];
    }
    return plan.plan_json.days
      .filter((day) => day.sessions.some((session) => session.completed))
      .map((day) => day.day);
  }, [plan]);

  const canExtendPlan = completedDays.length >= 3;

  const toggleDay = (day: number) => {
    setExpandedDays((current) => (current.includes(day) ? current.filter((item) => item !== day) : [...current, day]));
  };

  const handleToggleSession = async (dayIndex: number, sessionIndex: number, nextCompleted: boolean) => {
    if (!plan || !plan_id) {
      return;
    }

    const session = plan.plan_json.days[dayIndex]?.sessions[sessionIndex];
    if (!session) {
      return;
    }

    const previousPlan = plan;
    const optimisticPlan: TrainingPlanDetail = {
      ...plan,
      plan_json: {
        ...plan.plan_json,
        days: plan.plan_json.days.map((day, currentDayIndex) =>
          currentDayIndex === dayIndex
            ? {
                ...day,
                sessions: day.sessions.map((item, currentSessionIndex) =>
                  currentSessionIndex === sessionIndex ? { ...item, completed: nextCompleted } : item,
                ),
              }
            : day,
        ),
      },
    };

    setPlan(optimisticPlan);
    setSavingSessionIds((current) => [...current, session.id]);
    setError(null);

    try {
      const updated = await updatePlanSession(plan_id, session.id, nextCompleted);
      setPlan(updated);
    } catch (requestError) {
      setPlan(previousPlan);
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "训练项目状态更新失败，请稍后重试。"));
      } else {
        setError("训练项目状态更新失败，请稍后重试。");
      }
    } finally {
      setSavingSessionIds((current) => current.filter((id) => id !== session.id));
    }
  };

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const handleExtendPlan = async () => {
    if (!plan || !plan_id || !canExtendPlan) {
      return;
    }

    setIsExtending(true);
    setError(null);
    try {
      const updated = await extendPlan(plan_id, completedDays);
      setPlan(updated);
      showNotice("冰宝（IceBuddy）已根据你的进度更新了后续安排 ✨");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "计划续期失败，请稍后重试。"));
      } else {
        setError("计划续期失败，请稍后重试。");
      }
    } finally {
      setIsExtending(false);
    }
  };

  return (
    <main className="app-shell page-scroll-container page-content min-h-screen">
      <section className="page-content safe-bottom mx-auto min-h-screen w-full max-w-[1480px] px-4 pt-20 phone:px-5 tablet:px-6 tablet:pt-24 web:px-8 web:pb-10">
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link to={plan ? `/report/${plan.analysis_id}` : "/review"} className="app-pill">
              ← 返回诊断详情
            </Link>
            <div className="rounded-full border border-slate-200 bg-white/90 px-4 py-2 text-sm font-medium text-slate-600 shadow-sm">
              整体进度 {progress.completed}/{progress.total}
            </div>
          </div>

          {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
          {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

          {plan ? (
            <>
              <header className="app-card overflow-hidden p-6 tablet:p-8">
                <div className="grid gap-6 web:grid-cols-[1.1fr_0.9fr] web:items-end">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">7-Day Plan</p>
                    <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">{plan.plan_json.title}</h1>
                    <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">训练聚焦：{plan.plan_json.focus_skill}</p>
                  </div>

                  <div className="rounded-[28px] border border-blue-100 bg-blue-50/70 p-5">
                    <div className="flex items-center justify-between text-sm font-medium text-slate-600">
                      <span>本周完成度</span>
                      <span>{progress.percent}%</span>
                    </div>
                    <div className="mt-3 h-3 overflow-hidden rounded-full bg-white">
                      <div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-violet-500 transition-all duration-500" style={{ width: `${progress.percent}%` }} />
                    </div>
                    <p className="mt-3 text-sm text-slate-500">按天展开查看训练内容，完成后可直接勾选，进度会自动保存。</p>
                  </div>
                </div>

                <div className="mt-6 inline-flex rounded-full bg-slate-100 p-1">
                  <button
                    type="button"
                    onClick={() => setLocationMode("home")}
                    className={`min-h-[44px] rounded-full px-4 text-sm font-semibold transition ${
                      locationMode === "home" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
                    }`}
                  >
                    🏠 今天在家
                  </button>
                  <button
                    type="button"
                    onClick={() => setLocationMode("rink")}
                    className={`min-h-[44px] rounded-full px-4 text-sm font-semibold transition ${
                      locationMode === "rink" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
                    }`}
                  >
                    ⛸️ 今天在冰场
                  </button>
                </div>

                <div className="mt-6 overflow-x-auto">
                  <div className="flex min-w-max gap-3">
                    {plan.plan_json.days.map((day) => {
                      const expanded = expandedDays.includes(day.day);
                      return (
                        <button
                          key={day.day}
                          type="button"
                          onClick={() => toggleDay(day.day)}
                          className={`min-w-[156px] rounded-[24px] border px-4 py-4 text-left transition ${
                            expanded
                              ? "border-blue-200 bg-blue-50 text-slate-900 shadow-sm"
                              : "border-slate-200 bg-white text-slate-600 hover:border-blue-100 hover:bg-slate-50"
                          }`}
                        >
                          <p className={`text-xs font-semibold uppercase tracking-[0.24em] ${expanded ? "text-blue-500" : "text-slate-400"}`}>Day {day.day}</p>
                          <p className="mt-2 text-sm font-medium">{day.theme}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </header>

              <div className="space-y-4">
                {plan.plan_json.days.map((day, dayIndex) => {
                  const isExpanded = expandedDays.includes(day.day);
                  const completedCount = day.sessions.filter((session) => session.completed).length;
                  const visibleSessions =
                    locationMode === "home" ? day.sessions.filter((session) => session.is_office_trainable) : day.sessions;

                  return (
                    <article key={day.day} className="app-card p-5 tablet:p-6">
                      <button
                        type="button"
                        onClick={() => toggleDay(day.day)}
                        className="flex w-full flex-col gap-4 text-left tablet:flex-row tablet:items-center tablet:justify-between"
                      >
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">Day {day.day}</p>
                          <h2 className="mt-2 text-2xl font-semibold text-slate-900">{day.theme}</h2>
                        </div>
                        <div className="flex flex-wrap items-center gap-3">
                          <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">
                            已完成 {completedCount}/{day.sessions.length}
                          </span>
                          <span className="text-sm font-medium text-slate-500">{isExpanded ? "收起" : "展开"}</span>
                        </div>
                      </button>

                      {isExpanded ? (
                        <div className="mt-5 space-y-3">
                          {visibleSessions.length ? (
                            visibleSessions.map((session) => {
                              const sessionIndex = day.sessions.findIndex((item) => item.id === session.id);
                              const isSaving = savingSessionIds.includes(session.id);
                              return (
                                <label
                                  key={session.id}
                                  data-plan-session-id={session.id}
                                  className={`list-row flex gap-4 rounded-[24px] border p-4 transition ${
                                    focusedSessionId === session.id
                                      ? "border-blue-300 bg-blue-50/90 shadow-[0_16px_32px_rgba(59,130,246,0.14)]"
                                      : session.completed
                                        ? "border-emerald-200 bg-emerald-50/70"
                                        : "border-slate-200 bg-slate-50/80"
                                  }`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={session.completed}
                                    disabled={isSaving}
                                    onChange={(event) => handleToggleSession(dayIndex, sessionIndex, event.target.checked)}
                                    className="mt-1 h-5 w-5 shrink-0 accent-blue-500"
                                  />

                                  <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <h3 className="text-lg font-semibold text-slate-900">{session.title}</h3>
                                      <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-500">{session.duration}</span>
                                      <span className={`rounded-full px-3 py-1 text-xs font-medium ${sessionTypeTone(session.is_office_trainable)}`}>
                                        {sessionTypeLabel(session.is_office_trainable)}
                                      </span>
                                      {isSaving ? <span className="text-xs text-slate-400">保存中...</span> : null}
                                    </div>

                                    <p className="mt-3 leading-7 text-slate-600">{session.description}</p>
                                  </div>
                                </label>
                              );
                            })
                          ) : locationMode === "home" && day.day === 7 ? (
                            <div className="rounded-[24px] border border-sky-100 bg-sky-50 px-4 py-4 text-sm text-sky-700">
                              今天需要上冰才能练，切换到「在冰场」模式查看。
                            </div>
                          ) : (
                            <div className="rounded-[24px] bg-slate-50 px-4 py-4 text-sm text-slate-500">这一天暂时没有训练项目。</div>
                          )}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>

              {canExtendPlan ? (
                <div className="app-card border border-blue-100 bg-white/90 p-6">
                  <button
                    type="button"
                    onClick={handleExtendPlan}
                    disabled={isExtending}
                    className="min-h-[44px] rounded-full border border-blue-300 bg-white px-5 py-3 text-sm font-semibold text-blue-600 transition hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isExtending ? "续期中..." : "📅 根据进度续期计划"}
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <div className="app-card p-6 text-sm text-slate-500">正在加载训练计划...</div>
          )}
        </div>
      </section>
    </main>
  );
}
