import { Link } from "react-router-dom";

const tools = [
  ["历史记录", "/history"],
  ["AI 追问", "/analysis-chat"],
  ["Golden 标注", "/golden"],
  ["诊断调试", "/debug"],
  ["API 设置", "/settings/api"],
] as const;

export default function AdvancedToolsLinks() {
  return (
    <section className="app-card p-5 tablet:p-6" aria-labelledby="advanced-tools-title">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Advanced</p>
      <h2 id="advanced-tools-title" className="mt-2 text-2xl font-semibold text-slate-900">高级工具</h2>
      <div className="mt-5 grid gap-3 phone:grid-cols-2 tablet:grid-cols-3">
        {tools.map(([label, to]) => (
          <Link key={to} className="app-pill justify-center" to={to}>
            {label}
          </Link>
        ))}
      </div>
    </section>
  );
}
