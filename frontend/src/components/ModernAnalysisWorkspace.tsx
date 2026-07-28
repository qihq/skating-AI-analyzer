import { useEffect, useMemo, useRef } from "react";

import { AnalysisDetail, PoseFrame, PoseResponse } from "../api/client";
import { IceMediaPlayer, type IceMediaPlayerHandle } from "../media/IceMediaPlayer";
import { analysisMediaMarkers } from "../media/analysisMarkers";

type ModernAnalysisWorkspaceProps = {
  analysis: AnalysisDetail;
  pose: PoseResponse | null;
  selectedFrameId: string | null;
  onFrameChange: (frameId: string) => void;
};

const MARKER_COLORS = ["#2563EB", "#7C3AED", "#22C55E", "#F59E0B", "#EF4444"];

function metricUnavailableText() {
  return "æš‚æ— æ•°æ®";
}

function frameStem(frameName: string) {
  return frameName.replace(/\.jpg$/i, "");
}

function timestampForFrame(pose: PoseResponse, frame: PoseFrame, index: number) {
  const direct = pose.frame_timestamps?.[frame.frame] ?? pose.frame_timestamps?.[frameStem(frame.frame)];
  if (typeof direct === "number" && Number.isFinite(direct)) {
    return direct;
  }
  const fps = typeof pose.effective_fps === "number" && pose.effective_fps > 0 ? pose.effective_fps : 5;
  return index / fps;
}

function formatMetric(value: number | null | undefined, unit: string, digits = 1) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return { value: metricUnavailableText(), unit: "" };
  }
  return { value: value.toFixed(digits), unit };
}

function PerformanceMetrics({ analysis }: { analysis: AnalysisDetail }) {
  const metrics = analysis.bio_data?.jump_metrics;
  const landingImpact =
    typeof analysis.report?.subscores?.landing_absorption === "number"
      ? { value: Math.round(analysis.report.subscores.landing_absorption).toString(), unit: "/100" }
      : { value: metricUnavailableText(), unit: "" };
  const items = [
    { label: "è·³è·ƒé«˜åº¦", ...formatMetric(metrics?.estimated_height_cm, "cm", 1), accent: "#38BDF8", gradient: "from-sky-400/16 to-blue-500/8" },
    { label: "æ»žç©ºæ—¶é—´", ...formatMetric(metrics?.air_time_seconds, "s", 2), accent: "#34D399", gradient: "from-emerald-400/16 to-teal-500/8" },
    {
      label: "æ—‹è½¬é€Ÿåº¦",
      ...formatMetric(typeof metrics?.rotation_rps === "number" ? metrics.rotation_rps * 60 : null, "rpm", 0),
      accent: "#A78BFA",
      gradient: "from-violet-400/16 to-fuchsia-500/8",
    },
    { label: "è½å†°ç¨³å®šæ€§", ...landingImpact, accent: "#F59E0B", gradient: "from-amber-400/16 to-orange-500/8" },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 ipad:grid-cols-4 web:grid-cols-1">
      {items.map((item) => (
        <article key={item.label} className={`min-w-0 rounded-lg border border-white/10 bg-gradient-to-br ${item.gradient} bg-slate-900/70 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]`}>
          <div className="flex items-center justify-between gap-3">
            <p className="min-w-0 text-sm font-medium leading-5 text-slate-300">{item.label}</p>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full shadow-[0_0_16px_currentColor]" style={{ backgroundColor: item.accent, color: item.accent }} />
          </div>
          <div className="mt-4 flex min-w-0 items-end gap-2">
            <span
              className={`min-w-0 max-w-full truncate font-semibold leading-none text-white ${
                item.value === metricUnavailableText() ? "text-[clamp(1.25rem,4.4vw,1.75rem)]" : "text-3xl"
              }`}
              title={item.value}
            >
              {item.value}
            </span>
            {item.unit ? <span className="pb-1 text-sm font-medium text-slate-400">{item.unit}</span> : null}
          </div>
          <svg viewBox="0 0 120 28" className="mt-4 h-7 w-full text-current opacity-80" style={{ color: item.accent }} aria-hidden="true">
            <path d="M2 22 C14 19 18 10 28 15 C38 20 42 7 53 11 C63 15 67 4 78 8 C90 12 95 20 106 11 C112 6 116 8 118 5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            <path d="M2 22 C14 19 18 10 28 15 C38 20 42 7 53 11 C63 15 67 4 78 8 C90 12 95 20 106 11 C112 6 116 8 118 5 L118 28 L2 28 Z" fill="currentColor" opacity="0.08" />
          </svg>
        </article>
      ))}
    </div>
  );
}

