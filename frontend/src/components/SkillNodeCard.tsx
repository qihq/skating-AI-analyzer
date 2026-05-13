import type { KeyboardEvent } from "react";

import { SkillNode } from "../api/client";

type SkillNodeCardProps = {
  node: SkillNode;
  disabled?: boolean;
  actionLabel?: string;
  onClick?: () => void;
  highlightTone?: "default" | "focus";
};

function isUnlocked(status: SkillNode["status"]) {
  return status === "unlocked";
}

function statusMeta(status: SkillNode["status"]) {
  if (isUnlocked(status)) {
    return {
      label: "已点亮",
      wrapper: "bg-[var(--node-unlocked-bg)] border-[#4CAF50]/30",
      dot: "bg-[var(--node-unlocked-dot)]",
      text: "text-[#4CAF50]",
      title: "text-slate-700 font-bold",
    };
  }

  if (status === "attempting") {
    return {
      label: "🔥 尝试中",
      wrapper: "bg-[var(--node-inprogress-bg)] border-[#F59E0B]/30",
      dot: "bg-[var(--node-inprogress-dot)]",
      text: "text-[#F59E0B]",
      title: "text-slate-700 font-bold",
    };
  }

  return {
    label: "未开始",
    wrapper: "bg-[var(--node-locked-bg)] border-slate-200 opacity-80",
    dot: "bg-[var(--node-locked-dot)]",
    text: "text-slate-400",
    title: "text-slate-400 font-medium",
  };
}

export default function SkillNodeCard({ node, disabled, actionLabel, onClick, highlightTone = "default" }: SkillNodeCardProps) {
  const meta = statusMeta(node.status);
  const unlockedByParent = node.unlocked_by === "parent";
  const consecutive = Math.max(Number((node.unlock_config as { consecutive?: number } | null)?.consecutive ?? 0), 0);
  const progressPct = consecutive > 0 ? Math.min((node.attempt_count / consecutive) * 100, 100) : 0;
  const highlightClass = highlightTone === "focus" ? "border-[#FACC15] shadow-[0_16px_32px_rgba(250,204,21,0.22)]" : "";
  const isInteractive = Boolean(onClick) && !disabled;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!isInteractive || !onClick) {
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onClick();
    }
  };

  return (
    <div
      className={`relative flex min-w-0 flex-col gap-2 rounded-3xl border-2 p-3 transition-transform phone:p-4 ${meta.wrapper} ${highlightClass} ${
        isInteractive ? "cursor-pointer hover:-translate-y-0.5 hover:shadow-[0_16px_36px_rgba(15,23,42,0.12)] focus:outline-none focus:ring-2 focus:ring-blue-300 focus:ring-offset-2" : ""
      } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
      onClick={isInteractive ? onClick : undefined}
      onKeyDown={isInteractive ? handleKeyDown : undefined}
      role={isInteractive ? "button" : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      aria-disabled={disabled || undefined}
    >
      <div className={`absolute left-3 top-3 h-3 w-3 rounded-full ${meta.dot}`} />
      <span className="pt-2 text-xl leading-none phone:text-2xl">{node.emoji}</span>
      <span className={`break-words text-center text-[11px] leading-5 phone:text-xs ${meta.title}`}>
        {node.name}
        {unlockedByParent ? " 👑" : ""}
      </span>
      <span className={`break-words text-center text-[11px] font-medium leading-5 phone:text-xs ${meta.text}`}>{meta.label}</span>

      {node.status === "attempting" && consecutive > 0 ? (
        <>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-orange-100">
            <div className="h-full rounded-full bg-[#F59E0B]" style={{ width: `${progressPct}%` }} />
          </div>
          <span className="text-center text-[10px] text-orange-400">
            {node.attempt_count}/{consecutive} 次
          </span>
        </>
      ) : null}

      {node.unlock_note ? <span className="text-center text-[11px] leading-5 text-slate-500">{node.unlock_note}</span> : null}
      {typeof node.last_analysis_score === "number" ? (
        <span className="mt-auto break-words text-center text-[11px] leading-5 text-slate-500">上次得分：{node.last_analysis_score}分</span>
      ) : null}

      {actionLabel ? (
        <span
          className={`mt-2 inline-flex min-h-[40px] items-center justify-center rounded-full px-2 py-2 text-center text-[11px] font-semibold leading-5 transition phone:min-h-[44px] phone:px-3 phone:text-xs ${
            isInteractive ? "bg-white/80 text-slate-700" : "bg-white/50 text-slate-400"
          }`}
        >
          {actionLabel}
        </span>
      ) : null}
    </div>
  );
}
