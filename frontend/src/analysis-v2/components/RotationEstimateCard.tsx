import type { RotationEstimateV2 } from "../contracts";

function turns(value: number): string {
  return value.toFixed(2).replace(/\.?0+$/, "");
}

export function rotationEstimateLanguage(rotation: RotationEstimateV2): string {
  const definition = rotation.valueConvention === "airborne_body_rotation" ? "空中身体转体" : "旋转主体观察圈数";
  switch (rotation.status) {
    case "exact":
      return `${definition} ${turns(rotation.valueTurns)} 圈`;
    case "range":
      return `${definition}约 ${turns(rotation.rangeTurns[0])}–${turns(rotation.rangeTurns[1])} 圈`;
    case "unobservable":
      return "画面不足，暂不判断";
  }
}

export function competitionNamingLanguage(rotation: RotationEstimateV2): string | null {
  if (rotation.competitionConvention === "axel" && rotation.competitionNamingClass) return `比赛命名：${rotation.competitionNamingClass.replace(/_/g, " ")}`;
  if (rotation.competitionConvention === "non_axel" && rotation.competitionNamingTurns != null) return `比赛命名参考：${rotation.competitionNamingTurns} 圈`;
  if (rotation.competitionConvention === "unknown") return "比赛命名：动作细分证据不足，未应用约定";
  return null;
}

export default function RotationEstimateCard({ rotation, compact = false }: { rotation: RotationEstimateV2; compact?: boolean }) {
  const competition = competitionNamingLanguage(rotation);
  const airborne = rotation.phases.find((phase) => phase.phase === "airborne" || phase.phase === "spin_main");
  const pre = rotation.phases.find((phase) => phase.phase === "pre_takeoff");
  const post = rotation.phases.find((phase) => phase.phase === "post_landing");
  const phaseLanguage = (label: string, phase: typeof pre) => {
    if (!phase || phase.status === "unobservable") return null;
    if (phase.status === "exact") return `${label} ${phase.valueTurns?.toFixed(2)} 圈`;
    return `${label} ${phase.rangeTurns?.[0].toFixed(2)}–${phase.rangeTurns?.[1].toFixed(2)} 圈`;
  };
  return <section className={`rounded-2xl border border-blue-100 bg-blue-50/60 p-4 ${compact ? "text-sm" : ""}`} aria-label="多信号旋转估计" aria-live="polite">
    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-600">Multi-signal rotation</p>
    <strong className="mt-1 block text-slate-900">{rotationEstimateLanguage(rotation)}</strong>
    {competition ? <p className="mt-1 text-sm text-slate-600">{competition}</p> : null}
    {!compact ? <>
      <p className="mt-2 text-xs text-slate-500">定义：{rotation.valueConvention === "airborne_body_rotation" ? "空中身体转体" : "旋转主体观察圈数"} · {rotation.definitionVersion}</p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
        {[phaseLanguage("起跳前", pre), phaseLanguage(rotation.profile === "jump" ? "空中" : "主体", airborne), phaseLanguage("落冰后继续", post)].filter(Boolean).map((item) => <span className="rounded-full bg-white px-3 py-1" key={item}>{item}</span>)}
      </div>
      {rotation.status !== "exact" ? <p className="mt-2 text-xs text-amber-700">不会把区间取整成确定圈数，也不会用历史 shoulder×倍率补值。</p> : null}
    </> : null}
  </section>;
}
