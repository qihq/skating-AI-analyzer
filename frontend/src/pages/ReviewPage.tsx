import axios from "axios";
import { ChangeEvent, RefObject, startTransition, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  AnalysisStatus,
  createTrainingSession,
  fetchAnalysis,
  fetchSkaterSkills,
  fetchSkaters,
  fetchTrainingSessions,
  SessionPayload,
  Skater,
  SkillNode,
  TrainingSessionRecord,
  uploadAnalysis,
} from "../api/client";
import ZodiacAvatar from "../components/ZodiacAvatar";
import { useAppMode } from "../components/AppModeContext";
import { getAnalysisProcessingStage, isAnalysisInProgress } from "../constants/analysisStatus";
import { childViewFromSkater, pickSkaterIdForChildView } from "../utils/childView";

const ACCEPTED_TYPES = ".mp4,.mov,.avi,video/mp4,video/quicktime,video/x-msvideo";
const DRAFT_STORAGE_KEY = "icebuddy.review-draft";
const LOCATION_OPTIONS = ["冰场", "家", "体育馆"] as const;
const SESSION_TYPE_OPTIONS = ["上冰", "陆训"] as const;
const ACTION_TYPE_OPTIONS = ["跳跃", "旋转", "步法", "自由滑"] as const;
const ACTION_SUBTYPE_OPTIONS: Record<(typeof ACTION_TYPE_OPTIONS)[number], readonly string[]> = {
  跳跃: ["未指定", "单跳", "连跳"],
  旋转: ["未指定", "直立旋转", "蹲转", "燕式旋转", "联合旋转"],
  步法: ["未指定", "步法序列", "燕式滑行"],
  自由滑: ["节目片段"],
};

type ActionType = (typeof ACTION_TYPE_OPTIONS)[number];

type ReviewDraft = {
  skaterId: string;
  skillId: string;
  note: string;
  sessionId: string;
  actionType?: string;
  actionSubtype?: string;
};

type SessionFormState = {
  session_date: string;
  location: string;
  session_type: string;
  duration_minutes: string;
  coach_present: boolean;
  note: string;
};

type UploadStage = "idle" | "uploading" | "processing";
type AnalysisStepState = "active" | "done" | "idle";
type AnalysisStep = (typeof PROCESS_STEPS)[number] & { state: AnalysisStepState };

const PROCESS_STEPS = [
  { key: "uploaded", label: "视频上传" },
  { key: "extracting", label: "画面提取" },
  { key: "analyzing", label: "AI 分析" },
  { key: "report", label: "生成报告" },
] as const;

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function loadDraft(): ReviewDraft | null {
  const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as ReviewDraft;
  } catch {
    return null;
  }
}

function groupSkills(skills: SkillNode[]) {
  const groups = new Map<string, SkillNode[]>();
  skills.forEach((skill) => {
    const key = `阶段 ${skill.stage} · ${skill.stage_name}`;
    const current = groups.get(key) ?? [];
    current.push(skill);
    groups.set(key, current);
  });
  return Array.from(groups.entries());
}

function isActionType(value: string | null | undefined): value is ActionType {
  return ACTION_TYPE_OPTIONS.includes((value ?? "") as ActionType);
}

function actionTypeForSkill(skill: SkillNode | undefined): ActionType {
  return isActionType(skill?.action_type) ? skill.action_type : "自由滑";
}

function defaultSubtypeForActionType(actionType: ActionType) {
  return ACTION_SUBTYPE_OPTIONS[actionType][0];
}

function normalizeSubtype(actionType: ActionType, subtype?: string | null) {
  if (subtype && ACTION_SUBTYPE_OPTIONS[actionType].includes(subtype)) {
    return subtype;
  }
  return defaultSubtypeForActionType(actionType);
}

function todayString() {
  return new Date().toISOString().slice(0, 10);
}

function createDefaultSessionForm(): SessionFormState {
  return {
    session_date: todayString(),
    location: "冰场",
    session_type: "上冰",
    duration_minutes: "",
    coach_present: false,
    note: "",
  };
}

function sessionLabel(session: TrainingSessionRecord) {
  const parts = [session.session_date, session.location, session.session_type];
  if (session.duration_minutes) {
    parts.push(`${session.duration_minutes} 分钟`);
  }
  return parts.join(" · ");
}

type UploadWorkspaceHeaderProps = {
  selectedSkater: Skater | null;
  skaters: Skater[];
  selectedSkaterId: string;
  isParentMode: boolean;
  onSkaterChange: (nextSkaterId: string) => void;
};

