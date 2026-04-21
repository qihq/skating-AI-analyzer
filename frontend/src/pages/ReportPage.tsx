import axios from "axios";
import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer } from "recharts";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  AnalysisDetail,
  createPlan,
  deleteAnalysis,
  dismissMemorySuggestion,
  fetchAnalysis,
  fetchAnalysisPlan,
  fetchAnalysisPose,
  fetchMemorySuggestions,
  fetchSkaterSkills,
  fetchSkaters,
  MemorySuggestion,
  PoseResponse,
  Skater,
  SkillNode,
} from "../api/client";
import BiomechanicsPanel from "../components/BiomechanicsPanel";
import DeleteAnalysisModal from "../components/DeleteAnalysisModal";
import ForceScoreRing from "../components/ForceScoreRing";
import PoseViewer from "../components/PoseViewer";
import ReportCard from "../components/ReportCard";
import UnlockCelebration from "../components/UnlockCelebration";
import { useAppMode } from "../components/AppModeContext";
import ZodiacAvatar from "../components/ZodiacAvatar";

const STATUS_TEXT: Record<string, string> = {
  pending: "冰宝（IceBuddy）已收到视频，正在准备分析环境…",
  processing: "冰宝（IceBuddy）正在分析，通常需要 1-2 分钟…",
};

const ISSUE_STYLES: Record<string, string> = {
  high: "border-rose-200 bg-rose-50",
  medium: "border-amber-200 bg-amber-50",
  low: "border-sky-200 bg-sky-50",
};

const SUBSCORE_LABELS: Record<string, string> = {
  takeoff_power: "起跳发力",
  rotation_axis: "旋转轴心",
  arm_coordination: "手臂配合",
  landing_absorption: "落冰缓冲",
  core_stability: "核心稳定",
};

const DATA_QUALITY_LABELS: Record<string, string> = {
  good: "完整",
  partial: "部分可用",
  poor: "较弱",
};

type SuggestionPreview = {
  suggestionId: string;
  index: number;
  title: string;
};

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateString));
}

function buildSubscoreRadarData(subscores: Record<string, number>) {
  return Object.entries(SUBSCORE_LABELS).map(([key, label]) => ({
    label,
    value: Math.max(0, Math.min(Number(subscores[key] ?? 0), 100)),
  }));
}

function flattenSuggestionPreview(items: MemorySuggestion[]): SuggestionPreview[] {
  return items.flatMap((item) =>
    item.suggestions.map((suggestion, index) => {
      const action = String(suggestion.action ?? "").toLowerCase();
      if (action === "add") {
        return {
          suggestionId: item.id,
          index,
          title: String(suggestion.title ?? "发现新记忆"),
        };
      }
      if (action === "update") {
        return {
          suggestionId: item.id,
          index,
          title: String(suggestion.title ?? "建议更新已有记忆"),
        };
      }
      return {
        suggestionId: item.id,
        index,
        title: "建议设为过期",
      };
    }),
  );
}

function LoadingState({ status }: { status: string }) {
  return (
    <div className="app-card mx-auto max-w-2xl p-10 text-center">
      <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-blue-50 text-4xl animate-pulse">🎬</div>
      <h2 className="mt-6 text-3xl font-semibold text-slate-900">视频分析进行中</h2>
      <p className="mt-4 text-base text-slate-500">{STATUS_TEXT[status] ?? STATUS_TEXT.processing}</p>
      <div className="mx-auto mt-8 h-2 w-56 overflow-hidden rounded-full bg-slate-100">
        <div className="animate-shimmer h-full w-1/2 rounded-full bg-blue-500" />
      </div>
    </div>
  );
}

function FailedState({ message }: { message: string | null }) {
  return (
    <div className="app-card border border-rose-200 bg-rose-50 p-8 text-rose-600">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-rose-400">分析失败</p>
      <h2 className="mt-3 text-2xl font-semibold text-rose-600">这次报告没有成功生成</h2>
      <p className="mt-4 text-base leading-7">{message ?? "请稍后重试，或检查 AI 供应商配置。"}</p>
    </div>
  );
}

