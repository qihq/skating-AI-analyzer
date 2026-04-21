import { CSSProperties } from "react";

type ForceScoreRingProps = {
  score: number;
  sizeClassName?: string;
};

function scoreColor(score: number) {
  if (score >= 80) {
    return "var(--score-high)";
  }
  if (score >= 60) {
    return "var(--score-mid)";
  }
  return "var(--score-low)";
}

export default function ForceScoreRing({ score, sizeClassName = "h-24 w-24 tablet:h-28 tablet:w-28" }: ForceScoreRingProps) {
  const clampedScore = Math.max(0, Math.min(score, 100));

  return (
    <div
      className={`relative ${sizeClassName}`}
      style={
        {
          "--score": clampedScore,
          "--score-color": scoreColor(clampedScore),
        } as CSSProperties
      }
    >
      <svg className="h-full w-full -rotate-90" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="42" fill="none" stroke="#E5E7EB" strokeWidth="8" />
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="var(--score-color)"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray="263.9"
          strokeDashoffset={`calc(263.9 * (1 - ${clampedScore} / 100))`}
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold text-slate-900">{clampedScore}</span>
        <span className="text-xs text-slate-400">分</span>
      </div>
    </div>
  );
}