function UploadWorkspaceHeader({
  selectedSkater,
  skaters,
  selectedSkaterId,
  isParentMode,
  onSkaterChange,
}: UploadWorkspaceHeaderProps) {
  return (
    <section className="app-card overflow-hidden p-5 phone:p-6 tablet:p-8">
      <div className="flex flex-col gap-5 tablet:flex-row tablet:items-end tablet:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-blue-500">Review Workspace</p>
          <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">视频复盘工作台</h1>
          <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">
            先上传训练视频，再补充动作范围和最想看的问题。冰宝（IceBuddy）会自动抽取关键帧并生成诊断报告。
          </p>
        </div>

        <div className="min-w-0 rounded-[24px] border border-slate-200 bg-white px-4 py-4 tablet:min-w-[280px]">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">
            {isParentMode ? "分析对象" : "当前练习档案"}
          </p>
          <label className="mt-3 block space-y-2">
            <span className="sr-only">选择练习档案</span>
            <select value={selectedSkaterId} onChange={(event) => onSkaterChange(event.target.value)} className="app-select">
              {skaters.map((skater) => (
                <option key={skater.id} value={skater.id}>
                  {skater.display_name || skater.name}
                  {skater.level ? ` · ${skater.level}` : ""}
                </option>
              ))}
            </select>
          </label>
          {selectedSkater ? (
            <div className="mt-3 flex items-center gap-3 text-sm text-slate-500">
              <ZodiacAvatar avatarType={selectedSkater.avatar_type} avatarEmoji={selectedSkater.avatar_emoji} size="sm" />
              <span className="min-w-0 truncate">
                XP {selectedSkater.total_xp} · {selectedSkater.level ?? selectedSkater.current_level}
              </span>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">正在加载练习档案...</p>
          )}
        </div>
      </div>
    </section>
  );
}

type UploadCardProps = {
  inputRef: RefObject<HTMLInputElement>;
  selectedFile: File | null;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
};

function UploadCard({ inputRef, selectedFile, onFileChange }: UploadCardProps) {
  return (
    <section className="app-card overflow-hidden p-5 phone:p-6 tablet:p-7">
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
        <div>
          <p className="text-sm font-semibold text-blue-500">1 · 上传视频</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">选择本次训练片段</h2>
          <p className="mt-2 max-w-2xl text-sm leading-7 text-slate-500">
            支持 mp4 / mov / avi。建议上传单个动作或一段清晰的训练片段，后续会自动抽帧分析。
          </p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="min-h-[52px] shrink-0 whitespace-nowrap rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
        >
          选择训练视频
        </button>
      </div>

      <input ref={inputRef} type="file" accept={ACCEPTED_TYPES} className="hidden" onChange={onFileChange} />

      <div
        className={`mt-6 rounded-[26px] border px-5 py-5 ${
          selectedFile ? "border-blue-200 bg-blue-50/70" : "border-dashed border-slate-300 bg-slate-50"
        }`}
      >
        <div className="flex flex-col gap-2 tablet:flex-row tablet:items-center tablet:justify-between">
          <div className="min-w-0">
            <p className="break-words text-base font-semibold text-slate-900">{selectedFile ? selectedFile.name : "尚未选择视频"}</p>
            <p className="mt-1 text-sm text-slate-500">
              {selectedFile ? formatFileSize(selectedFile.size) : "点击按钮选择视频后，再填写下方复盘上下文。"}
            </p>
          </div>
          <span className="w-fit rounded-full bg-white px-3 py-1 text-sm font-medium text-slate-500">
            {selectedFile ? "已就绪" : "等待上传"}
          </span>
        </div>
      </div>
    </section>
  );
}

type SessionPanelProps = {
  sessions: TrainingSessionRecord[];
  selectedSessionId: string;
  isSessionFormOpen: boolean;
  sessionForm: SessionFormState;
  isCreatingSession: boolean;
  onSessionChange: (sessionId: string) => void;
  onToggleForm: () => void;
  onSessionFormChange: (nextForm: SessionFormState) => void;
  onCreateSession: () => void;
  onCancelSessionForm: () => void;
};