function ForceScoreStars({ score }: { score: number }) {
  const stars = score >= 85 ? 5 : score >= 70 ? 4 : score >= 56 ? 3 : score >= 40 ? 2 : 1;
  const encouragements = [
    "继续加油，你做到了！💪",
    "不错哦，再练几次就更好了！",
    "今天的动作有进步！⭐",
    "超棒！冰宝（IceBuddy）为你骄傲！🎉",
    "完美！你是冰上小明星！🌟",
  ];

  return (
    <div className="flex w-full max-w-[240px] flex-col items-center gap-2">
      <div className="flex flex-wrap justify-center gap-1 text-[clamp(1.9rem,3vw,3rem)] leading-none">
        {Array.from({ length: 5 }).map((_, index) => (
          <span key={index}>{index < stars ? "⭐" : "☆"}</span>
        ))}
      </div>
      <p className="max-w-[240px] text-center text-base font-bold leading-7 text-[#6C63FF] tablet:text-lg">{encouragements[stars - 1]}</p>
    </div>
  );
}

function ForceScoreCard({ score, isParentMode }: { score: number; isParentMode: boolean }) {
  const normalized = Math.max(0, Math.min(Math.round(score), 100));
  const levelText = normalized >= 85 ? "状态很稳" : normalized >= 70 ? "表现不错" : normalized >= 56 ? "持续进步中" : "继续找感觉";

  return (
    <div className="w-full max-w-[280px] rounded-[30px] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-blue-50 p-5 shadow-[0_18px_50px_rgba(15,23,42,0.08)]">
      <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Force Score</p>
      <div className="mt-4 flex flex-col items-center gap-4 tablet:items-start">
        <ForceScoreStars score={normalized} />
        <div className="flex w-full items-center gap-4 rounded-[24px] border border-white/80 bg-white/90 px-4 py-3">
          <ForceScoreRing score={normalized} sizeClassName="h-20 w-20 tablet:h-20 tablet:w-20" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-900">{levelText}</p>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              {isParentMode ? "家长模式同时保留星级感知和量化得分。" : "儿童模式优先展示直观的星级反馈。"}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { isParentMode, enterParentMode, pinLength } = useAppMode();
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [skills, setSkills] = useState<SkillNode[]>([]);
  const [pose, setPose] = useState<PoseResponse | null>(null);
  const [selectedPoseFrame, setSelectedPoseFrame] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [isCreatingPlan, setIsCreatingPlan] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [deleteStep, setDeleteStep] = useState<"confirm" | "pin">("confirm");
  const [deletePin, setDeletePin] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [celebrateSkillName, setCelebrateSkillName] = useState<string | null>(null);
  const [celebratedSkillId, setCelebratedSkillId] = useState<string | null>(null);
  const [memorySuggestions, setMemorySuggestions] = useState<MemorySuggestion[]>([]);
  const [isSuggestionLoading, setIsSuggestionLoading] = useState(false);
  const [isSuggestionMutating, setIsSuggestionMutating] = useState(false);
  const deferredAnalysis = useDeferredValue(analysis);
  const subscores = deferredAnalysis?.report?.subscores ?? deferredAnalysis?.bio_data?.bio_subscores ?? null;
  const reportDataQuality = deferredAnalysis?.report?.data_quality ?? "partial";
  const hasReliableSubscores = reportDataQuality === "good" && Boolean(subscores);
  const reportSkater = skaters.find((item) => item.id === deferredAnalysis?.skater_id) ?? null;
  const autoUnlockedSkill = skills.find((item) => item.id === deferredAnalysis?.auto_unlocked_skill) ?? null;
  const flattenedSuggestions = useMemo(() => flattenSuggestionPreview(memorySuggestions), [memorySuggestions]);

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (!cancelled) {
          setSkaters(data);
        }
      } catch {
        if (!cancelled) {
          setSkaters([]);
        }
      }
    };

    void loadSkaters();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!deferredAnalysis?.skater_id) {
      setSkills([]);
      return;
    }

    let cancelled = false;
    const loadSkills = async () => {
      try {
        const skaterId = deferredAnalysis.skater_id;
        if (!skaterId) {
          return;
        }
        const data = await fetchSkaterSkills(skaterId);
        if (!cancelled) {
          setSkills(data);
        }
      } catch {
        if (!cancelled) {
          setSkills([]);
        }
      }
    };

    void loadSkills();
    return () => {
      cancelled = true;
    };
  }, [deferredAnalysis?.skater_id]);

  useEffect(() => {
    if (!deferredAnalysis?.auto_unlocked_skill || celebratedSkillId === deferredAnalysis.auto_unlocked_skill) {
      return;
    }

    const label = autoUnlockedSkill?.name ?? deferredAnalysis.skill_category ?? "新技能";
    setCelebrateSkillName(label);
    setCelebratedSkillId(deferredAnalysis.auto_unlocked_skill);
    const timer = window.setTimeout(() => setCelebrateSkillName(null), 1400);
    return () => window.clearTimeout(timer);
  }, [autoUnlockedSkill?.name, celebratedSkillId, deferredAnalysis?.auto_unlocked_skill, deferredAnalysis?.skill_category]);

  useEffect(() => {
    if (!id) {
      setError("无效的报告 ID。");
      return;
    }

    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      try {
        const data = await fetchAnalysis(id);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setAnalysis(data);
          setError(null);
        });

        if (data.status === "pending" || data.status === "processing") {
          timer = window.setTimeout(load, 3000);
        }
      } catch {
        if (!cancelled) {
          setError("报告加载失败，请稍后刷新页面。");
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [id]);

  useEffect(() => {
    if (!id || analysis?.status !== "completed") {
      return;
    }

    let cancelled = false;
    const loadPlan = async () => {
      try {
        const data = await fetchAnalysisPlan(id);
        if (!cancelled) {
          setPlanId(data.id);
        }
      } catch (requestError) {
        if (axios.isAxiosError(requestError) && requestError.response?.status === 404) {
          if (!cancelled) {
            setPlanId(null);
          }
          return;
        }
        if (!cancelled) {
          setError("训练计划状态加载失败，请稍后重试。");
        }
      }
    };

    void loadPlan();
    return () => {
      cancelled = true;
    };
  }, [analysis?.status, id]);

  useEffect(() => {
    if (!id || analysis?.status !== "completed") {
      return;
    }

    let cancelled = false;
    const loadPose = async () => {
      try {
        const data = await fetchAnalysisPose(id);
        if (!cancelled) {
          setPose(data);
        }
      } catch {
        if (!cancelled) {
          setPose(null);
        }
      }
    };

    void loadPose();
    return () => {
      cancelled = true;
    };
  }, [analysis?.status, id]);

  useEffect(() => {
    if (!isParentMode || deferredAnalysis?.status !== "completed" || !deferredAnalysis.skater_id) {
      setMemorySuggestions([]);
      return;
    }

    let cancelled = false;
    const loadSuggestions = async () => {
      setIsSuggestionLoading(true);
      try {
        const skaterId = deferredAnalysis.skater_id;
        if (!skaterId) {
          return;
        }
        const data = await fetchMemorySuggestions(skaterId);
        if (!cancelled) {
          setMemorySuggestions(data);
        }
      } catch {
        if (!cancelled) {
          setMemorySuggestions([]);
        }
      } finally {
        if (!cancelled) {
          setIsSuggestionLoading(false);
        }
      }
    };

    void loadSuggestions();
    return () => {
      cancelled = true;
    };
  }, [deferredAnalysis?.skater_id, deferredAnalysis?.status, isParentMode]);

  const handleCreatePlan = async () => {
    if (!id) {
      return;
    }
    setIsCreatingPlan(true);
    setError(null);
    try {
      const plan = await createPlan(id);
      setPlanId(plan.id);
      navigate(`/plan/${plan.id}`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "训练计划生成失败，请稍后重试。"));
      } else {
        setError("训练计划生成失败，请稍后重试。");
      }
    } finally {
      setIsCreatingPlan(false);
    }
  };

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2400);
  };

  const openDeleteModal = () => {
    setDeleteStep("confirm");
    setDeletePin("");
    setDeleteError(null);
    setIsDeleteModalOpen(true);
  };

  const closeDeleteModal = () => {
    setIsDeleteModalOpen(false);
    setDeleteStep("confirm");
    setDeletePin("");
    setDeleteError(null);
    setIsDeleting(false);
  };

  const handleDeleteAnalysis = async () => {
    if (!id) {
      return;
    }

    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteAnalysis(id, deletePin);
      closeDeleteModal();
      navigate("/archive", { state: { notice: "已删除这条分析记录" } });
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setDeleteError(String(requestError.response?.data?.detail ?? "删除失败，请稍后重试。"));
      } else {
        setDeleteError("删除失败，请稍后重试。");
      }
      setIsDeleting(false);
    }
  };

  const handleDismissSuggestions = async () => {
    if (!deferredAnalysis?.skater_id || !memorySuggestions.length) {
      return;
    }

    setIsSuggestionMutating(true);
    try {
      const skaterId = deferredAnalysis.skater_id;
      if (!skaterId) {
        return;
      }
      await Promise.all(memorySuggestions.map((item) => dismissMemorySuggestion(skaterId, item.id)));
      setMemorySuggestions([]);
      showNotice("这批记忆建议已忽略。");
    } catch {
      setError("记忆建议处理失败，请稍后再试。");
    } finally {
      setIsSuggestionMutating(false);
    }
  };

  const handleViewSuggestions = async () => {
    if (!deferredAnalysis?.skater_id) {
      return;
    }
    if (!isParentMode) {
      await enterParentMode();
      return;
    }
    navigate("/snowball", {
      state: {
        focusSkaterId: deferredAnalysis.skater_id,
        focusSuggestions: true,
      },
    });
  };

  const canDeleteAnalysis = deferredAnalysis?.status === "completed" || deferredAnalysis?.status === "failed";
  const deleteDisabled = !deferredAnalysis || !canDeleteAnalysis;
  const deleteTitle =
    deferredAnalysis?.status === "processing"
      ? "分析进行中，无法删除"
      : deleteDisabled
        ? "当前状态暂不支持删除"
        : "删除这条分析记录";

  return (
    <div className="space-y-6">
      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to="/review" className="app-pill">
          ← 返回复盘
        </Link>
        <div className="flex flex-wrap gap-3">
          {isParentMode ? (
            <button
              type="button"
              onClick={openDeleteModal}
              disabled={deleteDisabled}
              title={deleteTitle}
              className="min-h-[44px] rounded-full border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              🗑️ 删除
            </button>
          ) : null}
          <Link to="/archive" className="app-pill">
            查看练习档案
          </Link>
          {planId ? (
            <Link to={`/plan/${planId}`} className="min-h-[44px] rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600">
              查看 7 天训练计划
            </Link>
          ) : (
            <button
              type="button"
              onClick={handleCreatePlan}
              disabled={!deferredAnalysis || deferredAnalysis.status !== "completed" || isCreatingPlan}
              className="min-h-[44px] rounded-full bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isCreatingPlan ? "正在生成训练计划..." : "生成 7 天训练计划"}
            </button>
          )}
        </div>
      </div>

      {error ? <div className="rounded-[24px] bg-rose-50 px-5 py-4 text-sm text-rose-500">{error}</div> : null}

      {!deferredAnalysis ? (
        <LoadingState status="processing" />
      ) : deferredAnalysis.status === "failed" ? (
        <FailedState message={deferredAnalysis.error_message} />
      ) : deferredAnalysis.status !== "completed" ? (
        <LoadingState status={deferredAnalysis.status} />
      ) : (
        <>
          {deferredAnalysis.report?.data_quality === "poor" ? (
            <div className="rounded-[28px] border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-7 text-amber-700">
              当前视频可能存在人物过小、遮挡、模糊或关键帧不足，报告已尽量保守分析。建议用更近、更稳定的角度重新拍摄后复盘。
            </div>
          ) : null}

          <section className="app-card overflow-hidden p-6 tablet:p-8">
            <div className="grid gap-6 tablet:grid-cols-[minmax(220px,240px)_1fr] tablet:items-center web:gap-8">
              <div className="flex justify-center tablet:justify-start">
                <ForceScoreCard score={deferredAnalysis.force_score ?? 0} isParentMode={isParentMode} />
              </div>

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">诊断报告</p>
                <h1 className="text-3xl font-semibold text-slate-900 tablet:text-4xl">{deferredAnalysis.action_type}</h1>
                {reportSkater ? (
                  <div className="flex w-fit items-center gap-3 rounded-[24px] bg-slate-50 px-4 py-3">
                    <ZodiacAvatar avatarType={reportSkater.avatar_type} avatarEmoji={reportSkater.avatar_emoji} size="md" />
                    <span className="text-sm font-medium text-slate-700">{reportSkater.display_name || reportSkater.name}</span>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-3 text-sm text-slate-500">
                  <span>{formatDate(deferredAnalysis.created_at)}</span>
                  {deferredAnalysis.skater_name ? <span>练习档案：{deferredAnalysis.skater_name}</span> : null}
                  {deferredAnalysis.skill_category ? <span>技能分类：{deferredAnalysis.skill_category}</span> : null}
                </div>
                {isParentMode && deferredAnalysis.action_window_start != null && deferredAnalysis.action_window_end != null ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    <span>
                      分析窗口：{deferredAnalysis.action_window_start.toFixed(1)}s - {deferredAnalysis.action_window_end.toFixed(1)}s
                    </span>
                    {deferredAnalysis.is_slow_motion ? (
                      <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[10px] font-bold text-orange-600">
                        慢动作 {Math.round(deferredAnalysis.source_fps ?? 0)}fps
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {deferredAnalysis.note ? (
                  <div className="rounded-[24px] bg-slate-50 px-5 py-4 text-sm leading-7 text-slate-600">
                    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">补充说明</p>
                    <p className="mt-2">{deferredAnalysis.note}</p>
                  </div>
                ) : null}
              </div>
            </div>
          </section>

          <div className="grid gap-6 web:grid-cols-[1.08fr_0.92fr]">
            <div className="space-y-6">
              <ReportCard title="总体评价" eyebrow="Summary">
                <p className="max-w-3xl text-base leading-8 text-slate-600">{deferredAnalysis.report?.summary ?? "暂无总体评价。"}</p>
              </ReportCard>

              {subscores || reportDataQuality !== "good" ? (
                <ReportCard title="分项评分" eyebrow="Subscores">
                  {hasReliableSubscores && subscores ? (
                    <div className="grid gap-6 ipad:grid-cols-[1fr_1fr] web:grid-cols-1">
                      <div className="h-64 overflow-hidden rounded-[28px] border border-slate-200 bg-slate-50">
                        <ResponsiveContainer width="100%" height="100%">
                          <RadarChart data={buildSubscoreRadarData(subscores)}>
                            <PolarGrid stroke="rgba(148,163,184,0.25)" />
                            <PolarAngleAxis dataKey="label" tick={{ fill: "#64748b", fontSize: 12 }} />
                            <Radar dataKey="value" stroke="#3B82F6" fill="#60A5FA" fillOpacity={0.28} dot={{ fill: "#1D4ED8", r: 3 }} />
                          </RadarChart>
                        </ResponsiveContainer>
                      </div>

                      <div className="grid gap-3 sm:grid-cols-2">
                        {Object.entries(subscores).map(([key, value]) => (
                          <article key={key} className="rounded-[24px] bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">{SUBSCORE_LABELS[key] ?? key}</p>
                            <p className="mt-3 text-2xl font-semibold text-slate-900">{value}</p>
                          </article>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="grid gap-6 ipad:grid-cols-[1fr_1fr] web:grid-cols-1">
                      <div className="relative h-64 overflow-hidden rounded-[28px] border border-slate-200 bg-slate-100">
                        <div className="absolute inset-0 opacity-60 [background-image:radial-gradient(circle_at_center,rgba(148,163,184,0.14)_0,rgba(148,163,184,0.14)_1px,transparent_1px)] [background-size:28px_28px]" />
                        <div className="absolute inset-6 rounded-full border border-dashed border-slate-300" />
                        <div className="absolute inset-[20%] rounded-full border border-dashed border-slate-300" />
                        <div className="absolute inset-[34%] rounded-full border border-dashed border-slate-300" />
                        <div className="absolute inset-0 flex items-center justify-center">
                          <span className="rounded-full bg-white/90 px-4 py-2 text-sm font-medium text-slate-500 shadow-sm">
                            雷达图已隐藏
                          </span>
                        </div>
                      </div>

                      <article className="flex min-h-64 flex-col justify-center rounded-[24px] border border-slate-200 bg-slate-50 p-6 text-center sm:text-left">
                        <p className="text-lg font-semibold text-slate-900">数据有限，暂不提供可靠分项评分</p>
                        <p className="mt-3 text-sm leading-7 text-slate-500">
                          当前视频关键帧不足，或识别稳定性不够，继续展示五项数字容易造成误导。建议补拍更近、更稳、更完整的视频后再查看分项评分。
                        </p>
                      </article>
                    </div>
                  )}

                  <p className="mt-4 text-sm text-slate-500">
                    数据质量：
                    {DATA_QUALITY_LABELS[reportDataQuality] ?? reportDataQuality}
                  </p>
                </ReportCard>
              ) : null}

              {pose?.frames?.length ? (
                <ReportCard title="姿态回放与生物力学" eyebrow="Pose Replay">
                  <PoseViewer pose={pose} activeFrameId={selectedPoseFrame} onFrameChange={setSelectedPoseFrame} />
                  {deferredAnalysis.bio_data ? (
                    <div className="mt-5">
                      <BiomechanicsPanel bioData={deferredAnalysis.bio_data} mode={isParentMode ? "parent" : "child"} onSelectFrame={setSelectedPoseFrame} />
                    </div>
                  ) : null}
                </ReportCard>
              ) : null}
            </div>

            <div className="space-y-6">
              {!isParentMode ? (
                <>
                  <ReportCard title="冰宝提醒" eyebrow="Simple View">
                    <div className="space-y-4">
                      {(deferredAnalysis.report?.improvements?.slice(0, 3) ?? []).map((improvement, index) => (
                        <article key={`${improvement.target}-${index}`} className="rounded-[24px] bg-slate-50 p-4">
                          <p className="text-sm font-semibold text-blue-500">{improvement.target}</p>
                          <p className="mt-2 text-sm leading-7 text-slate-600">{improvement.action}</p>
                        </article>
                      ))}
                      {!deferredAnalysis.report?.improvements?.length ? <p className="text-sm text-slate-500">今天表现很棒，继续保持稳定节奏。</p> : null}
                    </div>
                  </ReportCard>

                  <ReportCard title="今天先记住这一点" eyebrow="Focus" className="border border-blue-100 bg-blue-50/60">
                    <p className="text-lg leading-8 text-slate-700">{deferredAnalysis.report?.training_focus ?? "先把动作做稳，再慢慢加速度。"}
                    </p>
                    <button type="button" onClick={() => void enterParentMode()} className="app-pill mt-5">
                      家长模式查看完整报告
                    </button>
                  </ReportCard>
                </>
              ) : (
                <>
                  <ReportCard title="问题列表" eyebrow="Issues">
                    <div className="space-y-4">
                      {deferredAnalysis.report?.issues?.length ? (
                        deferredAnalysis.report.issues.map((issue, index) => (
                          <article key={`${issue.category}-${index}`} className={`rounded-[24px] border p-4 ${ISSUE_STYLES[issue.severity] ?? ISSUE_STYLES.low}`}>
                            <div className="flex items-center justify-between gap-3">
                              <h3 className="text-base font-semibold text-slate-900">{issue.category}</h3>
                              <span className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">{issue.severity}</span>
                            </div>
                            <p className="mt-3 text-sm leading-7 text-slate-600">{issue.description}</p>
                            {issue.phase || issue.frames?.length ? (
                              <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                                {issue.phase ? <span className="rounded-full bg-white px-3 py-1">阶段：{issue.phase}</span> : null}
                                {issue.frames?.length ? <span className="rounded-full bg-white px-3 py-1">帧号：{issue.frames.join(", ")}</span> : null}
                              </div>
                            ) : null}
                          </article>
                        ))
                      ) : (
                        <p className="text-sm text-slate-500">没有识别到明显问题。</p>
                      )}
                    </div>
                  </ReportCard>

                  <ReportCard title="改进建议" eyebrow="Next Reps">
                    <div className="space-y-4">
                      {deferredAnalysis.report?.improvements?.length ? (
                        deferredAnalysis.report.improvements.map((improvement, index) => (
                          <article key={`${improvement.target}-${index}`} className="rounded-[24px] bg-slate-50 p-4">
                            <p className="text-sm font-semibold text-blue-500">{improvement.target}</p>
                            <p className="mt-2 text-sm leading-7 text-slate-600">{improvement.action}</p>
                          </article>
                        ))
                      ) : (
                        <p className="text-sm text-slate-500">暂无改进建议。</p>
                      )}
                    </div>
                  </ReportCard>

                  <ReportCard title="训练重点" eyebrow="Focus" className="border border-blue-100 bg-blue-50/60">
                    <p className="text-lg leading-8 text-slate-700">{deferredAnalysis.report?.training_focus ?? "暂无训练重点。"}</p>
                  </ReportCard>
                </>
              )}
            </div>
          </div>

          <div className="app-card flex flex-col gap-4 border border-blue-100 bg-blue-50/60 p-6 tablet:flex-row tablet:items-center tablet:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">7-Day Plan</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">把这次诊断转成一周训练安排</h2>
              <p className="mt-2 text-sm leading-7 text-slate-500">系统会基于当前报告生成固定 7 天主题的个性化训练计划。</p>
            </div>
            {planId ? (
              <Link to={`/plan/${planId}`} className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600">
                查看训练计划
              </Link>
            ) : (
              <button
                type="button"
                onClick={handleCreatePlan}
                disabled={isCreatingPlan}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCreatingPlan ? "正在生成训练计划..." : "生成训练计划"}
              </button>
            )}
          </div>

          {isParentMode && !isSuggestionLoading && flattenedSuggestions.length ? (
            <section className="app-card border border-amber-200 bg-amber-50/70 p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-600">Memory Suggestions</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">💡 冰宝（IceBuddy）有 {flattenedSuggestions.length} 条记忆更新建议</h2>
              <p className="mt-3 text-sm leading-7 text-slate-600">「{flattenedSuggestions[0]?.title ?? "发现新卡点"}」</p>
              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => void handleViewSuggestions()}
                  disabled={isSuggestionMutating}
                  className="min-h-[44px] rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
                >
                  查看建议
                </button>
                <button
                  type="button"
                  onClick={() => void handleDismissSuggestions()}
                  disabled={isSuggestionMutating}
                  className="min-h-[44px] rounded-full border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                >
                  {isSuggestionMutating ? "处理中..." : "忽略"}
                </button>
              </div>
            </section>
          ) : null}
        </>
      )}

      {isDeleteModalOpen ? (
        <DeleteAnalysisModal
          step={deleteStep}
          pin={deletePin}
          pinLength={pinLength}
          error={deleteError}
          isSubmitting={isDeleting}
          onChangePin={setDeletePin}
          onClose={closeDeleteModal}
          onConfirmDelete={() => setDeleteStep("pin")}
          onSubmitPin={() => void handleDeleteAnalysis()}
        />
      ) : null}

      {celebrateSkillName ? <UnlockCelebration label={celebrateSkillName} /> : null}
    </div>
  );
}
