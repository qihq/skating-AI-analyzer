import { PropsWithChildren } from "react";

type ReportCardProps = PropsWithChildren<{
  title: string;
  eyebrow?: string;
  className?: string;
}>;

export default function ReportCard({ title, eyebrow, className = "", children }: ReportCardProps) {
  return (
    <section className={`app-card p-6 tablet:p-7 ${className}`}>
      <div className="mb-5">
        {eyebrow ? <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">{eyebrow}</p> : null}
        <h2 className="mt-2 text-xl font-semibold text-slate-900">{title}</h2>
      </div>
      {children}
    </section>
  );
}
