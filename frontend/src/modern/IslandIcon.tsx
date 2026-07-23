type IslandIconProps = {
  name: "home" | "review" | "growth" | "me" | "sun" | "lock" | "arrow";
  className?: string;
};

export default function IslandIcon({ name, className = "" }: IslandIconProps) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 24 24" {...common}>
      {name === "home" ? <><path d="m3 11 9-7 9 7"/><path d="M5.5 10v10h13V10M9 20v-6h6v6"/></> : null}
      {name === "review" ? <><path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h7A2.5 2.5 0 0 1 16 7.5v9A2.5 2.5 0 0 1 13.5 19h-7A2.5 2.5 0 0 1 4 16.5z"/><path d="m16 10 4-2v8l-4-2M8 9.5l4 2.5-4 2.5z"/></> : null}
      {name === "growth" ? <><path d="M4 19V9M10 19V5M16 19v-7M22 19V3"/><path d="m3 7 6-4 6 6 6-7"/></> : null}
      {name === "me" ? <><circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/></> : null}
      {name === "sun" ? <><circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></> : null}
      {name === "lock" ? <><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></> : null}
      {name === "arrow" ? <><path d="m9 18 6-6-6-6"/></> : null}
    </svg>
  );
}
