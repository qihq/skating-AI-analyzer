import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ArchiveResponse, fetchArchive, fetchSkaters, Skater } from "../api/client";
import ZodiacAvatar from "../components/ZodiacAvatar";

const FILTER_OPTIONS = ["全部", "跳跃", "旋转", "步法", "自由滑"] as const;

type TimelineGroup = {
  key: string;
  title: string;
  subtitle: string | null;
  items: ArchiveResponse["timeline"];
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

function skaterLabel(skater: Skater) {
  return skater.display_name || skater.name;
}

function buildGroupTitle(entry: ArchiveResponse["timeline"][number]) {
  if (!entry.session_id) {
    return formatSessionDate(entry.created_at);
  }
  return formatSessionDate(entry.session_date);
}

function buildGroupSubtitle(entry: ArchiveResponse["timeline"][number]) {
  if (!entry.session_id) {
    return null;
  }
  const parts = [entry.session_location, entry.session_type].filter(Boolean) as string[];
  if (entry.session_duration_minutes) {
    parts.push(`${entry.session_duration_minutes} 分钟`);
  }
  return parts.join(" · ") || null;
}

function buildTimelineGroups(timeline: ArchiveResponse["timeline"]): TimelineGroup[] {
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

export default function ArchivePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState("");
  const [archive, setArchive] = useState<ArchiveResponse | null>(null);
  const [activeFilter, setActiveFilter] = useState<(typeof FILTER_OPTIONS)[number]>("全部");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
        setSelectedSkaterId((current) => current || data.find((skater) => skater.is_default)?.id || data[0]?.id || "");
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
  }, []);

  useEffect(() => {
    if (!selectedSkaterId) {
      return;
    }

    let cancelled = false;
    const loadArchive = async () => {
      setIsLoading(true);
      try {
        const data = await fetchArchive(selectedSkaterId);
        if (!cancelled) {
          setArchive(data);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("练习档案时间轴加载失败，请稍后重试。");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void loadArchive();
    return () => {
      cancelled = true;
    };
  }, [selectedSkaterId]);

  const selectedSkater = skaters.find((skater) => skater.id === selectedSkaterId) ?? null;
  const filteredTimeline = useMemo(() => {
    const timeline = archive?.timeline ?? [];
    if (activeFilter === "全部") {
      return timeline;
    }
    return timeline.filter((entry) => entry.action_type === activeFilter);
  }, [activeFilter, archive?.timeline]);
  const timelineGroups = useMemo(() => buildTimelineGroups(filteredTimeline), [filteredTimeline]);

  return (
    <div className="space-y-6">
      <section className="app-card overflow-hidden p-6 tablet:p-8">
        <div className="flex flex-col gap-5 tablet:flex-row tablet:items-end tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Archive</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">练习档案时间轴</h1>
            <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">
              把每次视频复盘沉淀成连续可追踪的成长记录。这里会保留冰宝（IceBuddy）诊断、评分变化和课次归档关系。
            </p>
          </div>

          <label className="block min-w-[220px] space-y-2">
            <span className="text-sm font-medium text-slate-700">当前练习档案</span>
            <select value={selectedSkaterId} onChange={(event) => setSelectedSkaterId(event.target.value)} className="app-select">
              {skaters.map((skater) => (
                <option key={skater.id} value={skater.id}>
                  {skaterLabel(skater)}
                  {skater.level ? ` · ${skater.level}` : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      <div className="grid gap-6 web:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-6">
          {selectedSkater ? (
            <section className="app-card p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">当前对象</p>
              <div className="mt-4 rounded-[28px] bg-slate-50 p-5">
                <ZodiacAvatar avatarType={selectedSkater.avatar_type} avatarEmoji={selectedSkater.avatar_emoji} size="lg" className="mx-auto tablet:mx-0" />
                <h2 className="mt-3 text-xl font-semibold text-slate-900">{skaterLabel(selectedSkater)}</h2>
                <p className="mt-2 text-sm text-slate-500">{selectedSkater.level ?? selectedSkater.current_level}</p>
                <p className="mt-4 text-sm text-slate-500">当前 XP：{selectedSkater.total_xp}</p>
                <p className="mt-2 text-sm text-slate-500">连续记录：{selectedSkater.current_streak} 天</p>
              </div>
            </section>
          ) : null}

          <section className="grid gap-4 tablet:grid-cols-2 web:grid-cols-1">
            <div className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">累计档案</p>
              <p className="mt-3 text-3xl font-semibold text-slate-900">{archive?.stats.total_records ?? 0}</p>
              <p className="mt-2 text-sm text-slate-500">总记录数</p>
            </div>
            <div className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">近 7 天</p>
              <p className="mt-3 text-3xl font-semibold text-slate-900">{archive?.stats.recent_7days ?? 0}</p>
              <p className="mt-2 text-sm text-slate-500">最近一周训练次数</p>
            </div>
            <div className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">连续记录</p>
              <p className="mt-3 text-3xl font-semibold text-slate-900">{archive?.stats.current_streak ?? 0}</p>
              <p className="mt-2 text-sm text-slate-500">按自然日连续记录</p>
            </div>
            <div className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">本月课次</p>
              <p className="mt-3 text-3xl font-semibold text-slate-900">{archive?.stats.monthly_sessions ?? 0}</p>
              <p className="mt-2 text-sm text-slate-500">已登记训练课次</p>
            </div>
          </section>

          <section className="app-card p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">筛选</p>
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
          </section>
        </div>

        <section className="app-card p-6 tablet:p-7">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Timeline</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">复盘记录</h2>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">{filteredTimeline.length} 条</span>
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
                    {group.items.map((entry, index) => (
                      <article key={entry.id} className="content-visibility-auto relative pl-8">
                        {index < group.items.length - 1 ? (
                          <div className="absolute left-3 top-10 h-[calc(100%-1rem)] w-px bg-gradient-to-b from-blue-200 to-slate-100" />
                        ) : null}
                        <div className="absolute left-0 top-7 flex h-6 w-6 items-center justify-center rounded-full bg-blue-50 text-sm">⛸️</div>

                        <div className="rounded-[28px] border border-slate-200 bg-white p-5">
                          <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
                            <div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{entry.entry_type}</span>
                                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{entry.action_type}</span>
                                {entry.skill_category ? (
                                  <span className="rounded-full bg-blue-50 px-3 py-1 text-sm text-blue-600">{entry.skill_category}</span>
                                ) : null}
                                <span className={`rounded-full px-3 py-1 text-sm ${forceScoreTone(entry.force_score)}`}>评分 {entry.force_score ?? "--"}</span>
                              </div>
                              <p className="mt-3 text-sm text-slate-400">{formatDate(entry.created_at)}</p>
                              <p className="mt-4 max-w-3xl leading-7 text-slate-600">{entry.report_snippet}</p>
                            </div>

                            <Link
                              to={`/report/${entry.analysis_id}`}
                              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600"
                            >
                              查看冰宝（IceBuddy）诊断
                            </Link>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <div className="mt-6 rounded-[28px] bg-slate-50 px-5 py-6 text-sm text-slate-500">当前筛选下还没有复盘记录，先去上传一段训练视频吧。</div>
          )}
        </section>
      </div>
    </div>
  );
}
