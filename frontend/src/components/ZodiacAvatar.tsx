import type { CSSProperties } from "react";

import type { AvatarType } from "../api/client";

interface ZodiacAvatarProps {
  avatarType: AvatarType;
  avatarEmoji?: string;
  size?: "sm" | "md" | "lg" | "xl";
  animate?: boolean;
  className?: string;
}

const SIZE_MAP: Record<NonNullable<ZodiacAvatarProps["size"]>, number> = {
  sm: 32,
  md: 48,
  lg: 96,
  xl: 120,
};

function joinClasses(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function RatAvatarSvg({ size }: { size: number }) {
  return (
    <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id="rat-body" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#F5E6C8" />
          <stop offset="100%" stopColor="#D4C4A8" />
        </linearGradient>
      </defs>
      <path d="M98 76c9 4 12 15 7 22" fill="none" stroke="#CFAF82" strokeWidth="4" strokeLinecap="round" />
      <path d="M104 98c2 2 2 5-1 7" fill="none" stroke="#CFAF82" strokeWidth="3" strokeLinecap="round" />
      <ellipse cx="35" cy="34" rx="14" ry="14" fill="#F5E6C8" />
      <ellipse cx="85" cy="34" rx="14" ry="14" fill="#F5E6C8" />
      <ellipse cx="35" cy="36" rx="8" ry="8" fill="rgba(244,160,176,0.6)" />
      <ellipse cx="85" cy="36" rx="8" ry="8" fill="rgba(244,160,176,0.6)" />
      <ellipse cx="60" cy="62" rx="31" ry="30" fill="url(#rat-body)" />
      <ellipse cx="60" cy="68" rx="22" ry="18" fill="#EFE4D1" />
      <path d="M46 47c2-4 7-6 12-5" fill="none" stroke="#6E4E3A" strokeWidth="3" strokeLinecap="round" />
      <path d="M74 42c5-1 10 1 12 5" fill="none" stroke="#6E4E3A" strokeWidth="3" strokeLinecap="round" />
      <circle cx="48" cy="55" r="3.5" fill="#2F2A26" />
      <circle cx="72" cy="55" r="3.5" fill="#2F2A26" />
      <ellipse cx="60" cy="64" rx="6" ry="5" fill="#F6B3BC" />
      <path d="M54 70c4 3 8 3 12 0" fill="none" stroke="#8C5A48" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M44 85c2 11 9 18 16 18s14-7 16-18" fill="#D9DDE8" opacity="0.55" />
      <path d="M39 87c0 9 5 16 11 16 5 0 10-7 10-16" fill="#2C3E7A" />
      <path d="M60 87c0 9 5 16 10 16 6 0 11-7 11-16" fill="#2C3E7A" />
      <path d="M40 101h20" stroke="#C0C0C0" strokeWidth="3" strokeLinecap="round" />
      <path d="M60 101h20" stroke="#C0C0C0" strokeWidth="3" strokeLinecap="round" />
      <path d="M42 105h18" stroke="#AEB7C5" strokeWidth="2" strokeLinecap="round" />
      <path d="M60 105h18" stroke="#AEB7C5" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function TigerAvatarSvg({ size }: { size: number }) {
  return (
    <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id="tiger-body" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#F7B236" />
          <stop offset="100%" stopColor="#F08F1F" />
        </linearGradient>
      </defs>
      <ellipse cx="38" cy="34" rx="10" ry="10" fill="#F5A623" />
      <ellipse cx="82" cy="34" rx="10" ry="10" fill="#F5A623" />
      <ellipse cx="60" cy="62" rx="31" ry="30" fill="url(#tiger-body)" />
      <ellipse cx="60" cy="71" rx="20" ry="16" fill="#FAFAFA" />
      <path d="M53 36h14" stroke="#1C1C1C" strokeWidth="4" strokeLinecap="round" />
      <path d="M60 31v12" stroke="#1C1C1C" strokeWidth="4" strokeLinecap="round" />
      <path d="M44 45l7 6" stroke="#1C1C1C" strokeWidth="4" strokeLinecap="round" />
      <path d="M76 45l-7 6" stroke="#1C1C1C" strokeWidth="4" strokeLinecap="round" />
      <path d="M46 46c2-3 7-4 12-2" fill="none" stroke="#2B211C" strokeWidth="3" strokeLinecap="round" />
      <path d="M74 44c4-2 9-1 12 2" fill="none" stroke="#2B211C" strokeWidth="3" strokeLinecap="round" />
      <circle cx="49" cy="55" r="3.5" fill="#1F1714" />
      <circle cx="71" cy="55" r="3.5" fill="#1F1714" />
      <path d="M55 66h10" stroke="#DA7F19" strokeWidth="5" strokeLinecap="round" />
      <path d="M54 72c4 2 8 2 12 0" fill="none" stroke="#7C3F16" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M42 85c2 11 9 18 16 18s14-7 16-18" fill="#D9DDE8" opacity="0.55" />
      <path d="M39 87c0 9 5 16 11 16 5 0 10-7 10-16" fill="#2C3E7A" />
      <path d="M60 87c0 9 5 16 10 16 6 0 11-7 11-16" fill="#2C3E7A" />
      <path d="M40 101h20" stroke="#C0C0C0" strokeWidth="3" strokeLinecap="round" />
      <path d="M60 101h20" stroke="#C0C0C0" strokeWidth="3" strokeLinecap="round" />
      <path d="M42 105h18" stroke="#AEB7C5" strokeWidth="2" strokeLinecap="round" />
      <path d="M60 105h18" stroke="#AEB7C5" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function EmojiAvatar({ emoji, size }: { emoji: string; size: number }) {
  return (
    <div
      aria-hidden="true"
      className="flex items-center justify-center rounded-full bg-gradient-to-br from-slate-100 to-slate-200 text-center shadow-sm"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.56) }}
    >
      {emoji}
    </div>
  );
}

export default function ZodiacAvatar({
  avatarType,
  avatarEmoji = "⛸️",
  size = "md",
  animate = false,
  className,
}: ZodiacAvatarProps) {
  const pixels = SIZE_MAP[size];
  const style = { width: pixels, height: pixels } satisfies CSSProperties;

  return (
    <div className={joinClasses("inline-flex shrink-0 items-center justify-center", animate && "animate-avatar-bounce", className)} style={style}>
      {avatarType === "zodiac_rat" ? <RatAvatarSvg size={pixels} /> : null}
      {avatarType === "zodiac_tiger" ? <TigerAvatarSvg size={pixels} /> : null}
      {avatarType === "emoji" ? <EmojiAvatar emoji={avatarEmoji} size={pixels} /> : null}
    </div>
  );
}
