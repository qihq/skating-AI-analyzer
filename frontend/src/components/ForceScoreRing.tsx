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
  const radius = 42;
  const circumference = 2 * Math.PI * radius;

  return (
    <div
      className={`relative aspect-square ${sizeClassName}`}
      style={
        {
          "--score-color": scoreColor(clampedScore),
        } as CSSProperties
      }
    >
      {/* 修改前：直接在 svg 节点上使用旋转类名，依赖默认 transform-origin，部分屏幕会出现起点偏移。 */}
      {/* 修改后：统一使用 viewBox + width:100% 的响应式 SVG，并显式把旋转原点锁定在几何中心。 */}
      <svg
        viewBox="0 0 100 100"
        style={{ width: "100%", height: "auto", display: "block" }}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Force Score ${clampedScore}`}
      >
        <g
          style={{
            transform: "rotate(-90deg)",
            transformOrigin: "center center",
            transformBox: "fill-box",
          }}
        >
          <circle cx="50" cy="50" r={radius} fill="none" stroke="#E5E7EB" strokeWidth="8" />
          <circle
            cx="50"
            cy="50"
            r={radius}
            fill="none"
            stroke="var(--score-color)"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - clampedScore / 100)}
            className="transition-all duration-700 ease-out"
          />
        </g>
        {/* 修改前：中心分数通过绝对定位 HTML 叠放，缩放后与圆环中心容易出现视觉偏差。 */}
        {/* 修改后：分数文字直接写入 SVG，并使用 dominantBaseline + textAnchor 强制双端居中。 */}
        <text x="50" y="47" fill="#0f172a" fontSize="26" fontWeight="700" textAnchor="middle" dominantBaseline="central">
          {clampedScore}
        </text>
        <text x="50" y="62" fill="#94a3b8" fontSize="11" textAnchor="middle" dominantBaseline="central">
          分
        </text>
      </svg>
    </div>
  );
}
