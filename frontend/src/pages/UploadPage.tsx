import axios from "axios";
import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { fetchSkaters, Skater, uploadAnalysis } from "../api/client";
import { useAppMode } from "../components/AppModeContext";
import TopNav from "../components/TopNav";
import { childViewFromSkater, pickSkaterIdForChildView } from "../utils/childView";

const ACTION_OPTIONS = ["跳跃", "旋转", "步法", "自由滑"];
const ACCEPTED_TYPES = ".mp4,.mov,.avi,video/mp4,video/quicktime,video/x-msvideo";
const MAX_FILE_SIZE_MB = 500;

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const navigate = useNavigate();
  const { isParentMode, childView, setChildView, enterParentMode } = useAppMode();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [actionType, setActionType] = useState<string>(ACTION_OPTIONS[0]);
  const [note, setNote] = useState("");
  const [skillCategory, setSkillCategory] = useState("");
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedSkaterId, setSelectedSkaterId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const loadSkaters = async () => {
      try {
        const data = await fetchSkaters();
        if (cancelled) {
          return;
        }
        setSkaters(data);
        setSelectedSkaterId((current) => current || (isParentMode ? "" : pickSkaterIdForChildView(data, childView)) || data[0]?.id || "");
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
  }, [childView, isParentMode]);

  useEffect(() => {
    if (isParentMode || !skaters.length) {
      return;
    }

    const nextSkaterId = pickSkaterIdForChildView(skaters, childView);
    setSelectedSkaterId((current) => (current === nextSkaterId ? current : nextSkaterId));
  }, [childView, isParentMode, skaters]);

  const fileMeta = useMemo(() => {
    if (!selectedFile) {
      return "支持 mp4 / mov / avi，最大 500MB";
    }
    return `${selectedFile.name} · ${formatFileSize(selectedFile.size)}`;
  }, [selectedFile]);

  const validateFile = (file: File) => {
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (!extension || !["mp4", "mov", "avi"].includes(extension)) {
      setError("请上传 mp4、mov 或 avi 格式的视频。");
      return false;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      setError("文件超过 500MB 限制。");
      return false;
    }
    setError(null);
    return true;
  };

  const handleFile = (file: File | null) => {
    if (!file) {
      return;
    }
    if (validateFile(file)) {
      setSelectedFile(file);
    }
  };

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    handleFile(event.target.files?.[0] ?? null);
  };

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

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setIsDragging(false);
    handleFile(event.dataTransfer.files?.[0] ?? null);
  };

  const handleSubmit = async () => {
    if (!isParentMode) {
      enterParentMode();
      return;
    }

    if (!selectedFile) {
      setError("请先选择一个训练视频。");
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("action_type", actionType);
    if (selectedSkaterId) {
      formData.append("skater_id", selectedSkaterId);
    }
    if (skillCategory.trim()) {
      formData.append("skill_category", skillCategory.trim());
    }
    if (note.trim()) {
      formData.append("note", note.trim());
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await uploadAnalysis(formData);
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
    <main className="page-shell page-scroll-container min-h-screen">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="ice-orb left-[8%] top-[10%]" />
        <div className="ice-orb bottom-[12%] right-[10%]" />
        <div className="grid-ice h-full w-full" />
      </div>

      <section className="mx-auto min-h-screen w-full max-w-6xl px-6 py-6 lg:px-10">
        <TopNav />

        <div className="grid gap-8 lg:grid-cols-[1.08fr_0.92fr]">
          <div className="space-y-7 py-6">
            <div className="space-y-4">
              <p className="text-sm uppercase tracking-[0.35em] text-cyan-200/80">IceBuddy Phase 2</p>
              <h2 className="max-w-3xl text-5xl font-semibold tracking-tight text-white sm:text-6xl">
                一次上传，串起复盘、历史、趋势和 7 天训练计划。
              </h2>
              <p className="max-w-2xl text-lg leading-8 text-slate-200/78">
                训练视频会自动完成抽帧、视觉分析、结构化报告生成，并沉淀到对应选手的练习档案里，
                方便你后续查看进步趋势、做两次训练对比，以及继续生成一周训练安排。
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <div className="frost-panel">
                <p className="text-sm uppercase tracking-[0.2em] text-cyan-200/80">Upload</p>
                <p className="mt-3 text-lg text-white">上传训练视频</p>
                <p className="mt-2 text-sm text-slate-300">选择动作类型、练习档案和本次训练备注。</p>
              </div>
              <div className="frost-panel">
                <p className="text-sm uppercase tracking-[0.2em] text-cyan-200/80">Review</p>
                <p className="mt-3 text-lg text-white">生成技术诊断</p>
                <p className="mt-2 text-sm text-slate-300">识别发力时机、轴心控制和落冰稳定性问题。</p>
              </div>
              <div className="frost-panel">
                <p className="text-sm uppercase tracking-[0.2em] text-cyan-200/80">Plan</p>
                <p className="mt-3 text-lg text-white">沉淀进步档案</p>
                <p className="mt-2 text-sm text-slate-300">串到历史记录、练习时间轴和 7 天训练计划。</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-3 text-sm">
              <Link to="/history" className="pill-link">
                查看历史记录
              </Link>
              <Link to="/archive" className="pill-link">
                查看练习档案
              </Link>
              <Link to="/progress" className="pill-link">
                查看进步趋势
              </Link>
            </div>
          </div>

          <section className="frost-panel self-start lg:self-center">
            {!isParentMode ? (
              <div className="mb-5 rounded-[1.5rem] border border-amber-300/30 bg-amber-300/10 p-4 text-amber-50">
                <p className="font-semibold">坦坦模式下不能上传视频</p>
                <p className="mt-2 text-sm leading-6 text-amber-100/85">请由家长输入 PIN 后进入家长模式，再上传训练视频和管理技术复盘。</p>
                <button type="button" onClick={enterParentMode} className="mt-4 rounded-full bg-amber-300 px-4 py-2 text-sm font-semibold text-slate-950">
                  进入家长模式
                </button>
              </div>
            ) : null}

            <div className="mb-6">
              <p className="text-sm uppercase tracking-[0.25em] text-cyan-200/80">训练入口</p>
              <h2 className="mt-2 text-2xl font-semibold text-white">上传本次复盘视频</h2>
            </div>

            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={!isParentMode}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              className={`group w-full rounded-[2rem] border border-dashed px-6 py-10 text-left transition disabled:cursor-not-allowed disabled:opacity-55 ${
                isDragging ? "border-cyan-300 bg-cyan-200/10" : "border-white/15 bg-white/5 hover:bg-white/8"
              }`}
            >
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPTED_TYPES}
                className="hidden"
                onChange={handleInputChange}
              />
              <div className="flex items-start gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-cyan-200/12 text-2xl text-cyan-100">
                  ⛸️
                </div>
                <div>
                  <p className="text-xl font-medium text-white">拖拽视频到这里，或点击选择文件</p>
                  <p className="mt-2 text-sm text-slate-300">{fileMeta}</p>
                </div>
              </div>
            </button>

            <div className="mt-6 grid gap-5">
              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-200">练习档案</span>
                <select
                  value={selectedSkaterId}
                  onChange={(event) => handleSkaterChange(event.target.value)}
                  className="input-shell"
                >
                  {skaters.length ? (
                    skaters.map((skater) => (
                      <option key={skater.id} value={skater.id}>
                        {skater.display_name || skater.name}
                        {skater.level ? ` · ${skater.level}` : ""}
                      </option>
                    ))
                  ) : (
                    <option value="">正在加载练习档案…</option>
                  )}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-200">动作类型</span>
                <select value={actionType} onChange={(event) => setActionType(event.target.value)} className="input-shell">
                  {ACTION_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-200">技能分类（可选）</span>
                <input
                  value={skillCategory}
                  onChange={(event) => setSkillCategory(event.target.value)}
                  placeholder="例如：华尔兹跳 / 安全摔倒与起立 / 单足滑行"
                  className="input-shell"
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-200">训练备注（可选）</span>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={4}
                  placeholder="例如：重点看阿克塞尔起跳蹬冰是否过早，上体是否前倾。"
                  className="input-shell min-h-28 resize-y"
                />
              </label>
            </div>

            {error ? (
              <div className="mt-5 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                {error}
              </div>
            ) : null}

            <button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="mt-6 inline-flex w-full items-center justify-center rounded-full bg-cyan-300 px-5 py-4 text-base font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? "视频上传中..." : "开始分析"}
            </button>
          </section>
        </div>
      </section>
    </main>
  );
}
