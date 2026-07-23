type IslandIconProps = {
  name: "home" | "review" | "growth" | "me" | "sun" | "lock" | "arrow";
  className?: string;
};

export default function IslandIcon({ name, className = "" }: IslandIconProps) {
  if (name === "home" || name === "review" || name === "growth" || name === "me") {
    return (
      <img
        aria-hidden="true"
        className={`island-art-icon ${className}`.trim()}
        src={`/modern-island/icon-${name}.svg`}
      />
    );
  }

  const common = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 24 24" {...common}>
      {name === "sun" ? <><circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></> : null}
      {name === "lock" ? <><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></> : null}
      {name === "arrow" ? <><path d="m9 18 6-6-6-6"/></> : null}
    </svg>
  );
}
