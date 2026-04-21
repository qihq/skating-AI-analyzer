import { BioData } from "../api/client";

type BiomechanicsPanelProps = {
  bioData: BioData;
  mode: "child" | "parent";
  onSelectFrame?: (frameId: string) => void;
};

function metricDisplay(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { text: "数据异常", invalid: true };
  }
  return { text: value.toFixed(digits), invalid: false };
}

export default function BiomechanicsPanel({ bioData, mode, onSelectFrame }: BiomechanicsPanelProps) {
  const keyFrames = bioData.key_frames ?? {};
  const metrics = bioData.jump_metrics;
  if (!metrics) {
    return null;
  }

  const isChildMode = mode === "child";
  const showWarning = bioData.jump_metrics_status === "invalid" || Boolean(bioData.jump_metrics_warning);
  const visibleMetrics = isChildMode
    ? [
        { label: "滞空时间", ...metricDisplay(metrics.air_time_seconds, 2), unit: "s" },
        { label: "跳跃高度", ...metricDisplay(metrics.estimated_height_cm, 1), unit: "cm" },
      ]
    : [
        { label: "滞空时间", ...metricDisplay(metrics.air_time_seconds, 2), unit: "s" },
        { label: "跳跃高度", ...metricDisplay(metrics.estimated_height_cm, 1), unit: "cm" },
        { label: "起跳速度", ...metricDisplay(metrics.takeoff_speed_mps, 2), unit: "m/s" },
        { label: "转速", ...metricDisplay(metrics.rotation_rps, 2), unit: "rev/s" },
      ];

  const frameButtons = [
    { key: "T", label: "Takeoff", title: "起跳", color: "#F59E0B", frame: keyFrames.T },
    { key: "A", label: "Apex", title: "顶点", color: "#3B82F6", frame: keyFrames.A },
    { key: "L", label: "Landing", title: "落冰", color: "#EF4444", frame: keyFrames.L },
  ].filter((item) => item.frame);

  return (
    <div className="space-y-5 rounded-[28px] border border-slate-200 bg-slate-50 p-5">
      {showWarning ? (
        <div className="rounded-[20px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          {bioData.jump_metrics_warning ?? "当前视频关键帧检测不稳定，生物力学指标已标记为数据异常。"}
        </div>
      ) : null}

      {frameButtons.length ? (
        <div className="grid gap-3 tablet:grid-cols-3">
          {frameButtons.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => onSelectFrame?.(item.frame!)}
              className="rounded-[24px] bg-white px-4 py-4 text-left transition hover:-translate-y-0.5"
            >
              <div className="flex items-center gap-3">
                <div
                  className="flex h-11 w-11 items-center justify-center rounded-2xl text-sm font-bold text-white"
                  style={{ backgroundColor: item.color }}
                >
                  {item.key}
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">{item.label}</p>
                  <p className="mt-1 text-base font-semibold text-slate-900">{item.title}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : null}

      <div className={`grid gap-4 ${isChildMode ? "tablet:grid-cols-2" : "tablet:grid-cols-2 web:grid-cols-4"}`}>
        {visibleMetrics.map((metric) => (
          <article key={metric.label} className="rounded-[24px] bg-white p-4">
            <p className="text-sm text-slate-500">{metric.label}</p>
            <div className="mt-3 flex items-end gap-2">
              <span className={`text-3xl font-semibold ${metric.invalid ? "text-rose-500" : "text-slate-900"}`}>
                {metric.text}
              </span>
              {!metric.invalid ? <span className="pb-1 text-sm text-slate-400">{metric.unit}</span> : null}
            </div>
          </article>
        ))}
      </div>

      {isChildMode ? (
        <p className="text-sm leading-6 text-slate-500">坦坦模式会隐藏更复杂的速度、转速与完整生物力学拆解，家长模式可查看全部细节。</p>
      ) : null}
    </div>
  );
}