export default function ModernAnalysisWorkspace({ analysis, pose, selectedFrameId, onFrameChange }: ModernAnalysisWorkspaceProps) {
  const playerRef = useRef<IceMediaPlayerHandle | null>(null);
  const timelineMarkers = useMemo(() => analysisMediaMarkers(analysis), [analysis]);
  useEffect(() => {
    if (!pose || !selectedFrameId) return;
    const index = pose.frames.findIndex((frame) => frameStem(frame.frame) === selectedFrameId || frame.frame === selectedFrameId);
    if (index >= 0) playerRef.current?.seek(timestampForFrame(pose, pose.frames[index], index));
  }, [pose, selectedFrameId]);

  return (
    <section className="space-y-5 rounded-lg border border-white/10 bg-[#0C1422] p-4 text-slate-100 shadow-[0_24px_80px_rgba(2,6,23,0.26)] tablet:p-5">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-end tablet:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">AI è§†é¢‘åˆ†æžå·¥ä½œç«™</p>
          <h2 className="mt-2 text-2xl font-semibold leading-tight text-white">éª¨éª¼è¿½è¸ªä¸Žç”Ÿç‰©åŠ›å­¦åˆ†æž</h2>
        </div>
        <div className="w-fit shrink-0 rounded-lg border border-white/10 bg-slate-950/30 px-4 py-3 text-sm text-slate-300">
          {pose?.frames?.length ? `${pose.frames.length} å¸§å§¿æ€æ•°æ®` : "æš‚æ— å§¿æ€æ•°æ®"}
        </div>
      </div>

      <PerformanceMetrics analysis={analysis} />

      <div className="grid min-w-0 gap-5 web:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          <IceMediaPlayer
            ref={playerRef}
            manifest={analysis.media_manifest}
            fallbackSrc={`/api/analysis/${analysis.id}/video`}
            pose={pose}
            mode={pose?.frames?.length ? "overlay" : "video"}
            markers={timelineMarkers}
            onTimeChange={(time) => {
              if (!pose?.frames?.length) return;
              const closest = pose.frames.reduce<{ frame: PoseFrame; index: number; delta: number } | null>((best, frame, index) => {
                const delta = Math.abs(timestampForFrame(pose, frame, index) - time);
                return !best || delta < best.delta ? { frame, index, delta } : best;
              }, null);
              if (closest) onFrameChange(frameStem(closest.frame.frame));
            }}
          />
        </div>

        <aside className="min-w-0 rounded-lg border border-white/10 bg-[#0E1726] p-4 shadow-[0_18px_50px_rgba(2,6,23,0.18)]">
          <p className="text-sm font-semibold text-white">å®žæ—¶å§¿æ€æ¦‚è§ˆ</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 web:grid-cols-1">
            <div className="rounded-md border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">å…³é”®å¸§</p>
              <p className="mt-2 text-2xl font-semibold text-white">{pose?.frames?.length ?? 0}</p>
            </div>
            <div className="rounded-md border border-white/10 bg-white/5 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-400">è¿žæŽ¥çº¿</p>
              <p className="mt-2 text-2xl font-semibold text-white">{pose?.connections?.length ?? 0}</p>
            </div>
          </div>
          <div className="mt-4 rounded-md border border-white/10 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400">å¸§é€Ÿä¿¡æ¯</p>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              {typeof pose?.effective_fps === "number" && pose.effective_fps > 0 ? `æœ‰æ•ˆ FPSï¼š${pose.effective_fps.toFixed(1)}` : "æœ‰æ•ˆ FPS æœªæä¾›ï¼ŒæŒ‰å¸§åºå·ä¼°ç®—æ—¶é—´ã€‚"}
            </p>
          </div>
          <div className="mt-4 rounded-md border border-white/10 bg-white/5 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-400">æ—¶é—´è½´è¯´æ˜Ž</p>
            <p className="mt-2 text-sm leading-6 text-slate-300">ç‚¹å‡»å½©è‰²æ¡å—å³å¯è·³è½¬åˆ°å¯¹åº”åŠ¨ä½œé˜¶æ®µã€‚</p>
          </div>
        </aside>
      </div>

      <div className="grid min-w-0 gap-5 web:grid-cols-[minmax(0,1fr)_360px] web:items-start">
        <aside className="min-w-0 rounded-lg border border-white/10 bg-[#0E1726] p-4 shadow-[0_18px_50px_rgba(2,6,23,0.18)]">
          <p className="text-sm font-semibold text-white">åŠ¨ä½œæ—¶é—´è½´</p>
          <div className="mt-4 space-y-3">
            {timelineMarkers.length ? (
              timelineMarkers.map((marker, index) => (
                <button
                  key={marker.id}
                  type="button"
                  onClick={() => playerRef.current?.seek(marker.timestamp, { play: true })}
                  className="flex min-h-[48px] w-full min-w-0 items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/5 px-3 py-3 text-left text-sm transition hover:border-white/20 hover:bg-white/8"
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="h-3 w-3 shrink-0 rounded-sm" style={{ backgroundColor: MARKER_COLORS[index % MARKER_COLORS.length] }} />
                    <span className="truncate font-medium text-slate-200">{marker.label}</span>
                  </span>
                  <span className="shrink-0 text-slate-400">{marker.timestamp.toFixed(2)}s</span>
                </button>
              ))
            ) : (
              <p className="text-sm leading-6 text-slate-400">æœ¬æ¬¡åˆ†æžæš‚æœªè¿”å›žè¯­ä¹‰å…³é”®å¸§æˆ–ç”Ÿç‰©åŠ›å­¦å…³é”®å¸§ã€‚</p>
            )}
          </div>
        </aside>

        <aside className="min-w-0 rounded-lg border border-white/10 bg-[#0E1726] p-4 shadow-[0_18px_50px_rgba(2,6,23,0.18)]">
          <p className="text-sm font-semibold text-white">åˆ†æžä¸Šä¸‹æ–‡</p>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4 rounded-md bg-white/5 px-3 py-3">
              <dt className="text-slate-400">åŠ¨ä½œ</dt>
              <dd className="text-right font-medium text-slate-100">{analysis.action_type}</dd>
            </div>
            <div className="flex justify-between gap-4 rounded-md bg-white/5 px-3 py-3">
              <dt className="text-slate-400">æµç¨‹ç‰ˆæœ¬</dt>
              <dd className="text-right font-medium text-slate-100">{analysis.pipeline_version ?? "æœªçŸ¥"}</dd>
            </div>
            <div className="flex justify-between gap-4 rounded-md bg-white/5 px-3 py-3">
              <dt className="text-slate-400">æºè§†é¢‘ FPS</dt>
              <dd className="text-right font-medium text-slate-100">{analysis.source_fps ? Math.round(analysis.source_fps) : "æœªçŸ¥"}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </section>
  );
}
