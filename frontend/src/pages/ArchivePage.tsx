import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import axios from "axios";

import { ArchiveResponse, fetchArchive, fetchSkaters, retryAnalysis, Skater } from "../api/client";
import { useAppMode } from "../components/AppModeContext";
import ParentPinVerifyModal from "../components/ParentPinVerifyModal";
import RetryAnalysisConfirmSheet from "../components/RetryAnalysisConfirmSheet";
import { isAnalysisInProgress } from "../constants/analysisStatus";
import { pickSkaterIdForChildView } from "../utils/childView";
import { localDateKey, parseApiDate } from "../utils/datetime";

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;
const RANGE_OPTIONS = [
  { value: "7d", label: "近 7 天", days: 7 },
  { value: "30d", label: "近 30 天", days: 30 },
  { value: "all", label: "全部", days: null },
] as const;
const ALL_SKATERS_VIEW = "__all__";
const ARCHIVE_PAGE_SIZE = 24;
const TIMELINE_PAGE_SIZE = 12;
const WEEKDAY_LABELS = ["日", "一", "二", "三", "四", "五", "六"] as const;

type ParentRange = (typeof RANGE_OPTIONS)[number]["value"];
type ArchiveViewTab = "timeline" | "calendar";
type ArchiveStats = ArchiveResponse["stats"];
type ArchiveTimelineEntry = ArchiveResponse["timeline"][number] & {
  skater_id: string;
  skater_name: string;
  skater_avatar_type: Skater["avatar_type"];
  skater_avatar_emoji: Skater["avatar_emoji"];
};
type CalendarDay = {
  key: string;
  date: Date;
  isCurrentMonth: boolean;
  entries: ArchiveTimelineEntry[];
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
  }).format(parseApiDate(dateString));
}

function formatSessionDate(dateString: string | null) {
  if (!dateString) {
    return "未归档课次";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(parseApiDate(dateString));
}

function formatDayKey(dateString: string) {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Shanghai",
  }).format(parseApiDate(dateString));
}

function formatMonthTitle(date: Date) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
  }).format(date);
}

function shiftMonth(date: Date, delta: number) {
  return new Date(date.getFullYear(), date.getMonth() + delta, 1);
}

