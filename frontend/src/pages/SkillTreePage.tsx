import axios from "axios";
import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";

import {
  fetchLearningPath,
  fetchSkaters,
  LearningPathResponse,
  LearningPathStage,
  lockSkaterSkill,
  Skater,
  SkillNode,
  unlockSkaterSkill,
} from "../api/client";
import SkillNodeCard from "../components/SkillNodeCard";
import UnlockCelebration from "../components/UnlockCelebration";
import XpProgressBar from "../components/XpProgressBar";
import { useAppMode } from "../components/AppModeContext";
import ZodiacAvatar from "../components/ZodiacAvatar";

type ViewMode = "path" | "roadmap";

const XP_LEVELS = [0, 200, 600, 1500, 3000, 6000, 10000, 16000, 25000, 40000];

function isUnlocked(status: SkillNode["status"]) {
  return status === "unlocked";
}

function skaterLabel(skater: Skater) {
  return skater.display_name || skater.name;
}

function branchTone(chapter: string) {
  if (chapter.startsWith("ss")) {
    return "text-branch-snowplow";
  }
  if (chapter.includes("spin")) {
    return "text-branch-spin";
  }
  if (chapter.includes("basic")) {
    return "text-branch-basic";
  }
  return "text-branch-jump";
}

export default function SkillTreePage() {
  const { isParentMode, enterParentMode } = useAppMode();
  const [viewMode, setViewMode] = useState<ViewMode>("path");
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState("");
  const [path, setPath] = useState<LearningPathResponse | null>(null);
  const deferredPath = useDeferredValue(path);
  const [selectedStage, setSelectedStage] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [mutatingSkillId, setMutatingSkillId] = useState<string | null>(null);
  const [unlockingSkill, setUnlockingSkill] = useState<SkillNode | null>(null);
  const [unlockNote, setUnlockNote] = useState("");
  const [celebrateSkillName, setCelebrateSkillName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (cancelled) {
          return;
        }
        setSkaters(data);
        setSelectedSkaterId((current) => current || data.find((skater) => skater.is_default)?.id || data[0]?.id || "");
      } catch {
        if (!cancelled) {
          setError("练习档案加载失败，请稍后刷新页面。");
          setIsLoading(false);
        }
      }
    };

    void loadSkaters();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedSkaterId) {
      return;
    }

    let cancelled = false;

    const loadPath = async () => {
      setIsLoading(true);
      try {
        const data = await fetchLearningPath(selectedSkaterId);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setPath(data);
          setSelectedStage((current) => current || data.current_stage);
          setError(null);
        });
      } catch {
        if (!cancelled) {
          setError("技能路径加载失败，请稍后重试。");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void loadPath();
    return () => {
      cancelled = true;
    };
  }, [selectedSkaterId]);

  const selectedSkater = skaters.find((skater) => skater.id === selectedSkaterId) ?? null;
  const stageForDetail =
    deferredPath?.stages.find((stage) => stage.stage === selectedStage) ??
    deferredPath?.stages.find((stage) => stage.stage === deferredPath.current_stage) ??
    null;

  const xpProgressPct = useMemo(() => {
    if (!selectedSkater) {
      return 0;
    }
    const currentLevelFloor = XP_LEVELS[Math.max((selectedSkater.avatar_level ?? 1) - 1, 0)] ?? 0;
    const nextLevelTarget = XP_LEVELS[selectedSkater.avatar_level ?? 1] ?? currentLevelFloor;
    if (nextLevelTarget <= currentLevelFloor) {
      return 100;
    }
    return Math.round(((selectedSkater.total_xp - currentLevelFloor) / (nextLevelTarget - currentLevelFloor)) * 100);
  }, [selectedSkater]);

  const reloadPath = async () => {
    if (!selectedSkaterId) {
      return;
    }
    const [nextPath, nextSkaters] = await Promise.all([fetchLearningPath(selectedSkaterId), fetchSkaters()]);
    setPath(nextPath);
    setSkaters(nextSkaters);
  };

  const handleSkillMutation = async (skill: SkillNode) => {
    if (!isParentMode) {
      await enterParentMode();
      return;
    }

    if (!isUnlocked(skill.status)) {
      setUnlockingSkill(skill);
      setUnlockNote("");
      return;
    }

    setMutatingSkillId(skill.id);
    setError(null);
    try {
      await lockSkaterSkill(selectedSkaterId, skill.id);
      await reloadPath();
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "技能状态更新失败，请稍后重试。"));
      } else {
        setError("技能状态更新失败，请稍后重试。");
      }
    } finally {
      setMutatingSkillId(null);
    }
  };

  const handleConfirmUnlock = async () => {
    if (!unlockingSkill) {
      return;
    }

    setMutatingSkillId(unlockingSkill.id);
    setError(null);
    try {
      await unlockSkaterSkill(selectedSkaterId, unlockingSkill.id, unlockNote);
      await reloadPath();
      setCelebrateSkillName(unlockingSkill.name);
      window.setTimeout(() => setCelebrateSkillName(null), 1200);
      setUnlockingSkill(null);
      setUnlockNote("");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "技能状态更新失败，请稍后重试。"));
      } else {
        setError("技能状态更新失败，请稍后重试。");
      }
    } finally {
      setMutatingSkillId(null);
    }
  };

  return (
    <div className="space-y-6">
      <section className="app-card overflow-hidden p-6 tablet:p-8">
        <div className="grid gap-6 web:grid-cols-[1.15fr_0.85fr]">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Skill Path</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">学习路径 + 冰面路线图</h1>
            <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">
              左看阶段进度，右看整张技能图谱。孩子可以清楚看见“正在推进”和“已经点亮”的小目标，家长模式可以补备注并手动点亮。
            </p>
          </div>

          <div className="space-y-4">
            <label className="block space-y-2">
              <span className="text-sm font-medium text-slate-700">当前练习档案</span>
              <select value={selectedSkaterId} onChange={(event) => setSelectedSkaterId(event.target.value)} className="app-select">
                {skaters.map((skater) => (
                  <option key={skater.id} value={skater.id}>
                    {skaterLabel(skater)}
                    {skater.level ? ` · ${skater.level}` : ""}
                  </option>
                ))}
              </select>
            </label>

            {selectedSkater ? (
              <div className="app-card-muted rounded-[28px] p-5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm text-slate-500">成长卡片</p>
                    <div className="mt-2 flex items-center gap-3">
                      <ZodiacAvatar avatarType={selectedSkater.avatar_type} avatarEmoji={selectedSkater.avatar_emoji} size="lg" animate />
                      <h2 className="text-2xl font-semibold text-slate-900">Lv.{selectedSkater.avatar_level}</h2>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-slate-500">当前 XP</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-900">{selectedSkater.total_xp}</p>
                  </div>
                </div>
                <div className="mt-4">
                  <XpProgressBar value={xpProgressPct} />
                </div>
                <p className="mt-3 text-sm text-slate-500">距离下一等级还差 {Math.max((XP_LEVELS[selectedSkater.avatar_level] ?? selectedSkater.total_xp) - selectedSkater.total_xp, 0)} XP</p>
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => setViewMode("path")}
          className={`min-h-[44px] rounded-full px-5 text-sm font-semibold transition ${
            viewMode === "path" ? "bg-blue-500 text-white" : "bg-white text-slate-500 hover:bg-slate-100"
          }`}
        >
          学习路径
        </button>
        <button
          type="button"
          onClick={() => setViewMode("roadmap")}
          className={`min-h-[44px] rounded-full px-5 text-sm font-semibold transition ${
            viewMode === "roadmap" ? "bg-blue-500 text-white" : "bg-white text-slate-500 hover:bg-slate-100"
          }`}
        >
          冰面路线图
        </button>
      </div>

      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      {isLoading || !deferredPath ? (
        <div className="app-card p-6 text-sm text-slate-500">正在加载技能路径...</div>
      ) : viewMode === "path" ? (
        <PathView
          path={deferredPath}
          selectedStage={selectedStage}
          stageForDetail={stageForDetail}
          onSelectStage={setSelectedStage}
          onShowRoadmap={() => setViewMode("roadmap")}
        />
      ) : (
        <RoadmapView
          path={deferredPath}
          isParentMode={isParentMode}
          mutatingSkillId={mutatingSkillId}
          onSkillAction={handleSkillMutation}
        />
      )}

      {unlockingSkill ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/28 px-4 backdrop-blur-sm">
          <section className="app-card w-full max-w-md p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Parent Unlock</p>
            <h2 className="mt-3 text-2xl font-semibold text-slate-900">点亮 {unlockingSkill.name}</h2>
            <p className="mt-3 text-sm leading-7 text-slate-500">可以写一句家长备注，比如“今天教练确认动作稳定”或“连续做对了 3 次”。</p>
            <textarea
              value={unlockNote}
              onChange={(event) => setUnlockNote(event.target.value)}
              rows={4}
              placeholder="备注（可选）"
              className="app-textarea mt-5 min-h-[120px] resize-y"
            />
            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setUnlockingSkill(null)} className="app-pill">
                取消
              </button>
              <button
                type="button"
                onClick={handleConfirmUnlock}
                disabled={mutatingSkillId === unlockingSkill.id}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {mutatingSkillId === unlockingSkill.id ? "点亮中..." : "确认点亮"}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {celebrateSkillName ? <UnlockCelebration label={celebrateSkillName} /> : null}
    </div>
  );
}

