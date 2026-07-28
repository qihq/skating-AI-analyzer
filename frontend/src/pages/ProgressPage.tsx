import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fetchProgress, ProgressPoint, ProgressResponse } from "../api/client";
import TopNav from "../components/TopNav";
import { parseApiDate } from "../utils/datetime";
import { createShareImagePreview, normalizeShareText, ShareImagePreview } from "../utils/shareCanvas";
import { exportShareDocument } from "../utils/shareExport";
import IslandShareDialog from "../modern/IslandShareDialog";

const FILTER_OPTIONS = ["å…¨éƒ¨", "è·³è·ƒ", "æ—‹è½¬", "æ­¥æ³•", "è‡ªç”±æ»‘"] as const;

type FilterOption = (typeof FILTER_OPTIONS)[number];
type ChartPoint = ProgressPoint & { dateLabel: string };

function formatDateShort(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(parseApiDate(dateString));
}

function formatDateLong(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(dateString));
}

function createProgressShareDocument(data: ProgressResponse, selectedPoint: ProgressPoint | null, activeFilter: FilterOption) {
  const orderedPoints = [...data.points].sort((left, right) => parseApiDate(left.created_at).getTime() - parseApiDate(right.created_at).getTime());
  const latest = orderedPoints[orderedPoints.length - 1] ?? null;
  const best = orderedPoints.reduce<ProgressPoint | null>((current, point) => (!current || point.force_score > current.force_score ? point : current), null);
  const recent = orderedPoints.slice(-8).reverse();
  const trend = orderedPoints.length >= 2 ? orderedPoints[orderedPoints.length - 1].force_score - orderedPoints[0].force_score : 0;
  const selected = selectedPoint ?? latest;
  const sections = [
    {
      label: "è¶‹åŠ¿æ¦‚è§ˆ",
      title: `å…± ${data.stats.total_count} æ¬¡å¤ç›˜ï¼Œæœ€è¿‘è¯„åˆ† ${data.stats.latest_score ?? "--"}ï¼ŒåŽ†å²æœ€é«˜ ${data.stats.best_score ?? "--"}ï¼Œè¿‘ 5 æ¬¡å‡å€¼ ${data.stats.recent_five_average ?? "--"}`,
      body: orderedPoints.length >= 2 ? `åŒºé—´å˜åŒ– ${trend >= 0 ? "+" : ""}${trend} åˆ†ã€‚æœ€ä½³è®°å½•ï¼š${best ? `${formatDateShort(best.created_at)} ${best.force_score}åˆ†` : "æš‚æ— "}ã€‚` : "å½“å‰è®°å½•è¿˜ä¸å¤Ÿå½¢æˆé•¿æœŸè¶‹åŠ¿ã€‚",
      color: "#0891B2",
      bg: "#ECFEFF",
    },
    ...(selected
      ? [
          {
            label: "é€‰ä¸­è®°å½•",
            title: `${selected.action_subtype || selected.action_type} Â· è¯„åˆ† ${selected.force_score}`,
            body: normalizeShareText(selected.comments ?? selected.note ?? selected.summary, "æœ¬æ¬¡æ²¡æœ‰å¡«å†™ commentsã€‚"),
            meta: formatDateLong(selected.created_at),
            color: "#2563EB",
            bg: "#EFF6FF",
          },
        ]
      : []),
    {
      label: "æœ€è¿‘è®°å½•",
      title: recent
        .map((point) => `${formatDateShort(point.created_at)} ${point.action_subtype || point.action_type} ${point.force_score}åˆ†`)
        .join("ï¼›"),
      body: recent
        .map((point) => {
          const comment = normalizeShareText(point.comments ?? point.note, "");
          return comment ? `${formatDateShort(point.created_at)} commentsï¼š${comment}` : "";
        })
        .filter(Boolean)
        .join("\n"),
      color: "#059669",
      bg: "#ECFDF5",
    },
  ];

  return {
    eyebrow: "IceBuddy Progress",
    title: `${activeFilter} è¿›æ­¥è¶‹åŠ¿`,
    subtitle: `${latest?.skater_name ?? selected?.skater_name ?? "å°è¿åŠ¨å‘˜"} Â· ${latest ? formatDateShort(latest.created_at) : "æš‚æ— æ—¥æœŸ"}`,
    intro: "æ¯æ¬¡è®­ç»ƒ comments å’Œè¯„åˆ†è¶‹åŠ¿ä¼šä¸€èµ·ä¿ç•™ï¼Œæ–¹ä¾¿å¤ç›˜è¿‘æœŸåŠ¨ä½œç¨³å®šæ€§ã€‚",
    sections,
    footer: "è¿›å±•å›¾ç”± IceBuddy ç”Ÿæˆï¼Œè¶‹åŠ¿ä»…ä¾›è®­ç»ƒå¤ç›˜å‚è€ƒã€‚",
    filename: `icebuddy-progress-${activeFilter}-${Date.now()}.jpg`,
  };
}