function SessionPanel({
  sessions,
  selectedSessionId,
  isSessionFormOpen,
  sessionForm,
  isCreatingSession,
  onSessionChange,
  onToggleForm,
  onSessionFormChange,
  onCreateSession,
  onCancelSessionForm,
}: SessionPanelProps) {
  return (
    <div className="rounded-[26px] border border-slate-200 bg-slate-50/70 p-4 tablet:p-5">
      <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-900">关联课次（可选）</p>
          <p className="mt-1 text-sm leading-6 text-slate-500">用于把本次复盘归档到训练时间轴；不关联也可以提交分析。</p>
        </div>
        <button type="button" onClick={onToggleForm} className="app-pill min-h-[44px] px-4 text-sm font-semibold text-blue-600">
          {isSessionFormOpen ? "收起新课次" : "新建课次"}
        </button>
      </div>

      <label className="mt-4 block space-y-2">
        <span className="text-sm font-medium text-slate-700">选择已有课次</span>
        <select value={selectedSessionId} onChange={(event) => onSessionChange(event.target.value)} className="app-select">
          <option value="">不关联课次</option>
          {sessions.map((session) => (
            <option key={session.id} value={session.id}>
              {sessionLabel(session)}
            </option>
          ))}
        </select>
      </label>

      {isSessionFormOpen ? (
        <div className="mt-4 grid gap-4 rounded-[22px] border border-white bg-white p-4">
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">训练日期</span>
            <input
              type="date"
              value={sessionForm.session_date}
              onChange={(event) => onSessionFormChange({ ...sessionForm, session_date: event.target.value })}
              className="app-select"
            />
          </label>

          <div className="grid gap-4 tablet:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">地点</span>
              <select
                value={sessionForm.location}
                onChange={(event) => onSessionFormChange({ ...sessionForm, location: event.target.value })}
                className="app-select"
              >
                {LOCATION_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">类型</span>
              <select
                value={sessionForm.session_type}
                onChange={(event) => onSessionFormChange({ ...sessionForm, session_type: event.target.value })}
                className="app-select"
              >
                {SESSION_TYPE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">时长（分钟）</span>
            <input
              type="number"
              min={0}
              value={sessionForm.duration_minutes}
              onChange={(event) => onSessionFormChange({ ...sessionForm, duration_minutes: event.target.value })}
              className="app-select"
              placeholder="例如 60"
            />
          </label>

          <label className="flex min-h-[52px] items-center justify-between rounded-[18px] border border-slate-200 bg-white px-4 py-3">
            <span className="text-sm font-medium text-slate-700">有教练陪同</span>
            <input
              type="checkbox"
              checked={sessionForm.coach_present}
              onChange={(event) => onSessionFormChange({ ...sessionForm, coach_present: event.target.checked })}
              className="h-5 w-5 accent-blue-500"
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">备注</span>
            <textarea
              rows={3}
              value={sessionForm.note}
              onChange={(event) => onSessionFormChange({ ...sessionForm, note: event.target.value })}
              className="app-textarea min-h-[96px] resize-y"
              placeholder="可记录今天的主题、目标或状态。"
            />
          </label>

          <div className="flex flex-col gap-3 tablet:flex-row">
            <button
              type="button"
              onClick={onCreateSession}
              disabled={isCreatingSession}
              className="min-h-[48px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isCreatingSession ? "创建中..." : "保存并关联"}
            </button>
            <button type="button" onClick={onCancelSessionForm} className="app-pill min-h-[48px] px-5 text-sm font-semibold">
              取消
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

type ContextCardProps = {
  selectedActionType: ActionType;
  selectedActionSubtype: string;
  selectedSkill: SkillNode | undefined;
  groupedSkills: Array<[string, SkillNode[]]>;
  note: string;
  sessions: TrainingSessionRecord[];
  selectedSessionId: string;
  isSessionFormOpen: boolean;
  sessionForm: SessionFormState;
  isCreatingSession: boolean;
  onActionTypeChange: (nextType: ActionType) => void;
  onActionSubtypeChange: (nextSubtype: string) => void;
  onSkillChange: (nextSkillId: string) => void;
  onNoteChange: (nextNote: string) => void;
  onSessionChange: (sessionId: string) => void;
  onToggleSessionForm: () => void;
  onSessionFormChange: (nextForm: SessionFormState) => void;
  onCreateSession: () => void;
  onCancelSessionForm: () => void;
};

function ContextCard({
  selectedActionType,
  selectedActionSubtype,
  selectedSkill,
  groupedSkills,
  note,
  sessions,
  selectedSessionId,
  isSessionFormOpen,
  sessionForm,
  isCreatingSession,
  onActionTypeChange,
  onActionSubtypeChange,
  onSkillChange,
  onNoteChange,
  onSessionChange,
  onToggleSessionForm,
  onSessionFormChange,
  onCreateSession,
  onCancelSessionForm,
}: ContextCardProps) {
  return (
    <section className="app-card p-5 phone:p-6 tablet:p-7">
      <div>
        <p className="text-sm font-semibold text-blue-500">2 · 复盘上下文</p>
        <h2 className="mt-2 text-2xl font-semibold text-slate-900">告诉冰宝你在看什么</h2>
        <p className="mt-2 max-w-2xl text-sm leading-7 text-slate-500">
          动作信息会直接进入分析链路。备注只写你最关心的问题，报告会围绕这些重点展开。
        </p>
      </div>

      <div className="mt-6 grid gap-4">
        <div className="grid gap-4 tablet:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">动作大类</span>
            <select value={selectedActionType} onChange={(event) => onActionTypeChange(event.target.value as ActionType)} className="app-select">
              {ACTION_TYPE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">动作子类</span>
            <select value={selectedActionSubtype} onChange={(event) => onActionSubtypeChange(event.target.value)} className="app-select">
              {ACTION_SUBTYPE_OPTIONS[selectedActionType].map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="space-y-2">
          <span className="text-sm font-medium text-slate-700">技能分类</span>
          <select value={selectedSkill?.id ?? ""} onChange={(event) => onSkillChange(event.target.value)} className="app-select">
            {groupedSkills.length ? (
              groupedSkills.map(([groupLabel, items]) => (
                <optgroup key={groupLabel} label={groupLabel}>
                  {items.map((skill) => (
                    <option key={skill.id} value={skill.id}>
                      {skill.name}
                    </option>
                  ))}
                </optgroup>
              ))
            ) : (
              <option value="">当前大类下暂无技能节点</option>
            )}
          </select>
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium text-slate-700">最想看的问题（可选）</span>
          <textarea
            value={note}
            onChange={(event) => onNoteChange(event.target.value)}
            rows={5}
            placeholder="比如：我最想知道为什么落冰总是飘，或者今天重点想看华尔兹跳。"
            className="app-textarea min-h-[140px] resize-y"
          />
        </label>

        <SessionPanel
          sessions={sessions}
          selectedSessionId={selectedSessionId}
          isSessionFormOpen={isSessionFormOpen}
          sessionForm={sessionForm}
          isCreatingSession={isCreatingSession}
          onSessionChange={onSessionChange}
          onToggleForm={onToggleSessionForm}
          onSessionFormChange={onSessionFormChange}
          onCreateSession={onCreateSession}
          onCancelSessionForm={onCancelSessionForm}
        />
      </div>
    </section>
  );
}

type ProcessingProgressProps = {
  uploadStage: UploadStage;
  uploadProgress: { loaded: number; total: number; percent: number };
  selectedFile: File | null;
  analysisSteps: AnalysisStep[];
};

function ProcessingProgress({ uploadStage, uploadProgress, selectedFile, analysisSteps }: ProcessingProgressProps) {
  if (uploadStage === "idle") {
    return null;
  }

  return (
    <div className="rounded-[24px] border border-blue-100 bg-blue-50/70 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900">{uploadStage === "uploading" ? "正在上传视频" : "正在生成分析结果"}</p>
        <span className="text-sm font-semibold text-blue-600">{uploadStage === "uploading" ? `${uploadProgress.percent}%` : "100%"}</span>
      </div>

      <div className="mt-3 h-3 overflow-hidden rounded-full bg-white">
        <div
          className="h-full rounded-full bg-blue-500 transition-[width] duration-300"
          style={{ width: `${uploadStage === "uploading" ? uploadProgress.percent : 100}%` }}
        />
      </div>

      <p className="mt-3 text-sm text-slate-500">
        {formatFileSize(uploadProgress.loaded)} / {formatFileSize(uploadProgress.total || selectedFile?.size || 0)}
      </p>

      <div className="mt-4 grid gap-2">
        {analysisSteps.map((step) => {
          const icon = step.state === "done" ? "✓" : step.state === "active" ? "…" : "○";
          const tone =
            step.state === "done"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : step.state === "active"
                ? "border-amber-200 bg-amber-50 text-amber-700"
                : "border-slate-200 bg-white text-slate-400";
          return (
            <div key={step.key} className={`flex min-h-[42px] items-center gap-3 rounded-2xl border px-3 py-2 text-sm ${tone}`}>
              <span className="w-5 text-center text-base leading-none">{icon}</span>
              <span className="font-medium">{step.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

type ReviewSummaryProps = {
  selectedSkater: Skater | null;
  selectedActionType: ActionType;
  selectedActionSubtype: string;
  selectedSkill: SkillNode | undefined;
  selectedSession: TrainingSessionRecord | null;
  selectedFile: File | null;
  note: string;
  error: string | null;
  saveMessage: string | null;
  uploadStage: UploadStage;
  uploadProgress: { loaded: number; total: number; percent: number };
  analysisSteps: AnalysisStep[];
  isSubmitting: boolean;
  onSubmit: () => void;
  onSaveDraft: () => void;
};

function ReviewSummary({
  selectedSkater,
  selectedActionType,
  selectedActionSubtype,
  selectedSkill,
  selectedSession,
  selectedFile,
  note,
  error,
  saveMessage,
  uploadStage,
  uploadProgress,
  analysisSteps,
  isSubmitting,
  onSubmit,
  onSaveDraft,
}: ReviewSummaryProps) {
  const summaryItems = [
    { label: "练习档案", value: selectedSkater ? selectedSkater.display_name || selectedSkater.name : "加载中..." },
    { label: "动作范围", value: `${selectedActionType} · ${selectedActionSubtype}` },
    { label: "技能分类", value: selectedSkill?.name ?? "尚未选择" },
    { label: "关联课次", value: selectedSession ? sessionLabel(selectedSession) : "不关联" },
    { label: "视频文件", value: selectedFile ? `${selectedFile.name} · ${formatFileSize(selectedFile.size)}` : "尚未上传" },
  ];

  return (
    <aside className="app-card p-5 phone:p-6 tablet:p-7 web:sticky web:top-[112px]">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">确认提交</p>
        <h2 className="mt-2 text-2xl font-semibold text-slate-900">本次复盘摘要</h2>
        <p className="mt-2 text-sm leading-7 text-slate-500">提交前确认对象、动作和视频。分析完成后会自动进入报告与时间轴。</p>
      </div>

      <div className="mt-5 grid gap-3">
        {summaryItems.map((item) => (
          <div key={item.label} className="rounded-[20px] border border-slate-200 bg-white px-4 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">{item.label}</p>
            <p className="mt-1 break-words text-sm font-medium leading-6 text-slate-700">{item.value}</p>
          </div>
        ))}
        {note.trim() ? (
          <div className="rounded-[20px] border border-blue-100 bg-blue-50/70 px-4 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-blue-500">关注点</p>
            <p className="mt-1 text-sm leading-6 text-slate-700">{note.trim()}</p>
          </div>
        ) : null}
      </div>

      {error ? <p className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-500">{error}</p> : null}
      {saveMessage ? <p className="mt-4 rounded-2xl bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-600">{saveMessage}</p> : null}

      <div className="mt-5 space-y-3">
        <button
          type="button"
          onClick={onSubmit}
          disabled={!selectedFile || isSubmitting}
          className="min-h-[56px] w-full rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-55"
        >
          {isSubmitting ? "开始诊断中..." : "开始冰宝诊断"}
        </button>
        <button type="button" onClick={onSaveDraft} className="app-pill min-h-[52px] w-full px-5 text-sm font-semibold">
          保存本条复盘
        </button>
      </div>

      <div className="mt-5">
        <ProcessingProgress
          uploadStage={uploadStage}
          uploadProgress={uploadProgress}
          selectedFile={selectedFile}
          analysisSteps={analysisSteps}
        />
      </div>
    </aside>
  );
}

export default function ReviewPage() {
  const { isParentMode, childView, setChildView } = useAppMode();
  const location = useLocation();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const draft = useMemo(() => loadDraft(), []);
  const preferredSkaterId = (location.state as { skaterId?: string } | null)?.skaterId ?? "";
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState(preferredSkaterId || draft?.skaterId || "");
  const [skills, setSkills] = useState<SkillNode[]>([]);
  const [selectedActionType, setSelectedActionType] = useState<ActionType>(
    isActionType(draft?.actionType) ? draft.actionType : "自由滑",
  );
  const [selectedActionSubtype, setSelectedActionSubtype] = useState(() =>
    normalizeSubtype(isActionType(draft?.actionType) ? draft.actionType : "自由滑", draft?.actionSubtype),
  );
  const [selectedSkillId, setSelectedSkillId] = useState(draft?.skillId ?? "");
  const [sessions, setSessions] = useState<TrainingSessionRecord[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState(draft?.sessionId ?? "");
  const [note, setNote] = useState(draft?.note ?? "");
  const [isSessionFormOpen, setIsSessionFormOpen] = useState(false);
  const [sessionForm, setSessionForm] = useState<SessionFormState>(createDefaultSessionForm);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [uploadStage, setUploadStage] = useState<UploadStage>("idle");
  const [uploadProgress, setUploadProgress] = useState({ loaded: 0, total: 0, percent: 0 });
  const [pendingAnalysisId, setPendingAnalysisId] = useState<string | null>(null);
  const [processingStatus, setProcessingStatus] = useState<AnalysisStatus>("pending");

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (cancelled) {
          return;
        }
        setSkaters(data);
        setSelectedSkaterId(
          (current) =>
            current ||
            (preferredSkaterId && data.some((skater) => skater.id === preferredSkaterId) ? preferredSkaterId : "") ||
            (!isParentMode ? pickSkaterIdForChildView(data, childView) : "") ||
            data.find((skater) => skater.is_default)?.id ||
            data[0]?.id ||
            "",
        );
      } catch {
        if (!cancelled) {
          setError("练习档案加载失败，请稍后刷新页面。");
        }
      }
    };

    void loadSkaters();
    return () => {
      cancelled = true;
    };
  }, [childView, isParentMode, preferredSkaterId]);

  useEffect(() => {
    if (isParentMode || !skaters.length || preferredSkaterId) {
      return;
    }

    const nextSkaterId = pickSkaterIdForChildView(skaters, childView);
    setSelectedSkaterId((current) => (current === nextSkaterId ? current : nextSkaterId));
  }, [childView, isParentMode, preferredSkaterId, skaters]);

  useEffect(() => {
    if (!selectedSkaterId) {
      return;
    }

    let cancelled = false;
    const loadSkaterContext = async () => {
      try {
        const [skillData, sessionData] = await Promise.all([
          fetchSkaterSkills(selectedSkaterId),
          fetchTrainingSessions(selectedSkaterId),
        ]);
        if (cancelled) {
          return;
        }

        setSkills(skillData);
        setSessions(sessionData);
        setSelectedSessionId((current) => {
          if (current && sessionData.some((item) => item.id === current)) {
            return current;
          }
          if (draft?.sessionId && sessionData.some((item) => item.id === draft.sessionId)) {
            return draft.sessionId;
          }
          return "";
        });

        const draftSkill = skillData.find((skill) => skill.id === draft?.skillId);
        const nextActionType = draftSkill
          ? actionTypeForSkill(draftSkill)
          : isActionType(draft?.actionType)
            ? draft.actionType
            : skillData[0]
              ? actionTypeForSkill(skillData[0])
              : "自由滑";

        setSelectedActionType(nextActionType);
        setSelectedActionSubtype(normalizeSubtype(nextActionType, draft?.actionSubtype));

        const filtered = skillData.filter((skill) => actionTypeForSkill(skill) === nextActionType);
        setSelectedSkillId((current) => {
          const draftSkillId =
            draftSkill && actionTypeForSkill(draftSkill) === nextActionType ? draftSkill.id : "";
          if (current && filtered.some((skill) => skill.id === current)) {
            return current;
          }
          if (draftSkillId) {
            return draftSkillId;
          }
          return filtered[0]?.id ?? "";
        });
      } catch {
        if (!cancelled) {
          setSkills([]);
          setSessions([]);
          setError("技能分类或课次列表加载失败，请稍后重试。");
        }
      }
    };

    void loadSkaterContext();
    return () => {
      cancelled = true;
    };
  }, [draft?.actionSubtype, draft?.actionType, draft?.sessionId, draft?.skillId, selectedSkaterId]);

  useEffect(() => {
    if (!pendingAnalysisId) {
      return;
    }

    let cancelled = false;
    let timer: number | undefined;

    const pollAnalysis = async () => {
      try {
        const data = await fetchAnalysis(pendingAnalysisId, { isParentRequest: isParentMode });
        if (cancelled) {
          return;
        }

        startTransition(() => {
          setProcessingStatus(data.status);
        });

        if (data.status === "completed") {
          window.localStorage.removeItem(DRAFT_STORAGE_KEY);
          setIsSubmitting(false);
          navigate(`/report/${data.id}`);
          return;
        }

        if (data.status === "awaiting_target_selection") {
          setIsSubmitting(false);
          navigate(`/report/${data.id}/target`);
          return;
        }

        if (data.status === "failed") {
          setError(data.error_message ?? "分析失败，请稍后重试。");
          setUploadStage("idle");
          setIsSubmitting(false);
          setPendingAnalysisId(null);
          return;
        }

        if (isAnalysisInProgress(data.status)) {
          timer = window.setTimeout(pollAnalysis, 3000);
        }
      } catch {
        if (!cancelled) {
          setError("分析状态加载失败，请稍后重试。");
          setUploadStage("idle");
          setIsSubmitting(false);
          setPendingAnalysisId(null);
        }
      }
    };

    void pollAnalysis();

    return () => {
      cancelled = true;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [isParentMode, navigate, pendingAnalysisId]);

  const filteredSkills = useMemo(
    () => skills.filter((skill) => actionTypeForSkill(skill) === selectedActionType),
    [selectedActionType, skills],
  );
  const groupedSkills = useMemo(() => groupSkills(filteredSkills), [filteredSkills]);
  const selectedSkater = skaters.find((skater) => skater.id === selectedSkaterId) ?? null;
  const selectedSkill = filteredSkills.find((skill) => skill.id === selectedSkillId) ?? filteredSkills[0];
  const selectedSession = sessions.find((session) => session.id === selectedSessionId) ?? null;
  const processingStage = getAnalysisProcessingStage(processingStatus);
  const analysisSteps = useMemo<AnalysisStep[]>(
    () => [
      { ...PROCESS_STEPS[0], state: uploadStage === "uploading" ? "active" : uploadStage === "processing" ? "done" : "idle" },
      {
        ...PROCESS_STEPS[1],
        state: uploadStage === "processing" ? (processingStage >= 1 ? "done" : "active") : "idle",
      },
      {
        ...PROCESS_STEPS[2],
        state: uploadStage === "processing" ? (processingStage >= 2 ? "done" : processingStage >= 1 ? "active" : "idle") : "idle",
      },
      {
        ...PROCESS_STEPS[3],
        state: uploadStage === "processing" ? (processingStage >= 3 ? "done" : processingStage >= 2 ? "active" : "idle") : "idle",
      },
    ],
    [processingStage, uploadStage],
  );

  useEffect(() => {
    setSelectedActionSubtype((current) => normalizeSubtype(selectedActionType, current));
    setSelectedSkillId((current) => {
      if (current && filteredSkills.some((skill) => skill.id === current)) {
        return current;
      }
      return filteredSkills[0]?.id ?? "";
    });
  }, [filteredSkills, selectedActionType]);

  useEffect(() => {
    if (!selectedSkill) {
      return;
    }
    const skillActionType = actionTypeForSkill(selectedSkill);
    if (skillActionType !== selectedActionType) {
      setSelectedActionType(skillActionType);
      setSelectedActionSubtype((current) => normalizeSubtype(skillActionType, current));
    }
  }, [selectedActionType, selectedSkill]);

  const handleSkaterChange = (nextSkaterId: string) => {
    setSelectedSkaterId(nextSkaterId);
    if (isParentMode) {
      return;
    }

    const nextView = childViewFromSkater(skaters.find((skater) => skater.id === nextSkaterId));
    if (nextView) {
      setChildView(nextView);
    }
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setError(null);
  };

  const handleActionTypeChange = (nextType: ActionType) => {
    setSelectedActionType(nextType);
    setSelectedActionSubtype((current) => normalizeSubtype(nextType, current));
  };

  const handleSaveDraft = () => {
    window.localStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify({
        skaterId: selectedSkaterId,
        skillId: selectedSkill?.id ?? "",
        note,
        sessionId: selectedSessionId,
        actionType: selectedActionType,
        actionSubtype: selectedActionSubtype,
      } satisfies ReviewDraft),
    );
    setSaveMessage("这条复盘草稿已保存。");
    window.setTimeout(() => setSaveMessage(null), 1800);
  };

  const handleCreateSession = async () => {
    if (!selectedSkaterId) {
      setError("请先选择练习档案，再创建课次。");
      return;
    }

    const payload: SessionPayload = {
      session_date: sessionForm.session_date,
      location: sessionForm.location,
      session_type: sessionForm.session_type,
      duration_minutes: sessionForm.duration_minutes ? Number(sessionForm.duration_minutes) : null,
      coach_present: sessionForm.coach_present,
      note: sessionForm.note.trim() ? sessionForm.note.trim() : null,
    };

    setIsCreatingSession(true);
    setError(null);
    try {
      const created = await createTrainingSession(selectedSkaterId, payload);
      setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setSelectedSessionId(created.id);
      setIsSessionFormOpen(false);
      setSessionForm(createDefaultSessionForm());
      setSaveMessage("今天的训练课次已创建，并自动关联到本次复盘。");
      window.setTimeout(() => setSaveMessage(null), 2200);
    } catch (requestError) {
      setUploadStage("idle");
      setPendingAnalysisId(null);
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "课次创建失败，请稍后重试。"));
      } else {
        setError("课次创建失败，请稍后重试。");
      }
    } finally {
      setIsCreatingSession(false);
    }
  };

  const handleSubmit = async () => {
    if (!selectedFile) {
      setError("请先选择训练视频。");
      return;
    }
    if (!selectedSkill) {
      setError("请先选择技能分类。");
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("action_type", selectedActionType);
    formData.append("action_subtype", selectedActionSubtype);
    formData.append("skill_node_id", selectedSkill.id);
    formData.append("skill_category", selectedSkill.name);
    if (selectedSkaterId) {
      formData.append("skater_id", selectedSkaterId);
    }
    if (note.trim()) {
      formData.append("note", note.trim());
    }
    if (selectedSessionId) {
      formData.append("session_id", selectedSessionId);
    }

    setIsSubmitting(true);
    setError(null);
    setUploadStage("uploading");
    setUploadProgress({ loaded: 0, total: selectedFile.size, percent: 0 });
    setPendingAnalysisId(null);
    setProcessingStatus("pending");

    try {
      const response = await uploadAnalysis(formData, {
        onProgress: (progress) => {
          startTransition(() => {
            setUploadProgress(progress);
          });
        },
      });
      startTransition(() => {
        setUploadProgress({ loaded: selectedFile.size, total: selectedFile.size, percent: 100 });
        setUploadStage("processing");
        setProcessingStatus(response.status);
        setPendingAnalysisId(response.id);
      });
      if (response.status === "awaiting_target_selection") {
        navigate(`/report/${response.id}/target`);
      }
    } catch (requestError) {
      setUploadStage("idle");
      setPendingAnalysisId(null);
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "上传失败，请稍后重试。"));
      } else {
        setError("上传失败，请稍后重试。");
      }
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      <UploadWorkspaceHeader
        selectedSkater={selectedSkater}
        skaters={skaters}
        selectedSkaterId={selectedSkaterId}
        isParentMode={isParentMode}
        onSkaterChange={handleSkaterChange}
      />

      <div className="grid min-w-0 gap-6 web:grid-cols-[minmax(0,1fr)_390px] web:items-start">
        <main className="min-w-0 space-y-6">
          <UploadCard inputRef={inputRef} selectedFile={selectedFile} onFileChange={handleFileChange} />

          <ContextCard
            selectedActionType={selectedActionType}
            selectedActionSubtype={selectedActionSubtype}
            selectedSkill={selectedSkill}
            groupedSkills={groupedSkills}
            note={note}
            sessions={sessions}
            selectedSessionId={selectedSessionId}
            isSessionFormOpen={isSessionFormOpen}
            sessionForm={sessionForm}
            isCreatingSession={isCreatingSession}
            onActionTypeChange={handleActionTypeChange}
            onActionSubtypeChange={setSelectedActionSubtype}
            onSkillChange={setSelectedSkillId}
            onNoteChange={setNote}
            onSessionChange={setSelectedSessionId}
            onToggleSessionForm={() => setIsSessionFormOpen((current) => !current)}
            onSessionFormChange={setSessionForm}
            onCreateSession={() => void handleCreateSession()}
            onCancelSessionForm={() => {
              setIsSessionFormOpen(false);
              setSessionForm(createDefaultSessionForm());
            }}
          />
        </main>

        <ReviewSummary
          selectedSkater={selectedSkater}
          selectedActionType={selectedActionType}
          selectedActionSubtype={selectedActionSubtype}
          selectedSkill={selectedSkill}
          selectedSession={selectedSession}
          selectedFile={selectedFile}
          note={note}
          error={error}
          saveMessage={saveMessage}
          uploadStage={uploadStage}
          uploadProgress={uploadProgress}
          analysisSteps={analysisSteps}
          isSubmitting={isSubmitting}
          onSubmit={() => void handleSubmit()}
          onSaveDraft={handleSaveDraft}
        />
      </div>
    </div>
  );
}