function PathView({
  path,
  selectedStage,
  stageForDetail,
  onSelectStage,
  onShowRoadmap,
}: {
  path: LearningPathResponse;
  selectedStage: number | null;
  stageForDetail: LearningPathStage | null;
  onSelectStage: (stage: number) => void;
  onShowRoadmap: () => void;
}) {
  const [selectedNode, setSelectedNode] = useState<SkillNode | null>(null);
  const selectedNodeConsecutive = Math.max(Number((selectedNode?.unlock_config as { consecutive?: number } | null)?.consecutive ?? 0), 0);
  const selectedNodeThreshold = Math.max(Number((selectedNode?.unlock_config as { threshold?: number } | null)?.threshold ?? 0), 0);
  const selectedNodeRemaining = Math.max(selectedNodeConsecutive - Number(selectedNode?.attempt_count ?? 0), 0);

  return (
    <div className="grid gap-6 web:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="app-card p-4 tablet:p-5">
        <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-2 tablet:mx-0 tablet:grid tablet:overflow-visible tablet:px-0 tablet:pb-0 tablet:grid-cols-4 web:grid-cols-1">
          {path.stages.map((stage) => {
            const isCurrent = stage.stage === path.current_stage;
            const isSelected = selectedStage === stage.stage;
            const isCompleted = stage.progress_pct === 100;

            return (
              <button
                key={stage.stage}
                type="button"
                onClick={() => onSelectStage(stage.stage)}
                className={`min-w-[140px] shrink-0 rounded-2xl p-4 text-left transition tablet:min-w-0 ${
                  isSelected || isCurrent
                    ? "border border-blue-100 bg-white shadow-soft"
                    : isCompleted
                      ? "bg-slate-50"
                      : "bg-slate-50/70 hover:bg-slate-100"
                }`}
              >
                <p className={`text-xs font-medium ${isSelected || isCurrent ? "text-blue-500" : "text-slate-400"}`}>阶段 {stage.stage}</p>
                <div className={`mt-2 h-1.5 rounded-full ${isSelected || isCurrent ? "bg-blue-100" : "bg-slate-200"} overflow-hidden`}>
                  <div
                    className={`h-full rounded-full ${isSelected || isCurrent ? "bg-blue-500" : "bg-slate-400"}`}
                    style={{ width: `${stage.progress_pct}%` }}
                  />
                </div>
                <p className={`mt-3 text-xl font-bold ${isSelected || isCurrent ? "text-blue-600" : "text-slate-500"}`}>{stage.progress_pct}%</p>
              </button>
            );
          })}
        </div>
      </aside>

      {stageForDetail ? (
        <section className="space-y-6">
          <div className="app-card p-6 tablet:p-7">
            <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">当前阶段详情</p>
                <h2 className="mt-3 text-2xl font-semibold text-slate-900">
                  阶段 {stageForDetail.stage} · {stageForDetail.name}
                </h2>
                <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">{stageForDetail.description}</p>
              </div>
              <div className="rounded-[28px] bg-blue-50 px-5 py-4 text-center">
                <p className="text-sm text-blue-500">阶段进度</p>
                <p className="mt-2 text-4xl font-semibold text-slate-900">{stageForDetail.progress_pct}%</p>
              </div>
            </div>

            <div className="mt-5">
              <button
                type="button"
                onClick={onShowRoadmap}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
              >
                看已点亮图谱
              </button>
            </div>
          </div>

          <div className="grid gap-4 tablet:grid-cols-3">
            <div className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">未点亮</p>
              <p className="mt-3 text-3xl font-semibold text-slate-900">{stageForDetail.counts.locked ?? 0}</p>
            </div>
            <div className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">推进中</p>
              <p className="mt-3 text-3xl font-semibold text-slate-900">{stageForDetail.counts.attempting ?? 0}</p>
            </div>
            <div className="app-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">已点亮</p>
              <p className="mt-3 text-3xl font-semibold text-slate-900">{stageForDetail.counts.unlocked ?? 0}</p>
            </div>
          </div>

          <div className="app-card p-6 tablet:p-7">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">当前阶段节点</p>
            <div className="mt-5 space-y-6">
              {stageForDetail.groups.map((group) => (
                <section key={group.group_name}>
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-lg font-semibold text-slate-900">{group.group_name}</h3>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">
                      {group.nodes_unlocked}/{group.nodes_total}
                    </span>
                  </div>
                  <div className="mt-4 grid gap-3 grid-cols-3 tablet:grid-cols-4 web:grid-cols-4">
                    {group.nodes.map((node) => (
                      <SkillNodeCard key={node.id} node={node} onClick={node.status === "attempting" ? () => setSelectedNode(node) : undefined} actionLabel={node.status === "attempting" ? "查看详情" : undefined} />
                    ))}
                  </div>
                </section>
              ))}
            </div>

            {selectedNode?.status === "attempting" ? (
              <div className="mt-6 rounded-[28px] border border-orange-200 bg-orange-50 p-5">
                <p className="text-sm font-semibold text-[#F59E0B]">
                  {selectedNode.name} · 🔥 尝试中
                </p>
                <div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-600">
                  <span>最高分：{selectedNode.best_score}</span>
                  <span>目标分：{selectedNodeThreshold}</span>
                </div>
                <p className="mt-2 text-sm text-slate-600">
                  已达标：{selectedNode.attempt_count} / {selectedNodeConsecutive} 次
                </p>
                <p className="mt-2 text-sm font-medium text-orange-500">
                  {selectedNodeRemaining > 0 ? `再来 ${selectedNodeRemaining} 次就能点亮！⭐` : "已经满足点亮条件，等分析同步完成就会更新。"}
                </p>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function RoadmapView({
  path,
  isParentMode,
  mutatingSkillId,
  onSkillAction,
}: {
  path: LearningPathResponse;
  isParentMode: boolean;
  mutatingSkillId: string | null;
  onSkillAction: (skill: SkillNode) => void;
}) {
  const totalNodeCount = path.stages.reduce((sum, stage) => sum + stage.groups.reduce((groupSum, group) => groupSum + group.nodes.length, 0), 0);

  return (
    <section className="app-card p-6 tablet:p-7">
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-end tablet:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Ice Roadmap</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">整张冰面路线图（{totalNodeCount} 个节点）</h2>
          <p className="mt-3 text-sm leading-7 text-slate-500">按阶段和群组展开所有技能节点，手机端为 3 列节点网格，iPad 和网页端会自动扩展到更宽布局。</p>
        </div>
        {!isParentMode ? <p className="text-sm text-slate-500">进入家长模式后可手动点亮或收回节点。</p> : null}
      </div>

      <div className="mt-6 space-y-8">
        {path.stages.map((stage) => (
          <section key={stage.stage} className="rounded-[28px] bg-slate-50 p-4 tablet:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm text-slate-400">阶段 {stage.stage}</p>
                <h3 className="mt-1 text-xl font-semibold text-slate-900">{stage.name}</h3>
              </div>
              <span className="rounded-full bg-white px-4 py-2 text-sm text-slate-500">{stage.progress_pct}%</span>
            </div>

            <div className="mt-5 space-y-5">
              {stage.groups.map((group) => (
                <article key={`${stage.stage}-${group.group_name}`} className="rounded-[24px] bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h4 className="text-base font-semibold text-slate-900">{group.group_name}</h4>
                      <p className={`mt-1 text-sm ${branchTone(group.nodes[0]?.chapter ?? "")}`}>{group.nodes.length} 个节点</p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-500">
                      {group.nodes_unlocked}/{group.nodes_total}
                    </span>
                  </div>

                  <div className="mt-4 grid gap-3 grid-cols-3 tablet:grid-cols-4 web:grid-cols-4">
                    {group.nodes.map((node) => (
                      <SkillNodeCard
                        key={node.id}
                        node={node}
                        disabled={mutatingSkillId === node.id}
                        actionLabel={isUnlocked(node.status) ? "收回点亮" : "手动点亮"}
                        onClick={isParentMode ? () => onSkillAction(node) : undefined}
                      />
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}
