import axios from "axios";
import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createTrainingSession,
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

const ACCEPTED_TYPES = ".mp4,.mov,.avi,video/mp4,video/quicktime,video/x-msvideo";
const DRAFT_STORAGE_KEY = "icebuddy.review-draft";
const LOCATION_OPTIONS = ["冰场", "家", "体育馆"] as const;
const SESSION_TYPE_OPTIONS = ["上冰", "陆训"] as const;

type ReviewDraft = {
  skaterId: string;
  skillId: string;
  note: string;
  sessionId: string;
};

type SessionFormState = {
  session_date: string;
  location: string;
  session_type: string;
  duration_minutes: string;
  coach_present: boolean;
  note: string;
};

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

function actionTypeForSkill(skill: SkillNode | undefined) {
  return skill?.action_type ?? "自由滑";
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

export default function ReviewPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const draft = useMemo(() => loadDraft(), []);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState(draft?.skaterId ?? "");
  const [skills, setSkills] = useState<SkillNode[]>([]);
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
        setSelectedSkillId((current) => current || draft?.skillId || skillData[0]?.id || "");
        setSelectedSessionId((current) => {
          if (current && sessionData.some((item) => item.id === current)) {
            return current;
          }
          if (draft?.sessionId && sessionData.some((item) => item.id === draft.sessionId)) {
            return draft.sessionId;
          }
          return "";
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
  }, [draft?.sessionId, draft?.skillId, selectedSkaterId]);

  const selectedSkater = skaters.find((skater) => skater.id === selectedSkaterId) ?? null;
  const selectedSkill = skills.find((skill) => skill.id === selectedSkillId);
  const selectedSession = sessions.find((session) => session.id === selectedSessionId) ?? null;
  const groupedSkills = useMemo(() => groupSkills(skills), [skills]);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
    setError(null);
  };

  const handleSaveDraft = () => {
    window.localStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify({
        skaterId: selectedSkaterId,
        skillId: selectedSkillId,
        note,
        sessionId: selectedSessionId,
      }),
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
    formData.append("action_type", actionTypeForSkill(selectedSkill));
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

    try {
      const response = await uploadAnalysis(formData);
      window.localStorage.removeItem(DRAFT_STORAGE_KEY);
      navigate(`/report/${response.id}`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "上传失败，请稍后重试。"));
      } else {
        setError("上传失败，请稍后重试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="app-card overflow-hidden p-6 tablet:p-8">
        <div className="grid gap-6 web:grid-cols-[1.1fr_0.9fr] web:items-start">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Review Flow</p>
            <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">视频复盘</h1>
            <p className="mt-4 max-w-2xl text-base leading-8 text-slate-500">
              上传视频后，冰宝（IceBuddy）会抽取关键帧做诊断。你不再需要手填四段自评，只需补充你最在意的问题。
            </p>
          </div>

          <div className="app-card-muted rounded-3xl p-5">
            <p className="text-sm font-semibold text-slate-900">本次复盘预览</p>
            <div className="mt-4 space-y-3 text-sm text-slate-500">
              <p>练习档案：{selectedSkater ? selectedSkater.display_name || selectedSkater.name : "加载中..."}</p>
              <p>技能分类：{selectedSkill?.name ?? "尚未选择"}</p>
              <p>诊断类型：{actionTypeForSkill(selectedSkill)}</p>
              <p>关联课次：{selectedSession ? sessionLabel(selectedSession) : "不关联"}</p>
              <p>视频文件：{selectedFile ? `${selectedFile.name} · ${formatFileSize(selectedFile.size)}` : "尚未上传"}</p>
            </div>
            <div className="mt-5 rounded-3xl bg-blue-50 p-4 text-sm leading-7 text-slate-600">
              分析完成后，结果会自动进入练习档案时间轴，并可继续生成训练计划。
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-6 web:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-6">
          <section className="app-card p-6 tablet:p-7">
            <p className="text-sm font-semibold text-blue-500">Step 1</p>
            <div className="mt-2 flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-slate-900">选择训练视频</h2>
                <p className="mt-2 text-sm text-slate-500">支持 mp4 / mov / avi，视频会被自动抽帧分析。</p>
              </div>
              <button type="button" onClick={() => inputRef.current?.click()} className="app-pill min-h-[56px] px-5 font-semibold text-blue-600">
                选择训练视频
              </button>
            </div>

            <input ref={inputRef} type="file" accept={ACCEPTED_TYPES} className="hidden" onChange={handleFileChange} />

            <div className="mt-5 rounded-[28px] border border-dashed border-blue-100 bg-blue-50/70 p-5">
              <p className="text-sm font-medium text-slate-700">{selectedFile ? selectedFile.name : "尚未选择视频"}</p>
              <p className="mt-2 text-sm text-slate-500">{selectedFile ? formatFileSize(selectedFile.size) : "点击上方按钮选择本次训练视频。"}</p>
            </div>

            <div className="mt-5 rounded-[28px] border border-slate-200 bg-white p-5">
              <div className="flex flex-col gap-3 tablet:flex-row tablet:items-center tablet:justify-between">
                <div>
                  <p className="text-sm font-semibold text-slate-900">关联到课次（可选）</p>
                  <p className="mt-1 text-sm text-slate-500">可以挂到今天的新课次，或者选择已有课次。</p>
                </div>
                <button
                  type="button"
                  onClick={() => setIsSessionFormOpen((current) => !current)}
                  className="app-pill min-h-[48px] px-4 font-semibold text-blue-600"
                >
                  + 今天新建课次
                </button>
              </div>

              <label className="mt-4 space-y-2">
                <span className="text-sm font-medium text-slate-700">选择已有课次</span>
                <select value={selectedSessionId} onChange={(event) => setSelectedSessionId(event.target.value)} className="app-select">
                  <option value="">不关联课次</option>
                  {sessions.map((session) => (
                    <option key={session.id} value={session.id}>
                      {sessionLabel(session)}
                    </option>
                  ))}
                </select>
              </label>

              {isSessionFormOpen ? (
                <div className="mt-4 grid gap-4 rounded-[24px] bg-slate-50 p-4">
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700">训练日期</span>
                    <input
                      type="date"
                      value={sessionForm.session_date}
                      onChange={(event) => setSessionForm((current) => ({ ...current, session_date: event.target.value }))}
                      className="app-select"
                    />
                  </label>

                  <div className="grid gap-4 tablet:grid-cols-2">
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-slate-700">地点</span>
                      <select
                        value={sessionForm.location}
                        onChange={(event) => setSessionForm((current) => ({ ...current, location: event.target.value }))}
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
                        onChange={(event) => setSessionForm((current) => ({ ...current, session_type: event.target.value }))}
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
                      onChange={(event) => setSessionForm((current) => ({ ...current, duration_minutes: event.target.value }))}
                      className="app-select"
                      placeholder="例如 60"
                    />
                  </label>

                  <label className="flex items-center justify-between rounded-[18px] border border-slate-200 bg-white px-4 py-3">
                    <span className="text-sm font-medium text-slate-700">有教练陪同</span>
                    <input
                      type="checkbox"
                      checked={sessionForm.coach_present}
                      onChange={(event) => setSessionForm((current) => ({ ...current, coach_present: event.target.checked }))}
                      className="h-5 w-5 accent-blue-500"
                    />
                  </label>

                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700">备注</span>
                    <textarea
                      rows={3}
                      value={sessionForm.note}
                      onChange={(event) => setSessionForm((current) => ({ ...current, note: event.target.value }))}
                      className="app-textarea min-h-[96px] resize-y"
                      placeholder="可记录今天的主题、目标或状态。"
                    />
                  </label>

                  <div className="flex flex-col gap-3 tablet:flex-row">
                    <button
                      type="button"
                      onClick={() => void handleCreateSession()}
                      disabled={isCreatingSession}
                      className="min-h-[48px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isCreatingSession ? "创建中..." : "保存并关联本次复盘"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setIsSessionFormOpen(false);
                        setSessionForm(createDefaultSessionForm());
                      }}
                      className="app-pill min-h-[48px] px-5 font-semibold"
                    >
                      收起表单
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section className="app-card p-6 tablet:p-7">
            <p className="text-sm font-semibold text-blue-500">Step 2</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">告诉冰宝（IceBuddy）你在看什么</h2>

            <div className="mt-5 grid gap-4">
              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-700">练习档案</span>
                <select value={selectedSkaterId} onChange={(event) => setSelectedSkaterId(event.target.value)} className="app-select">
                  {skaters.map((skater) => (
                    <option key={skater.id} value={skater.id}>
                      {skater.display_name || skater.name}
                      {skater.level ? ` · ${skater.level}` : ""}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-700">技能分类</span>
                <select value={selectedSkillId} onChange={(event) => setSelectedSkillId(event.target.value)} className="app-select">
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
                    <option value="">正在加载技能节点...</option>
                  )}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-700">补充说明（可选）</span>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={5}
                  placeholder="比如：我最想知道为什么落冰总是飘，或者今天重点想看华尔兹跳。"
                  className="app-textarea min-h-[140px] resize-y"
                />
              </label>
            </div>
          </section>

          <section className="app-card p-6 tablet:p-7">
            <p className="text-sm font-semibold text-blue-500">Step 3</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">开始冰宝（IceBuddy）视频诊断</h2>
            <p className="mt-3 text-sm leading-7 text-slate-500">开始诊断后会上传视频并跳转到诊断报告页。分析结果完成后会自动进入练习档案时间轴。</p>

            {error ? <p className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-500">{error}</p> : null}
            {saveMessage ? <p className="mt-4 rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-600">{saveMessage}</p> : null}

            <div className="mt-5 flex flex-col gap-3 tablet:flex-row">
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={!selectedFile || isSubmitting}
                className="min-h-[56px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-55"
              >
                {isSubmitting ? "开始诊断中..." : "开始冰宝（IceBuddy）诊断"}
              </button>
              <button type="button" onClick={handleSaveDraft} className="app-pill min-h-[56px] px-5 font-semibold">
                保存本条复盘
              </button>
            </div>
          </section>
        </div>

        <div className="space-y-6">
          <section className="app-card p-6 tablet:p-7">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">复盘说明</p>
            <div className="mt-4 space-y-4 text-sm leading-7 text-slate-500">
              <p>1. 选择视频后，系统会自动上传原片并抽取动作关键帧。</p>
              <p>2. 技能分类会直接使用技能树节点名称，帮助冰宝（IceBuddy）更快定位动作语境。</p>
              <p>3. 你补充的备注会和报告一起进入练习档案，课次信息也会同步进入时间轴。</p>
            </div>
          </section>

          <section className="app-card p-6 tablet:p-7">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">当前对象</p>
            {selectedSkater ? (
              <div className="mt-4 rounded-[28px] bg-slate-50 p-5">
                <ZodiacAvatar avatarType={selectedSkater.avatar_type} avatarEmoji={selectedSkater.avatar_emoji} size="md" animate className="mx-auto tablet:mx-0" />
                <h2 className="mt-3 text-xl font-semibold text-slate-900">{selectedSkater.display_name || selectedSkater.name}</h2>
                <p className="mt-2 text-sm text-slate-500">{selectedSkater.level ?? selectedSkater.current_level}</p>
                <p className="mt-4 text-sm text-slate-500">当前 XP：{selectedSkater.total_xp}</p>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-500">正在加载练习档案...</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
