import { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from "react";

export function IslandCard({ children, className = "", tone = "cream" }: PropsWithChildren<{ className?: string; tone?: "cream" | "mint" | "sky" | "sun" }>) {
  return <section className={`island-card island-card--${tone} ${className}`}>{children}</section>;
}

export function IslandTitle({ children, as = "h2", className = "" }: PropsWithChildren<{ as?: "h1" | "h2" | "h3"; className?: string }>) {
  const Tag = as;
  return <Tag className={`island-title ${className}`}><span>{children}</span></Tag>;
}

export function IslandButton({ children, className = "", variant = "primary", ...props }: PropsWithChildren<ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "quiet" }>) {
  return <button className={`island-button island-button--${variant} ${className}`} {...props}>{children}</button>;
}

export function IslandPageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <header className="island-page-header">
      <div className="min-w-0">
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {action ? <div className="island-page-header__action">{action}</div> : null}
    </header>
  );
}
