import { BioData } from "../api/client";
import ProfileEvidenceWarning, { normalizeProfileWarning, resolveProfileWarning } from "./ProfileEvidenceWarning";

type BiomechanicsPanelProps = {
  bioData: BioData;
  mode: "child" | "parent";
  onSelectFrame?: (frameId: string) => void;
  reportWarning?: string | null;
};

const JUMP_WARNING_FALLBACK = "当前视频关键帧检测不稳定，生物力学指标已标记为数据异常。";

function metricDisplay(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { text: "数据异常", invalid: true };
  }
  return { text: value.toFixed(digits), invalid: false };
}

const metricStyles = {
  cyan: "border-cyan-100 bg-cyan-50/70 text-cyan-700",
  emerald: "border-emerald-100 bg-emerald-50/70 text-emerald-700",
  amber: "border-amber-100 bg-amber-50/80 text-amber-700",
  violet: "border-violet-100 bg-violet-50/70 text-violet-700",
} as const;

const frameStyles = {
  amber: "border-amber-200 bg-amber-50 text-amber-700",
  blue: "border-blue-200 bg-blue-50 text-blue-700",
  rose: "border-rose-200 bg-rose-50 text-rose-700",
} as const;

export default function BiomechanicsPanel({ bioData, mode, onSelectFrame, reportWarning }: BiomechanicsPanelProps) {
  const keyFrames = bioData.key_frames ?? {};
  const metrics = bioData.jump_metrics;
  const profileWarning = resolveProfileWarning(reportWarning, bioData.profile_warning);
  if (!metrics) {
    return profileWarning ? (
      <ProfileEvidenceWarning reportWarning={reportWarning} bioWarning={bioData.profile_warning} />
    ) : null;
  }

  const isChildMode = mode === "child";
  const showWarning = bioData.jump_metrics_status === "invalid" || Boolean(bioData.jump_metrics_warning);
  const jumpWarningText = bioData.jump_metrics_warning ?? (showWarning ? JUMP_WARNING_FALLBACK : "");
  const showProfileWarning = Boolean(profileWarning) && profileWarning !== normalizeProfileWarning(jumpWarningText);
  const visibleMetrics = isChildMode
    ? [
        { label: "滞空时间", caption: "Air time", icon: "T", tone: "cyan" as const, ...metricDisplay(metrics.air_time_seconds, 2), unit: "s" },
        { label: "跳跃高度", caption: "Height", icon: "H", tone: "emerald" as const, ...metricDisplay(metrics.estimated_height_cm, 1), unit: "cm" },
      ]
    : [
        { label: "滞空时间", caption: "Air time", icon: "T", tone: "cyan" as const, ...metricDisplay(metrics.air_time_seconds, 2), unit: "s" },
        { label: "跳跃高度", caption: "Height", icon: "H", tone: "emerald" as const, ...metricDisplay(metrics.estimated_height_cm, 1), unit: "cm" },
        { label: "起跳速度", caption: "Takeoff", icon: "V", tone: "amber" as const, ...metricDisplay(metrics.takeoff_speed_mps, 2), unit: "m/s" },
        { label: "转速", caption: "Rotation", icon: "R", tone: "violet" as const, ...metricDisplay(metrics.rotation_rps, 2), unit: "rev/s" },
      ];

  const frameButtons = [
    { key: "T", label: "Takeoff", title: "起跳", tone: "amber" as const, frame: keyFrames.T },
    { key: "A", label: "Apex", title: "顶点", tone: "blue" as const, frame: keyFrames.A },
    { key: "L", label: "Landing", title: "落冰", tone: "rose" as const, frame: keyFrames.L },
  ].filter((item) => item.frame);

  return (
    <div className="space-y-4 rounded-[24px] border border-slate-200 bg-slate-50/80 p-4 tablet:p-5">
      {showWarning ? (
        <div className="rounded-[18px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-700">
          {bioData.jump_metrics_warning ?? JUMP_WARNING_FALLBACK}
        </div>
      ) : null}

      {showProfileWarning ? (
        <ProfileEvidenceWarning reportWarning={reportWarning} bioWarning={bioData.profile_warning} />
      ) : null}

      {frameButtons.length ? (
        <div className="grid gap-2 phone:grid-cols-3">
          {frameButtons.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => onSelectFrame?.(item.frame!)}
              className={`min-h-[64px] rounded-[18px] border px-3 py-3 text-left transition hover:-translate-y-0.5 hover:bg-white ${frameStyles[item.tone]}`}
            >
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] bg-white text-sm font-bold shadow-sm">
                  {item.key}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-[11px] font-semibold uppercase text-current opacity-70">{item.label}</p>
                  <p className="mt-0.5 truncate text-sm font-semibold text-slate-900">{item.title}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : null}

      <div className={`grid gap-3 ${isChildMode ? "phone:grid-cols-2" : "phone:grid-cols-2 web:grid-cols-4"}`}>
        {visibleMetrics.map((metric) => (
          <article key={metric.label} className="min-h-[132px] min-w-0 rounded-[20px] border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex min-w-0 items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-800">{metric.label}</p>
                <p className="mt-1 truncate text-[11px] font-semibold uppercase text-slate-400">{metric.caption}</p>
              </div>
              <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border text-sm font-bold ${metricStyles[metric.tone]}`}>
                {metric.icon}
              </span>
            </div>
            <div className="mt-4 flex min-w-0 items-end gap-2">
              <span className={`min-w-0 break-all text-2xl font-semibold leading-none tablet:text-3xl ${metric.invalid ? "text-rose-500" : "text-slate-950"}`}>
                {metric.text}
              </span>
              {!metric.invalid ? <span className="shrink-0 pb-0.5 text-sm font-medium text-slate-400">{metric.unit}</span> : null}
            </div>
          </article>
        ))}
      </div>

      {isChildMode ? (
        <p className="rounded-[18px] bg-white/70 px-4 py-3 text-sm leading-6 text-slate-500">儿童模式会隐藏更复杂的速度、转速与完整生物力学拆解，家长模式可查看全部细节。</p>
      ) : null}
    </div>
  );
}