export default function ProgressPage() {
  const [activeFilter, setActiveFilter] = useState<FilterOption>("å…¨éƒ¨");
  const [data, setData] = useState<ProgressResponse | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<ProgressPoint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isSharing, setIsSharing] = useState(false);
  const [sharePreview, setSharePreview] = useState<ShareImagePreview[]>([]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const response = await fetchProgress(activeFilter === "å…¨éƒ¨" ? undefined : { action_type: activeFilter });
        if (!cancelled) {
          setData(response);
          setSelectedPoint(response.points.length ? response.points[response.points.length - 1] : null);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("è¶‹åŠ¿æ•°æ®åŠ è½½å¤±è´¥ï¼Œè¯·ç¨åŽé‡è¯•ã€‚");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [activeFilter]);

  const chartData = useMemo(
    () =>
      (data?.points ?? []).map((point): ChartPoint => ({
        ...point,
        dateLabel: formatDateShort(point.created_at),
      })),
    [data],
  );

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const handleShareProgress = async () => {
    if (!data || isSharing) {
      return;
    }
    setIsSharing(true);
    setError(null);
    try {
      const result = await exportShareDocument(createProgressShareDocument(data, selectedPoint, activeFilter));
      setSharePreview(result.pages.map((page) => createShareImagePreview(page, false)));
      showNotice("è¿›å±•åˆ†äº«å›¾å·²ç”Ÿæˆ");
    } catch {
      setError("è¿›å±•åˆ†äº«å›¾ç”Ÿæˆå¤±è´¥ï¼Œè¯·ç¨åŽé‡è¯•ã€‚");
    } finally {
      setIsSharing(false);
    }
  };

  return (
    <main className="page-shell page-scroll-container min-h-screen">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="ice-orb left-[8%] top-[8%]" />
        <div className="ice-orb bottom-[10%] right-[10%]" />
        <div className="grid-ice h-full w-full" />
      </div>

      <section className="mx-auto min-h-screen w-full max-w-6xl px-4 py-4 sm:px-6 sm:py-6 lg:px-10">
        <TopNav />

        <header className="frost-panel">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-cyan-200/80">Progress</p>
              <h2 className="mt-3 text-2xl font-semibold text-white sm:text-3xl">è¿›æ­¥è¶‹åŠ¿æŠ˜çº¿å›¾</h2>
              <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-300 sm:text-base">
                è·Ÿè¸ªæ¯æ¬¡è®­ç»ƒå¤ç›˜çš„å‘åŠ›è¯„åˆ†å˜åŒ–ï¼Œå¿«é€Ÿçœ‹åˆ°è¿‘æœŸä¸Šå‡è¶‹åŠ¿ã€æ³¢åŠ¨åŒºé—´å’Œæœ€æ–°é˜¶æ®µçš„è®­ç»ƒæ‘˜è¦ã€‚
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void handleShareProgress()}
                disabled={!data?.points.length || isSharing}
                className="pill-link w-fit disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSharing ? "ç”Ÿæˆä¸­..." : "åˆ†äº«è¿›å±•å›¾"}
              </button>
              <Link to="/history" className="pill-link w-fit">
                è¿”å›žåŽ†å²è®°å½•
              </Link>
            </div>
          </div>
        </header>

        <div className="mt-6 flex flex-wrap gap-3">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setActiveFilter(option)}
              className={`rounded-full px-4 py-2 text-sm transition ${
                activeFilter === option ? "bg-cyan-300 text-slate-950" : "bg-white/6 text-slate-200 hover:bg-white/12"
              }`}
            >
              {option}
            </button>
          ))}
        </div>

        {notice ? <div className="mt-5 rounded-[24px] border border-cyan-300/20 bg-cyan-300/12 px-5 py-4 text-sm text-cyan-50">{notice}</div> : null}
        {error ? <div className="mt-5 text-sm text-rose-200">{error}</div> : null}

        <div className="mt-6 grid gap-4 lg:grid-cols-[1.1fr_0.9fr] lg:gap-6">
          <div className="frost-panel min-h-[300px] overflow-hidden px-2 py-3 sm:min-h-[420px] sm:px-6 sm:py-5">
            {chartData.length ? (
              <div className="h-[280px] sm:h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={chartData}
                    margin={{ top: 8, right: 8, bottom: 8, left: -16 }}
                    onClick={(state: { activePayload?: Array<{ payload?: ChartPoint }> }) => {
                      const payload = state?.activePayload?.[0]?.payload as ChartPoint | undefined;
                      if (payload) {
                        setSelectedPoint(payload);
                      }
                    }}
                  >
                    <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />
                    <XAxis dataKey="dateLabel" stroke="#cbd5e1" tickLine={false} axisLine={false} minTickGap={20} />
                    <YAxis width={28} domain={[0, 100]} stroke="#cbd5e1" tickLine={false} axisLine={false} />
                    <Tooltip
                      cursor={{ stroke: "rgba(34,211,238,0.35)", strokeWidth: 1 }}
                      contentStyle={{
                        background: "rgba(2, 6, 23, 0.92)",
                        border: "1px solid rgba(255,255,255,0.12)",
                        borderRadius: "18px",
                        color: "#f8fafc",
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="force_score"
                      stroke="#67e8f9"
                      strokeWidth={3}
                      dot={{ r: 5, strokeWidth: 0, fill: "#22d3ee", cursor: "pointer" }}
                      activeDot={{ r: 7, fill: "#cffafe" }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-center text-sm text-slate-300 sm:text-base">
                å½“å‰ç­›é€‰ä¸‹è¿˜æ²¡æœ‰å¯å±•ç¤ºçš„è¶‹åŠ¿æ•°æ®ã€‚
              </div>
            )}
          </div>

          <div className="space-y-4 sm:space-y-6">
            <div className="frost-panel min-w-0 overflow-hidden p-4 sm:p-6">
              <p className="text-sm uppercase tracking-[0.28em] text-cyan-200/80">Selected Point</p>
              {selectedPoint ? (
                <>
                  <div className="mt-3 flex flex-wrap items-start gap-2">
                    <span className="rounded-full bg-white/8 px-3 py-1 text-sm text-white">{selectedPoint.action_subtype || selectedPoint.action_type}</span>
                    <span className="rounded-full bg-cyan-300/12 px-3 py-1 text-sm text-cyan-50">è¯„åˆ† {selectedPoint.force_score}</span>
                  </div>
                  <p className="mt-4 break-words text-sm leading-6 text-slate-400">{formatDateLong(selectedPoint.created_at)}</p>
                  <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-slate-100/90 sm:text-base">
                    {selectedPoint.summary}
                  </p>
                </>
              ) : (
                <p className="mt-4 text-sm leading-7 text-slate-300 sm:text-base">ç‚¹å‡»æŠ˜çº¿å›¾ä¸­çš„ä»»æ„æ•°æ®ç‚¹ï¼ŒæŸ¥çœ‹å¯¹åº”è®­ç»ƒæ‘˜è¦ã€‚</p>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2 sm:gap-4">
              <div className="stat-panel">
                <p className="stat-label">æ€»æ¬¡æ•°</p>
                <p className="stat-value">{data?.stats.total_count ?? 0}</p>
                <p className="stat-meta">å®Œæˆå¤ç›˜è®°å½•</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">æœ€è¿‘è¯„åˆ†</p>
                <p className="stat-value">{data?.stats.latest_score ?? "--"}</p>
                <p className="stat-meta">æœ€æ–°ä¸€æ¬¡ç»“æžœ</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">åŽ†å²æœ€é«˜</p>
                <p className="stat-value">{data?.stats.best_score ?? "--"}</p>
                <p className="stat-meta">æœ€ä½³è¡¨çŽ°</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">è¿‘ 5 æ¬¡å‡å€¼</p>
                <p className="stat-value">{data?.stats.recent_five_average ?? "--"}</p>
                <p className="stat-meta">è¿‘æœŸç¨³å®šæ€§</p>
              </div>
            </div>
          </div>
        </div>
      </section>
      <IslandShareDialog preview={null} previews={sharePreview} title="进展分享图" onClose={() => setSharePreview([])} />
    </main>
  );
}
