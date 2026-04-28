import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import axios from "axios";

import { ArchiveResponse, fetchArchive, fetchSkaters, retryAnalysis, Skater } from "../api/client";
import { useAppMode } from "../components/AppModeContext";
import ParentPinVerifyModal from "../components/ParentPinVerifyModal";
import RetryAnalysisConfirmSheet from "../components/RetryAnalysisConfirmSheet";
import { isAnalysisInProgress } from "../constants/analysisStatus";
import ZodiacAvatar from "../components/ZodiacAvatar";
import { pickSkaterIdForChildView } from "../utils/childView";

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;
const RANGE_OPTIONS = [
  { value: "7d", label: "近 7 天", days: 7 },
  { value: "30d", label: "近 30 天", days: 30 },
  { value: "all", label: "全部", days: null },
] as const;
const ALL_SKATERS_VIEW = "__all__";

type ParentRange = (typeof RANGE_OPTIONS)[number]["value"];
type ArchiveStats = ArchiveResponse["stats"];
type ArchiveTimelineEntry = ArchiveResponse["timeline"][number] & {
  skater_id: string;
  skater_name: string;
  skater_avatar_type: Skater["avatar_type"];
  skater_avatar_emoji: Skater["avatar_emoji"];
};
type TimelineGroup = {
  key: string;
  title: string;
  subtitle: string | null;
  items: ArchiveTimelineEntry[];
};

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateString));
}

function formatSessionDate(dateString: string | null) {
  if (!dateString) {
    return "未归档课次";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date(dateString));
}

function formatDayKey(dateString: string) {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(new Date(dateString));
}

function forceScoreTone(score: number | null) {
  if (score === null) {
    return "bg-slate-100 text-slate-500";
  }
  if (score >= 80) {
    return "bg-emerald-50 text-emerald-600";
  }
  if (score >= 60) {
    return "bg-amber-50 text-amber-600";
  }
  return "bg-rose-50 text-rose-500";
}

function scoreStars(score: number | null) {
  if (score === null) {
    return "待评分";
  }
  const filled = Math.max(1, Math.min(5, Math.round(score / 20)));
  return `${"★".repeat(filled)}${"☆".repeat(5 - filled)}`;
}

function skaterLabel(skater: Skater) {
  return skater.display_name || skater.name;
}

function buildGroupTitle(entry: ArchiveTimelineEntry) {
  if (!entry.session_id) {
    return formatSessionDate(entry.created_at);
  }
  return formatSessionDate(entry.session_date);
}

function buildGroupSubtitle(entry: ArchiveTimelineEntry) {
  if (!entry.session_id) {
    return null;
  }
  const parts = [entry.session_location, entry.session_type].filter(Boolean) as string[];
  if (entry.session_duration_minutes) {
    parts.push(`${entry.session_duration_minutes} 分钟`);
  }
  return parts.join(" · ") || null;
}

function buildTimelineGroups(timeline: ArchiveTimelineEntry[]): TimelineGroup[] {
  const groups: TimelineGroup[] = [];
  let current: TimelineGroup | null = null;

  timeline.forEach((entry) => {
    const key = entry.session_id ?? `solo-${entry.created_at.slice(0, 10)}-${entry.id}`;
    if (!current || current.key !== key) {
      current = {
        key,
        title: buildGroupTitle(entry),
        subtitle: buildGroupSubtitle(entry),
        items: [],
      };
      groups.push(current);
    }
    current.items.push(entry);
  });

  return groups;
}

function isWithinLastDays(dateString: string, days: number) {
  const start = Date.now() - days * 24 * 60 * 60 * 1000;
  return new Date(dateString).getTime() >= start;
}