function buildCalendarDays(anchorDate: Date, timeline: ArchiveTimelineEntry[]): CalendarDay[] {
  const monthStart = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1);
  const gridStart = new Date(monthStart);
  gridStart.setDate(monthStart.getDate() - monthStart.getDay());

  const entriesByDay = new Map<string, ArchiveTimelineEntry[]>();
  timeline.forEach((entry) => {
    const key = formatDayKey(entry.created_at);
    const entries = entriesByDay.get(key) ?? [];
    entries.push(entry);
    entriesByDay.set(key, entries);
  });

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + index);
    const key = localDateKey(date);
    return {
      key,
      date,
      isCurrentMonth: date.getMonth() === anchorDate.getMonth(),
      entries: entriesByDay.get(key) ?? [],
    };
  });
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
    const key = entry.session_id ?? `solo-${formatDayKey(entry.created_at)}-${entry.id}`;
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
  return parseApiDate(dateString).getTime() >= start;
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
  const startDate = recordedDays.has(localDateKey(today))
    ? today
    : recordedDays.has(localDateKey(yesterday))
      ? yesterday
      : null;

  if (!startDate) {
    return 0;
  }

  let streak = 0;
  const cursor = new Date(startDate);
  while (recordedDays.has(localDateKey(cursor))) {
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
    if (parseApiDate(entry.created_at).getTime() < monthStart) {
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
  "list-row-action inline-flex shrink-0 rounded-full border text-[20px] leading-none transition disabled:cursor-not-allowed disabled:opacity-50";

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
  const [loadingMoreSkaterIds, setLoadingMoreSkaterIds] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<ArchiveViewTab>("timeline");
  const [timelinePage, setTimelinePage] = useState(1);
  const [calendarMonth, setCalendarMonth] = useState(() => {
    const today = new Date();
    return new Date(today.getFullYear(), today.getMonth(), 1);
  });

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
      const results = await Promise.allSettled(
        targetSkaterIds.map(async (skaterId) => [skaterId, await fetchArchive(skaterId, { limit: ARCHIVE_PAGE_SIZE, offset: 0 })] as const),
      );

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
        .sort((left, right) => parseApiDate(right.created_at).getTime() - parseApiDate(left.created_at).getTime()),
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
      (left, right) => parseApiDate(right.created_at).getTime() - parseApiDate(left.created_at).getTime(),
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

  useEffect(() => {
    setTimelinePage(1);
  }, [activeFilter, activeScope, parentRange]);

  useEffect(() => {
    if (filteredTimeline.length) {
      const latestEntryDate = parseApiDate(filteredTimeline[0].created_at);
      setCalendarMonth(new Date(latestEntryDate.getFullYear(), latestEntryDate.getMonth(), 1));
    }
  }, [activeFilter, activeScope, filteredTimeline, parentRange]);

  const totalTimelinePages = Math.max(1, Math.ceil(filteredTimeline.length / TIMELINE_PAGE_SIZE));

  useEffect(() => {
    setTimelinePage((current) => Math.min(current, totalTimelinePages));
  }, [totalTimelinePages]);

  const pagedTimeline = useMemo(() => {
    const start = (timelinePage - 1) * TIMELINE_PAGE_SIZE;
    return filteredTimeline.slice(start, start + TIMELINE_PAGE_SIZE);
  }, [filteredTimeline, timelinePage]);

  const timelineGroups = useMemo(() => buildTimelineGroups(pagedTimeline), [pagedTimeline]);
  const calendarDays = useMemo(() => buildCalendarDays(calendarMonth, filteredTimeline), [calendarMonth, filteredTimeline]);
  const calendarMonthEntries = useMemo(
    () =>
      filteredTimeline.filter((entry) => {
        const entryDate = parseApiDate(entry.created_at);
        return entryDate.getFullYear() === calendarMonth.getFullYear() && entryDate.getMonth() === calendarMonth.getMonth();
      }),
    [calendarMonth, filteredTimeline],
  );
  const loadedRecordCount = filteredTimeline.length;
  const pageStartIndex = loadedRecordCount ? (timelinePage - 1) * TIMELINE_PAGE_SIZE + 1 : 0;
  const pageEndIndex = Math.min(timelinePage * TIMELINE_PAGE_SIZE, loadedRecordCount);

  const activeStats = useMemo<ArchiveStats>(() => {
    if (isParentMode && activeScope === ALL_SKATERS_VIEW) {
      return skaters.reduce<ArchiveStats>(
        (stats, skater) => {
          const archive = archiveBySkaterId[skater.id];
          if (!archive) {
            return stats;
          }
          return {
            total_records: stats.total_records + archive.stats.total_records,
            recent_7days: stats.recent_7days + archive.stats.recent_7days,
            current_streak: Math.max(stats.current_streak, archive.stats.current_streak),
            monthly_sessions: stats.monthly_sessions + archive.stats.monthly_sessions,
          };
        },
        { total_records: 0, recent_7days: 0, current_streak: 0, monthly_sessions: 0 },
      );
    }
    if (selectedSkater) {
      return archiveBySkaterId[selectedSkater.id]?.stats ?? computeAggregateStats(activeTimeline);
    }
    return computeAggregateStats(activeTimeline);
  }, [activeScope, activeTimeline, archiveBySkaterId, isParentMode, selectedSkater, skaters]);

  const skaterIdsNeedingMore = useMemo(() => {
    if (isParentMode && activeScope === ALL_SKATERS_VIEW) {
      return skaters
        .map((skater) => skater.id)
        .filter((skaterId) => Boolean(archiveBySkaterId[skaterId]?.has_more));
    }
    if (selectedSkater && archiveBySkaterId[selectedSkater.id]?.has_more) {
      return [selectedSkater.id];
    }
    return [];
  }, [activeScope, archiveBySkaterId, isParentMode, selectedSkater, skaters]);

  const isLoadingMore = skaterIdsNeedingMore.some((skaterId) => loadingMoreSkaterIds.includes(skaterId));

  const mergeArchivePage = (currentArchive: ArchiveResponse | undefined, nextArchive: ArchiveResponse): ArchiveResponse => {
    if (!currentArchive || (nextArchive.offset ?? 0) === 0) {
      return nextArchive;
    }

    const existingIds = new Set(currentArchive.timeline.map((entry) => entry.id));
    const appended = nextArchive.timeline.filter((entry) => !existingIds.has(entry.id));
    return {
      ...nextArchive,
      timeline: [...currentArchive.timeline, ...appended],
    };
  };

  const handleLoadMore = async (advancePage = false) => {
    if (!skaterIdsNeedingMore.length || isLoadingMore) {
      return;
    }

    const requestedSkaterIds = [...skaterIdsNeedingMore];
    setLoadingMoreSkaterIds((current) => [...new Set([...current, ...requestedSkaterIds])]);
    setError(null);

    const results = await Promise.allSettled(
      requestedSkaterIds.map(async (skaterId) => {
        const currentArchive = archiveBySkaterId[skaterId];
        const offset = currentArchive?.timeline.length ?? 0;
        return [skaterId, await fetchArchive(skaterId, { limit: ARCHIVE_PAGE_SIZE, offset })] as const;
      }),
    );

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

    setArchiveBySkaterId((current) => {
      const merged = { ...current };
      Object.entries(nextArchives).forEach(([skaterId, archive]) => {
        merged[skaterId] = mergeArchivePage(current[skaterId], archive);
      });
      return merged;
    });
    setLoadingMoreSkaterIds((current) => current.filter((skaterId) => !requestedSkaterIds.includes(skaterId)));
    if (!failedCount && advancePage) {
      setTimelinePage((current) => current + 1);
    }
    if (failedCount) {
      setError("更多练习档案加载失败，请稍后重试。");
    }
  };

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
      await retryAnalysis(entry.analysis_id, { resetTargetLock: true });
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

  const renderTimelineEntry = (entry: ArchiveTimelineEntry, index: number, groupLength: number) => {
    const isRetrying = retryingAnalysisId === entry.analysis_id;
    const hideRetry = missingVideoRetryIds.includes(entry.analysis_id);

    return (
      <article key={entry.id} className="content-visibility-auto relative min-w-0 pl-7 phone:pl-8">
        {index < groupLength - 1 ? (
          <div className="absolute left-3 top-10 h-[calc(100%-1rem)] w-px bg-gradient-to-b from-blue-200 to-slate-100" />
        ) : null}
        <div className="absolute left-0 top-7 flex h-6 w-6 items-center justify-center rounded-full bg-blue-50 text-sm">⛸️</div>

        <div className="list-row min-w-0 max-w-full rounded-[20px] border border-slate-200 bg-white p-3 phone:p-4 tablet:p-5">
          <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                {isParentMode && activeScope === ALL_SKATERS_VIEW ? (
                  <span className="max-w-full break-words rounded-full bg-violet-50 px-3 py-1 text-sm text-violet-600">{entry.skater_name}</span>
                ) : null}
                <span className="max-w-full break-words rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{entry.entry_type}</span>
                <span className="max-w-full break-words rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{entry.action_type}</span>
                {entry.skill_category ? (
                  <span className="max-w-full break-words rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-600">{entry.skill_category}</span>
                ) : null}
                <span className={`max-w-full break-words rounded-full px-3 py-1 text-sm ${forceScoreTone(entry.force_score)}`}>
                  {isParentMode ? `AI 评分 ${entry.force_score ?? "--"}` : `星级 ${scoreStars(entry.force_score)}`}
                </span>
              </div>
              <p className="mt-3 text-sm text-slate-400">{formatDate(entry.created_at)}</p>
              <p className="mt-3 max-w-3xl whitespace-normal break-words leading-7 text-slate-600">{entry.report_snippet}</p>
            </div>

            <div className="flex min-w-0 flex-col gap-3 tablet:items-end">
              <div className="flex flex-wrap items-center gap-2 pr-0 tablet:justify-end tablet:pr-2">
                {entry.status === "completed" || entry.status === "failed" ? (
                  <Link
                    to={`/report/${entry.analysis_id}`}
                    title="查看分析报告"
                    aria-label="查看分析报告"
                    className={`${actionIconClassName} border-blue-200 bg-blue-50 text-blue-600 hover:bg-blue-100`}
                  >
                    📄
                  </Link>
                ) : null}

                {entry.status === "completed" ? (
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
                ) : null}

                {isAnalysisInProgress(entry.status) ? (
                  <Link
                    to={`/report/${entry.analysis_id}`}
                    title="分析进行中"
                    aria-label="分析进行中"
                    className={`${actionIconClassName} border-blue-100 bg-blue-50 text-blue-500 hover:bg-blue-100`}
                  >
                    ⏳
                  </Link>
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
      </article>
    );
  };

  const statItems = [
    { label: "累计档案", value: activeStats.total_records, hint: "总记录" },
    { label: "近 7 天", value: activeStats.recent_7days, hint: "训练次数" },
    { label: "连续记录", value: activeStats.current_streak, hint: "自然日" },
    { label: "本月课次", value: activeStats.monthly_sessions, hint: "已归档" },
  ];

  const renderStatsGrid = (
    <section className="app-card p-3 phone:p-4">
      <div className="grid gap-2 phone:grid-cols-2 tablet:grid-cols-4">
        {statItems.map((item) => (
          <div key={item.label} className="min-w-0 rounded-[18px] bg-slate-50 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">{item.label}</p>
            <div className="mt-2 flex items-end gap-2">
              <p className="text-2xl font-semibold leading-none text-slate-900 tablet:text-3xl">{item.value}</p>
              <p className="pb-0.5 text-xs text-slate-500">{item.hint}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );

  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-8">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">
            {isParentMode ? "Progress" : "Archive"}
          </p>
          <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">
            {isParentMode ? "训练进展总览" : "练习档案时间轴"}
          </h1>
          <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">
            {isParentMode
              ? "按对象、动作和时间快速定位训练记录，也可以切到日历视图查看训练分布。"
              : "把每次视频复盘沉淀成连续可追踪的成长记录。这里会保留冰宝（IceBuddy）诊断、评分变化和课次归档关系。"}
          </p>
        </div>
      </section>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      {renderStatsGrid}

      <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-7">
        <div className="grid gap-5">
          <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Archive</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">{isParentMode ? "进展记录" : "复盘记录"}</h2>
              <p className="mt-3 text-sm leading-6 text-slate-500">
                每页显示 {TIMELINE_PAGE_SIZE} 条，按需继续加载历史记录；日历视图可快速看到训练分布。
              </p>
            </div>
            <span className="w-fit rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">
              已加载 {loadedRecordCount}/{activeStats.total_records} 条
            </span>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-3 phone:p-4">
            <div className="grid gap-4 web:grid-cols-[minmax(0,1.1fr)_minmax(0,1.25fr)_auto] web:items-end">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">查看对象</p>
                {isParentMode ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {viewOptions.map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => setActiveScope(option.id)}
                        className={`min-h-[40px] rounded-full px-4 text-sm font-medium transition ${
                          activeScope === option.id
                            ? "bg-blue-500 text-white"
                            : "border border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-600"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                ) : (
                  <select value={activeScope} onChange={(event) => setActiveScope(event.target.value)} className="app-select mt-3">
                    {skaters.map((skater) => (
                      <option key={skater.id} value={skater.id}>
                        {skaterLabel(skater)}
                        {skater.level ? ` · ${skater.level}` : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">动作筛选</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {FILTER_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setActiveFilter(option)}
                      className={`min-h-[40px] rounded-full px-4 text-sm font-medium transition ${
                        activeFilter === option ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100"
                      }`}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>

              {isParentMode ? (
                <div className="min-w-0 web:min-w-[220px]">
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">时间范围</p>
                  <div className="mt-3 flex flex-wrap gap-2 web:justify-end">
                    {RANGE_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setParentRange(option.value)}
                        className={`min-h-[40px] rounded-full px-4 text-sm font-medium transition ${
                          parentRange === option.value ? "bg-blue-500 text-white" : "bg-white text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>

            <div className="mt-4 flex flex-col gap-3 border-t border-slate-200 pt-4 tablet:flex-row tablet:items-center tablet:justify-between">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">
                  {activeScope === ALL_SKATERS_VIEW ? "全部对象" : selectedSkater ? skaterLabel(selectedSkater) : "当前对象"}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {activeFilter} · {isParentMode ? RANGE_OPTIONS.find((option) => option.value === parentRange)?.label : "全部时间"}
                </p>
              </div>
              <div className="flex w-full rounded-full bg-white p-1 tablet:w-auto">
                {[
                  { id: "timeline" as const, label: "列表" },
                  { id: "calendar" as const, label: "日历" },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setActiveTab(tab.id)}
                    className={`min-h-[40px] flex-1 rounded-full px-4 text-sm font-semibold transition tablet:flex-none ${
                      activeTab === tab.id ? "bg-slate-900 text-white shadow-sm" : "text-slate-500 hover:text-slate-700"
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {isLoading ? (
          <div className="mt-6 rounded-[24px] bg-slate-50 px-5 py-6 text-sm text-slate-500">正在加载练习档案...</div>
        ) : activeTab === "timeline" ? (
          timelineGroups.length ? (
            <div className="mt-6 space-y-6">
              <div className="flex flex-col gap-3 rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500 tablet:flex-row tablet:items-center tablet:justify-between">
                <span>
                  第 {timelinePage}/{totalTimelinePages} 页 · 显示 {pageStartIndex}-{pageEndIndex} 条
                </span>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setTimelinePage((current) => Math.max(1, current - 1))}
                    disabled={timelinePage === 1}
                    className="min-h-[40px] rounded-full border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (timelinePage < totalTimelinePages) {
                        setTimelinePage((current) => current + 1);
                        return;
                      }
                      void handleLoadMore(true);
                    }}
                    disabled={isLoadingMore || (timelinePage >= totalTimelinePages && !skaterIdsNeedingMore.length)}
                    className="min-h-[40px] rounded-full bg-slate-900 px-4 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isLoadingMore ? "加载中..." : timelinePage < totalTimelinePages ? "下一页" : "加载下一批"}
                  </button>
                </div>
              </div>

              {timelineGroups.map((group) => (
                <section key={group.key} className="space-y-4">
                  <div className="border-b border-slate-200 pb-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <h3 className="text-lg font-semibold text-slate-900">{group.title}</h3>
                      {group.subtitle ? <span className="text-sm text-slate-500">{group.subtitle}</span> : null}
                    </div>
                  </div>

                  <div className="space-y-4">
                    {group.items.map((entry, index) => renderTimelineEntry(entry, index, group.items.length))}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <div className="mt-6 rounded-[24px] bg-slate-50 px-5 py-6 text-sm text-slate-500">当前筛选下还没有复盘记录，先去上传一段训练视频吧。</div>
          )
        ) : (
          <div className="mt-6 grid min-w-0 gap-6 wide:grid-cols-[minmax(0,1fr)_360px]">
            <div className="min-w-0 rounded-[24px] border border-slate-200 bg-slate-50 p-3 phone:p-4">
              <div className="mb-4 flex flex-col gap-3 phone:flex-row phone:items-center phone:justify-between">
                <h3 className="text-xl font-semibold text-slate-900">{formatMonthTitle(calendarMonth)}</h3>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setCalendarMonth((current) => shiftMonth(current, -1))}
                    className="min-h-[40px] rounded-full border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
                  >
                    上月
                  </button>
                  <button
                    type="button"
                    onClick={() => setCalendarMonth((current) => shiftMonth(current, 1))}
                    className="min-h-[40px] rounded-full border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 transition hover:bg-slate-50"
                  >
                    下月
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-7 gap-1 text-center text-xs font-semibold text-slate-400">
                {WEEKDAY_LABELS.map((label) => (
                  <span key={label} className="py-2">
                    {label}
                  </span>
                ))}
              </div>
              <div className="grid grid-cols-7 gap-1">
                {calendarDays.map((day) => (
                  <div
                    key={day.key}
                    className={`min-h-[66px] rounded-[16px] border p-2 text-left tablet:min-h-[92px] ${
                      day.isCurrentMonth ? "border-slate-200 bg-white" : "border-transparent bg-white/50 text-slate-300"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-sm font-semibold">{day.date.getDate()}</span>
                      {day.entries.length ? (
                        <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-600">{day.entries.length}</span>
                      ) : null}
                    </div>
                    {day.entries.length ? (
                      <div className="mt-2 hidden space-y-1 tablet:block">
                        {day.entries.slice(0, 2).map((entry) => (
                          <Link
                            key={entry.id}
                            to={`/report/${entry.analysis_id}`}
                            className="block truncate rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600 hover:bg-blue-50 hover:text-blue-600"
                          >
                            {isParentMode && activeScope === ALL_SKATERS_VIEW ? `${entry.skater_name} · ` : ""}
                            {entry.action_type}
                          </Link>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>

            <aside className="min-w-0 rounded-[24px] border border-slate-200 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-blue-500">Month</p>
                  <h3 className="mt-2 text-lg font-semibold text-slate-900">本月记录</h3>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">{calendarMonthEntries.length} 条</span>
              </div>
              {calendarMonthEntries.length ? (
                <div className="mt-4 space-y-3">
                  {calendarMonthEntries.slice(0, 8).map((entry) => (
                    <Link
                      key={entry.id}
                      to={`/report/${entry.analysis_id}`}
                      className="block rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3 transition hover:border-blue-200 hover:bg-blue-50/50"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="truncate text-sm font-semibold text-slate-900">{entry.action_type}</p>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${forceScoreTone(entry.force_score)}`}>
                          {entry.force_score ?? "--"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-400">{formatDate(entry.created_at)}</p>
                      {isParentMode && activeScope === ALL_SKATERS_VIEW ? <p className="mt-1 text-xs text-blue-600">{entry.skater_name}</p> : null}
                    </Link>
                  ))}
                  {calendarMonthEntries.length > 8 ? <p className="text-sm text-slate-500">还有 {calendarMonthEntries.length - 8} 条，请在列表页翻看。</p> : null}
                </div>
              ) : (
                <p className="mt-4 rounded-[18px] bg-slate-50 px-4 py-5 text-sm leading-6 text-slate-500">这个月份还没有已加载的复盘记录。</p>
              )}
              {skaterIdsNeedingMore.length ? (
                <button
                  type="button"
                  onClick={() => void handleLoadMore()}
                  disabled={isLoadingMore}
                  className="mt-4 min-h-[44px] w-full rounded-full border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 transition hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isLoadingMore ? "正在加载更多..." : "加载更多历史记录"}
                </button>
              ) : null}
            </aside>
          </div>
        )}
      </section>

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
          resetTargetLock
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
