import { SkillNode } from "../api/client";

type SkillNodeCardProps = {
  node: SkillNode;
  disabled?: boolean;
  actionLabel?: string;
  onClick?: () => void;
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

export default function SkillNodeCard({ node, disabled, actionLabel, onClick }: SkillNodeCardProps) {
  const meta = statusMeta(node.status);
  const unlockedByParent = node.unlocked_by === "parent";
  const consecutive = Math.max(Number((node.unlock_config as { consecutive?: number } | null)?.consecutive ?? 0), 0);
  const progressPct = consecutive > 0 ? Math.min((node.attempt_count / consecutive) * 100, 100) : 0;

  return (
    <div className={`relative flex min-w-[88px] flex-col gap-2 rounded-3xl border-2 p-4 transition-transform ${meta.wrapper}`}>
      <div className={`absolute left-3 top-3 h-3 w-3 rounded-full ${meta.dot}`} />
      <span className="pt-2 text-2xl leading-none">{node.emoji}</span>
      <span className={`text-center text-xs ${meta.title}`}>
        {node.name}
        {unlockedByParent ? " 👑" : ""}
      </span>
      <span className={`text-center text-xs font-medium ${meta.text}`}>{meta.label}</span>

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

      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          disabled={disabled}
          className="mt-2 min-h-[44px] rounded-full bg-white/80 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