function computeCurrentStreak(timeline: ArchiveTimelineEntry[]) {
  if (!timeline.length) {
    return 0;
  }

  const recordedDays = new Set(timeline.map((entry) => formatDayKey(entry.created_at)));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const startDate = recordedDays.has(formatDayKey(today.toISOString()))
    ? today
    : recordedDays.has(formatDayKey(yesterday.toISOString()))
      ? yesterday
      : null;

  if (!startDate) {
    return 0;
  }

  let streak = 0;
  const cursor = new Date(startDate);
  while (recordedDays.has(formatDayKey(cursor.toISOString()))) {
    streak += 1;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}

function computeMonthlySessions(timeline: ArchiveTimelineEntry[]) {
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const sessionKeys = new Set<string>();

  timeline.forEach((entry) => {
    if (new Date(entry.created_at).getTime() < monthStart) {
      return;
    }
    sessionKeys.add(entry.session_id ?? `solo-${entry.id}`);
  });

  return sessionKeys.size;
}

function computeAggregateStats(timeline: ArchiveTimelineEntry[]): ArchiveStats {
  return {
    total_records: timeline.length,
    recent_7days: timeline.filter((entry) => isWithinLastDays(entry.created_at, 7)).length,
    current_streak: computeCurrentStreak(timeline),
    monthly_sessions: computeMonthlySessions(timeline),
  };
}

function annotateTimeline(skater: Skater, archive: ArchiveResponse | null | undefined): ArchiveTimelineEntry[] {
  if (!archive) {
    return [];
  }

  return archive.timeline.map((entry) => ({
    ...entry,
    skater_id: skater.id,
    skater_name: skaterLabel(skater),
    skater_avatar_type: skater.avatar_type,
    skater_avatar_emoji: skater.avatar_emoji,
  }));
}

const actionIconClassName =
  "list-row-action inline-flex rounded-full border text-[20px] leading-none transition disabled:cursor-not-allowed disabled:opacity-50";

export default function ArchivePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isParentMode, childView, pinLength } = useAppMode();
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [archiveBySkaterId, setArchiveBySkaterId] = useState<Record<string, ArchiveResponse>>({});
  const [activeScope, setActiveScope] = useState("");
  const [activeFilter, setActiveFilter] = useState<(typeof FILTER_OPTIONS)[number]>("全部");
  const [parentRange, setParentRange] = useState<ParentRange>("all");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryingAnalysisId, setRetryingAnalysisId] = useState<string | null>(null);
  const [missingVideoRetryIds, setMissingVideoRetryIds] = useState<string[]>([]);
  const [confirmRetryAnalysisId, setConfirmRetryAnalysisId] = useState<string | null>(null);
  const [pinRetryAnalysisId, setPinRetryAnalysisId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const message = (location.state as { notice?: string } | null)?.notice;
    if (!message) {
      return;
    }

    setNotice(message);
    const timer = window.setTimeout(() => setNotice(null), 2400);
    navigate(location.pathname, { replace: true });
    return () => window.clearTimeout(timer);
  }, [location.pathname, location.state, navigate]);

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (cancelled) {
          return;
        }
        setSkaters(data);
        setActiveScope((current) => {
          if (isParentMode) {
            return current || ALL_SKATERS_VIEW;
          }
          return current && current !== ALL_SKATERS_VIEW ? current : pickSkaterIdForChildView(data, childView);
        });
      } catch {
        if (!cancelled) {
          setError("练习档案列表加载失败，请稍后刷新。");
          setIsLoading(false);
        }
      }
    };

    void loadSkaters();
    return () => {
      cancelled = true;
    };
  }, [childView, isParentMode]);

  useEffect(() => {
    if (isParentMode || !skaters.length) {
      return;
    }

    const nextScope = pickSkaterIdForChildView(skaters, childView);
    setActiveScope((current) => (current === nextScope ? current : nextScope));
  }, [childView, isParentMode, skaters]);

  useEffect(() => {
    if (!skaters.length) {
      return;
    }

    const targetSkaterIds = isParentMode
      ? skaters.map((skater) => skater.id)
      : activeScope && activeScope !== ALL_SKATERS_VIEW
        ? [activeScope]
        : [];

    if (!targetSkaterIds.length) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    const loadArchives = async () => {
      setIsLoading(true);
      const results = await Promise.allSettled(targetSkaterIds.map(async (skaterId) => [skaterId, await fetchArchive(skaterId)] as const));

      if (cancelled) {
        return;
      }

      const nextArchives: Record<string, ArchiveResponse> = {};
      let failedCount = 0;

      results.forEach((result) => {
        if (result.status === "fulfilled") {
          const [skaterId, archive] = result.value;
          nextArchives[skaterId] = archive;
        } else {
          failedCount += 1;
        }
      });

      setArchiveBySkaterId((current) => ({ ...current, ...nextArchives }));
      setError(
        failedCount
          ? failedCount === targetSkaterIds.length
            ? "练习档案时间轴加载失败，请稍后重试。"
            : "部分练习档案加载失败，请稍后重试。"
          : null,
      );
      setIsLoading(false);
    };

    void loadArchives();
    return () => {
      cancelled = true;
    };
  }, [activeScope, isParentMode, skaters]);

  const allTimelineEntries = useMemo(
    () =>
      skaters
        .flatMap((skater) => annotateTimeline(skater, archiveBySkaterId[skater.id]))
        .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()),
    [archiveBySkaterId, skaters],
  );

  const selectedSkater =
    activeScope && activeScope !== ALL_SKATERS_VIEW ? skaters.find((skater) => skater.id === activeScope) ?? null : null;

  const activeTimeline = useMemo(() => {
    if (isParentMode && activeScope === ALL_SKATERS_VIEW) {
      return allTimelineEntries;
    }
    if (!selectedSkater) {
      return [];
    }
    return annotateTimeline(selectedSkater, archiveBySkaterId[selectedSkater.id]).sort(
      (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
    );
  }, [activeScope, allTimelineEntries, archiveBySkaterId, isParentMode, selectedSkater]);

  const confirmRetryEntry = allTimelineEntries.find((entry) => entry.analysis_id === confirmRetryAnalysisId) ?? null;
  const pinRetryEntry = allTimelineEntries.find((entry) => entry.analysis_id === pinRetryAnalysisId) ?? null;

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const filteredTimeline = useMemo(() => {
    const range = RANGE_OPTIONS.find((option) => option.value === parentRange) ?? RANGE_OPTIONS[2];
    return activeTimeline.filter((entry) => {
      if (activeFilter !== "全部" && entry.action_type !== activeFilter) {
        return false;
      }
      if (isParentMode && range.days !== null && !isWithinLastDays(entry.created_at, range.days)) {
        return false;
      }
      return true;
    });
  }, [activeFilter, activeTimeline, isParentMode, parentRange]);

  const timelineGroups = useMemo(() => buildTimelineGroups(filteredTimeline), [filteredTimeline]);

  const activeStats = useMemo<ArchiveStats>(() => {
    if (isParentMode && activeScope === ALL_SKATERS_VIEW) {
      return computeAggregateStats(allTimelineEntries);
    }
    if (selectedSkater) {
      return archiveBySkaterId[selectedSkater.id]?.stats ?? computeAggregateStats(activeTimeline);
    }
    return computeAggregateStats(activeTimeline);
  }, [activeScope, activeTimeline, allTimelineEntries, archiveBySkaterId, isParentMode, selectedSkater]);

  const markAnalysisAsProcessing = (analysisId: string, skaterId: string) => {
    setArchiveBySkaterId((current) => {
      const currentArchive = current[skaterId];
      if (!currentArchive) {
        return current;
      }

      return {
        ...current,
        [skaterId]: {
          ...currentArchive,
          timeline: currentArchive.timeline.map((entry) =>
            entry.analysis_id === analysisId
              ? {
                  ...entry,
                  status: "processing",
                }
              : entry,
          ),
        },
      };
    });
  };

  const handleRetryEntry = async (entry: ArchiveTimelineEntry) => {
    setRetryingAnalysisId(entry.analysis_id);
    setError(null);
    try {
      await retryAnalysis(entry.analysis_id);
      markAnalysisAsProcessing(entry.analysis_id, entry.skater_id);
      setMissingVideoRetryIds((current) => current.filter((id) => id !== entry.analysis_id));
      showNotice("已重新提交，请稍候");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        if (requestError.response?.status === 404) {
          setMissingVideoRetryIds((current) =>
            current.includes(entry.analysis_id) ? current : [...current, entry.analysis_id],
          );
          showNotice('原始视频已清理，请点击"重新上传"');
          return;
        }
        setError(String(requestError.response?.data?.detail ?? "重新分析失败，请稍后重试。"));
      } else {
        setError("重新分析失败，请稍后重试。");
      }
    } finally {
      setRetryingAnalysisId(null);
    }
  };

  const requestReanalysis = (entry: ArchiveTimelineEntry) => {
    if (retryingAnalysisId === entry.analysis_id) {
      return;
    }

    if (isParentMode) {
      setConfirmRetryAnalysisId(entry.analysis_id);
      return;
    }

    setPinRetryAnalysisId(entry.analysis_id);
  };

  const handleVerifiedRetry = () => {
    if (!pinRetryEntry) {
      return;
    }
    setPinRetryAnalysisId(null);
    setConfirmRetryAnalysisId(pinRetryEntry.analysis_id);
  };

  const viewOptions = useMemo(
    () => [
      { id: ALL_SKATERS_VIEW, label: "全部" },
      ...skaters.map((skater) => ({ id: skater.id, label: skaterLabel(skater) })),
    ],
    [skaters],
  );

  const renderStatsGrid = (
    <section className="grid gap-4 phone:grid-cols-2 web:grid-cols-4">
      <div className="app-card p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">累计档案</p>
        <p className="mt-3 text-3xl font-semibold text-slate-900">{activeStats.total_records}</p>
        <p className="mt-2 text-sm text-slate-500">总记录数</p>
      </div>
      <div className="app-card p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">近 7 天</p>
        <p className="mt-3 text-3xl font-semibold text-slate-900">{activeStats.recent_7days}</p>
        <p className="mt-2 text-sm text-slate-500">最近一周训练次数</p>
      </div>
      <div className="app-card p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">连续记录</p>
        <p className="mt-3 text-3xl font-semibold text-slate-900">{activeStats.current_streak}</p>
        <p className="mt-2 text-sm text-slate-500">按自然日连续记录</p>
      </div>
      <div className="app-card p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">本月课次</p>
        <p className="mt-3 text-3xl font-semibold text-slate-900">{activeStats.monthly_sessions}</p>
        <p className="mt-2 text-sm text-slate-500">已登记训练课次</p>
      </div>
    </section>
  );

  const renderFiltersCard = (
    <section className="app-card p-6">
      <div className="flex flex-col gap-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">动作筛选</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {FILTER_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setActiveFilter(option)}
                className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
                  activeFilter === option ? "bg-blue-500 text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        {isParentMode ? (
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">时间范围</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {RANGE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setParentRange(option.value)}
                  className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
                    parentRange === option.value ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );

  return (
    <div className="space-y-6">
      <section className="app-card overflow-hidden p-6 tablet:p-8">
        <div className="flex flex-col gap-5 tablet:flex-row tablet:items-end tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">
              {isParentMode ? "Progress" : "Archive"}
            </p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">
              {isParentMode ? "训练进展总览" : "练习档案时间轴"}
            </h1>
            <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">
              {isParentMode
                ? "家长模式下可在两个孩子与家庭总览之间切换，统一查看课次归档、AI 评分与训练记录。"
                : "把每次视频复盘沉淀成连续可追踪的成长记录。这里会保留冰宝（IceBuddy）诊断、评分变化和课次归档关系。"}
            </p>
          </div>

          {isParentMode ? (
            <div className="min-w-[280px]">
              <p className="text-sm font-medium text-slate-700">查看对象</p>
              <div className="mt-3 flex flex-wrap justify-start gap-2 tablet:justify-end">
                {viewOptions.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setActiveScope(option.id)}
                    className={`min-h-[44px] rounded-full px-4 text-sm font-medium transition ${
                      activeScope === option.id
                        ? "bg-blue-500 text-white"
                        : "border border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-600"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <label className="block min-w-[220px] space-y-2">
              <span className="text-sm font-medium text-slate-700">当前练习档案</span>
              <select value={activeScope} onChange={(event) => setActiveScope(event.target.value)} className="app-select">
                {skaters.map((skater) => (
                  <option key={skater.id} value={skater.id}>
                    {skaterLabel(skater)}
                    {skater.level ? ` · ${skater.level}` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </section>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      {isParentMode ? renderStatsGrid : null}

      <div className="grid gap-6 web:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-6">
          {isParentMode ? (
            <section className="app-card p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">
                {activeScope === ALL_SKATERS_VIEW ? "家庭总览" : "当前对象"}
              </p>
              {activeScope === ALL_SKATERS_VIEW ? (
                <div className="mt-4 space-y-4 rounded-[28px] bg-slate-50 p-5">
                  <div>
                    <h2 className="text-xl font-semibold text-slate-900">坦坦 / 昭昭 进展总览</h2>
                    <p className="mt-2 text-sm leading-6 text-slate-500">可统一浏览两个孩子的训练时间轴，并保留每条记录的孩子标识与 AI 评分。</p>
                  </div>
                  <div className="space-y-3">
                    {skaters.map((skater) => (
                      <button
                        key={skater.id}
                        type="button"
                        onClick={() => setActiveScope(skater.id)}
                        className="flex w-full items-center justify-between rounded-[22px] border border-white bg-white px-4 py-3 text-left transition hover:border-blue-200 hover:bg-blue-50/40"
                      >
                        <div className="flex items-center gap-3">
                          <ZodiacAvatar avatarType={skater.avatar_type} avatarEmoji={skater.avatar_emoji} size="sm" />
                          <div>
                            <p className="font-medium text-slate-900">{skaterLabel(skater)}</p>
                            <p className="text-sm text-slate-500">XP {skater.total_xp} · 连续 {skater.current_streak} 天</p>
                          </div>
                        </div>
                        <span className="text-sm font-medium text-blue-600">查看进展</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : selectedSkater ? (
                <div className="mt-4 rounded-[28px] bg-slate-50 p-5">
                  <ZodiacAvatar
                    avatarType={selectedSkater.avatar_type}
                    avatarEmoji={selectedSkater.avatar_emoji}
                    size="lg"
                    className="mx-auto tablet:mx-0"
                  />
                  <h2 className="mt-3 text-xl font-semibold text-slate-900">{skaterLabel(selectedSkater)}</h2>
                  <p className="mt-2 text-sm text-slate-500">{selectedSkater.level ?? selectedSkater.current_level}</p>
                  <p className="mt-4 text-sm text-slate-500">当前 XP：{selectedSkater.total_xp}</p>
                  <p className="mt-2 text-sm text-slate-500">连续记录：{selectedSkater.current_streak} 天</p>
                </div>
              ) : null}
            </section>
          ) : selectedSkater ? (
            <>
              <section className="app-card p-6">
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">当前对象</p>
                <div className="mt-4 rounded-[28px] bg-slate-50 p-5">
                  <ZodiacAvatar
                    avatarType={selectedSkater.avatar_type}
                    avatarEmoji={selectedSkater.avatar_emoji}
                    size="lg"
                    className="mx-auto tablet:mx-0"
                  />
                  <h2 className="mt-3 text-xl font-semibold text-slate-900">{skaterLabel(selectedSkater)}</h2>
                  <p className="mt-2 text-sm text-slate-500">{selectedSkater.level ?? selectedSkater.current_level}</p>
                  <p className="mt-4 text-sm text-slate-500">当前 XP：{selectedSkater.total_xp}</p>
                  <p className="mt-2 text-sm text-slate-500">连续记录：{selectedSkater.current_streak} 天</p>
                </div>
              </section>

              {renderStatsGrid}
            </>
          ) : null}

          {renderFiltersCard}
        </div>

        <section className="app-card p-6 tablet:p-7">
          <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Timeline</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">{isParentMode ? "进展记录" : "复盘记录"}</h2>
              {isParentMode ? (
                <p className="mt-3 text-sm leading-6 text-slate-500">
                  {activeScope === ALL_SKATERS_VIEW
                    ? "已按训练课次自动归组，支持在家庭总览中查看两个孩子的完整时间轴。"
                    : "已按训练课次自动归组，可结合 AI 评分回看阶段性变化。"}
                </p>
              ) : null}
            </div>
            <span className="w-fit rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">{filteredTimeline.length} 条</span>
          </div>

          {isLoading ? (
            <div className="mt-6 rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">正在加载练习档案...</div>
          ) : timelineGroups.length ? (
            <div className="mt-6 space-y-7">
              {timelineGroups.map((group) => (
                <section key={group.key} className="space-y-4">
                  <div className="border-b border-slate-200 pb-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <h3 className="text-lg font-semibold text-slate-900">{group.title}</h3>
                      {group.subtitle ? <span className="text-sm text-slate-500">{group.subtitle}</span> : null}
                    </div>
                  </div>

                  <div className="space-y-4">
                    {group.items.map((entry, index) => {
                      const isRetrying = retryingAnalysisId === entry.analysis_id;
                      const hideRetry = missingVideoRetryIds.includes(entry.analysis_id);

                      return (
                        <article key={entry.id} className="content-visibility-auto relative pl-8">
                          {index < group.items.length - 1 ? (
                            <div className="absolute left-3 top-10 h-[calc(100%-1rem)] w-px bg-gradient-to-b from-blue-200 to-slate-100" />
                          ) : null}
                          <div className="absolute left-0 top-7 flex h-6 w-6 items-center justify-center rounded-full bg-blue-50 text-sm">⛸️</div>

                          <div className="list-row rounded-[28px] border border-slate-200 bg-white p-5">
                            <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
                              <div>
                                <div className="flex flex-wrap items-center gap-2">
                                  {isParentMode && activeScope === ALL_SKATERS_VIEW ? (
                                    <span className="rounded-full bg-violet-50 px-3 py-1 text-sm text-violet-600">{entry.skater_name}</span>
                                  ) : null}
                                  <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{entry.entry_type}</span>
                                  <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{entry.action_type}</span>
                                  {entry.skill_category ? (
                                    <span className="rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-600">{entry.skill_category}</span>
                                  ) : null}
                                  <span className={`rounded-full px-3 py-1 text-sm ${forceScoreTone(entry.force_score)}`}>
                                    {isParentMode ? `AI 评分 ${entry.force_score ?? "--"}` : `星级 ${scoreStars(entry.force_score)}`}
                                  </span>
                                </div>
                                <p className="mt-3 text-sm text-slate-400">{formatDate(entry.created_at)}</p>
                                <p className="mt-4 max-w-3xl leading-7 text-slate-600">{entry.report_snippet}</p>
                              </div>

                              <div className="flex flex-col gap-3 tablet:items-end">
                                <div className="flex items-center gap-2 pr-2">
                                  {entry.status === "completed" ? (
                                    <>
                                      <Link
                                        to={`/report/${entry.analysis_id}`}
                                        title="查看分析报告"
                                        aria-label="查看分析报告"
                                        className={`${actionIconClassName} border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100`}
                                      >
                                        📄
                                      </Link>
                                      <button
                                        type="button"
                                        onClick={() => requestReanalysis(entry)}
                                        disabled={isRetrying}
                                        title="再次分析"
                                        aria-label="再次分析"
                                        className={`${actionIconClassName} border-orange-200 bg-orange-50 text-orange-600 hover:bg-orange-100`}
                                      >
                                        {isRetrying ? "…" : "🔄"}
                                      </button>
                                    </>
                                  ) : null}

                                  {isAnalysisInProgress(entry.status) ? (
                                    <span
                                      title="分析进行中"
                                      aria-label="分析进行中"
                                      className={`${actionIconClassName} cursor-default border-blue-100 bg-blue-50 text-blue-500`}
                                    >
                                      ⏳
                                    </span>
                                  ) : null}

                                  {entry.status === "failed" && !hideRetry ? (
                                    <button
                                      type="button"
                                      onClick={() => void handleRetryEntry(entry)}
                                      disabled={isRetrying}
                                      title="分析失败，点击重试"
                                      aria-label="分析失败，点击重试"
                                      className={`${actionIconClassName} border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100`}
                                    >
                                      {isRetrying ? "…" : "❌"}
                                    </button>
                                  ) : null}
                                </div>

                                <div className="flex flex-wrap gap-3 tablet:justify-end">
                                  {entry.status === "failed" && hideRetry ? (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        navigate("/review", {
                                          state: entry.skater_id ? { skaterId: entry.skater_id } : undefined,
                                        })
                                      }
                                      className="list-row-action inline-flex min-w-[44px] rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
                                    >
                                      📤 重新上传
                                    </button>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <div className="mt-6 rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">当前筛选下还没有复盘记录，先去上传一段训练视频吧。</div>
          )}
        </section>
      </div>

      {pinRetryEntry ? (
        <ParentPinVerifyModal
          pinLength={pinLength}
          title="输入家长 PIN"
          description="验证通过后才能重新分析这个视频。"
          confirmLabel="继续"
          onClose={() => setPinRetryAnalysisId(null)}
          onVerified={handleVerifiedRetry}
        />
      ) : null}

      {confirmRetryEntry ? (
        <RetryAnalysisConfirmSheet
          isSubmitting={retryingAnalysisId === confirmRetryEntry.analysis_id}
          onClose={() => {
            if (retryingAnalysisId !== confirmRetryEntry.analysis_id) {
              setConfirmRetryAnalysisId(null);
            }
          }}
          onConfirm={() =>
            void (async () => {
              await handleRetryEntry(confirmRetryEntry);
              setConfirmRetryAnalysisId(null);
            })()
          }
        />
      ) : null}
    </div>
  );
}
