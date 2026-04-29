import axios from "axios";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  ApiConnectionTestResponse,
  BackupFile,
  changePin,
  createBackup,
  fetchBackups,
  fetchPoseRuntimeStatus,
  fetchSkaters,
  fetchStorageStats,
  fetchSystemInfo,
  PoseRuntimeStatus,
  restoreBackup,
  Skater,
  StorageStats,
  SystemInfo,
  testActiveApiConnection,
  updateSkater,
} from "../api/client";
import { getAnalysisErrorMessage } from "../constants/analysisErrors";
import { useAppMode } from "../components/AppModeContext";
import PinInput from "../components/PinInput";

type PinLengthOption = 4 | 5 | 6;

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatMegabytes(value: number) {
  return `${value.toFixed(1)} MB`;
}

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateString));
}

export default function SettingsPage() {
  const { isParentMode, enterParentMode, pinLength, refreshPinState } = useAppMode();
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);
  const [backups, setBackups] = useState<BackupFile[]>([]);
  const [poseRuntime, setPoseRuntime] = useState<PoseRuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingSkaterId, setSavingSkaterId] = useState<string | null>(null);
  const [isPinModalOpen, setIsPinModalOpen] = useState(false);
  const [oldPin, setOldPin] = useState("");
  const [newPinLength, setNewPinLength] = useState<PinLengthOption>(4);
  const [newPin, setNewPin] = useState("");
  const [confirmNewPin, setConfirmNewPin] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const [isSavingPin, setIsSavingPin] = useState(false);
  const [isCreatingBackup, setIsCreatingBackup] = useState(false);
  const [restoringFilename, setRestoringFilename] = useState<string | null>(null);
  const [apiTestResult, setApiTestResult] = useState<ApiConnectionTestResponse | null>(null);
  const [isTestingApi, setIsTestingApi] = useState(false);

  useEffect(() => {
    setNewPinLength((pinLength >= 4 && pinLength <= 6 ? pinLength : 4) as PinLengthOption);
  }, [pinLength]);

  const loadSettingsData = async () => {
    const [skaterData, systemData, storageData, backupData, poseRuntimeData] = await Promise.all([
      fetchSkaters(),
      fetchSystemInfo(),
      fetchStorageStats(),
      fetchBackups(),
      fetchPoseRuntimeStatus(),
    ]);
    setSkaters(skaterData);
    setSystemInfo(systemData);
    setStorageStats(storageData);
    setBackups(backupData);
    setPoseRuntime(poseRuntimeData);
  };

  useEffect(() => {
    if (!isParentMode) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const [skaterData, systemData, storageData, backupData, poseRuntimeData] = await Promise.all([
          fetchSkaters(),
          fetchSystemInfo(),
          fetchStorageStats(),
          fetchBackups(),
          fetchPoseRuntimeStatus(),
        ]);
        if (cancelled) {
          return;
        }
        setSkaters(skaterData);
        setSystemInfo(systemData);
        setStorageStats(storageData);
        setBackups(backupData);
        setPoseRuntime(poseRuntimeData);
      } catch {
        if (!cancelled) {
          setError("家长设置加载失败，请稍后重试。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [isParentMode]);

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2600);
  };

  const handleSkaterChange = (skaterId: string, field: "display_name" | "avatar_emoji" | "birth_year", value: string) => {
    setSkaters((current) =>
      current.map((skater) =>
        skater.id === skaterId
          ? {
              ...skater,
              [field]: field === "birth_year" ? Number(value || skater.birth_year) : value,
            }
          : skater,
      ),
    );
  };

  const handleSkaterSave = async (skater: Skater) => {
    setSavingSkaterId(skater.id);
    setError(null);
    try {
      const updated = await updateSkater(skater.id, {
        display_name: skater.display_name,
        avatar_emoji: skater.avatar_emoji,
        birth_year: skater.birth_year,
      });
      setSkaters((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      showNotice(`已保存 ${updated.display_name || updated.name} 的展示信息。`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "选手信息保存失败。"));
      } else {
        setError("选手信息保存失败。");
      }
    } finally {
      setSavingSkaterId(null);
    }
  };

  const openPinModal = () => {
    setOldPin("");
    setNewPin("");
    setConfirmNewPin("");
    setPinError(null);
    setNewPinLength((pinLength >= 4 && pinLength <= 6 ? pinLength : 4) as PinLengthOption);
    setIsPinModalOpen(true);
  };

  const closePinModal = () => {
    setIsPinModalOpen(false);
    setOldPin("");
    setNewPin("");
    setConfirmNewPin("");
    setPinError(null);
    setIsSavingPin(false);
  };

  const handleChangePinLength = (nextLength: PinLengthOption) => {
    setNewPinLength(nextLength);
    setNewPin((current) => current.slice(0, nextLength));
    setConfirmNewPin((current) => current.slice(0, nextLength));
    setPinError(null);
  };

  const handleSavePin = async () => {
    if (!new RegExp(`^\\d{${pinLength}}$`).test(oldPin)) {
      setPinError("旧 PIN 位数不正确。");
      return;
    }
    if (!new RegExp(`^\\d{${newPinLength}}$`).test(newPin)) {
      setPinError(`新 PIN 必须是 ${newPinLength} 位数字。`);
      return;
    }
    if (newPin !== confirmNewPin) {
      setPinError("两次输入的新 PIN 不一致。");
      return;
    }

    setIsSavingPin(true);
    setPinError(null);
    try {
      const result = await changePin(oldPin, newPin);
      if (!result.success) {
        setPinError(result.reason ?? "旧 PIN 不正确。");
        setOldPin("");
        return;
      }
      await refreshPinState();
      closePinModal();
      showNotice("家长 PIN 已更新。");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setPinError(String(requestError.response?.data?.detail ?? "PIN 更新失败，请稍后重试。"));
      } else {
        setPinError("PIN 更新失败，请稍后重试。");
      }
    } finally {
      setIsSavingPin(false);
    }
  };

  const handleCreateBackup = async () => {
    setIsCreatingBackup(true);
    setError(null);
    try {
      const result = await createBackup();
      await loadSettingsData();
      showNotice(`${result.filename} 已创建。`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "手动备份失败。"));
      } else {
        setError("手动备份失败。");
      }
    } finally {
      setIsCreatingBackup(false);
    }
  };

  const handleRestoreBackup = async (filename: string) => {
    const confirmed = window.confirm(`确认恢复备份「${filename}」吗？这会覆盖当前 data 数据。`);
    if (!confirmed) {
      return;
    }

    setRestoringFilename(filename);
    setError(null);
    try {
      const result = await restoreBackup(filename);
      await loadSettingsData();
      showNotice(result.detail);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "恢复备份失败。"));
      } else {
        setError("恢复备份失败。");
      }
    } finally {
      setRestoringFilename(null);
    }
  };

  const handleTestApi = async () => {
    setIsTestingApi(true);
    setError(null);
    try {
      const result = await testActiveApiConnection();
      setApiTestResult(result);
      if (result.status === "ok") {
        showNotice(`API 连接正常（延迟 ${result.latency_ms ?? 0}ms）。`);
      }
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "API 连接测试失败。"));
      } else {
        setError("API 连接测试失败。");
      }
    } finally {
      setIsTestingApi(false);
    }
  };

  const poseModeLabel = poseRuntime?.mode === "multi_pose" ? "二期多姿态已启用" : "当前为一期兼容模式";
  const poseModeBadgeClass =
    poseRuntime?.mode === "multi_pose"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : "border-amber-200 bg-amber-50 text-amber-700";
  const poseReasonText =
    poseRuntime?.reason === "configured"
      ? "模型已加载，可直接使用多姿态候选。"
      : poseRuntime?.reason === "missing_model_file"
        ? "已配置模型路径，但当前挂载目录里没有可读取的 .task 文件。"
        : "尚未配置模型路径，系统会继续使用一期单人裁剪 Pose。";
  const poseNextStepText =
    poseRuntime?.mode === "multi_pose"
      ? "当前环境已经具备二期主滑手多候选能力，可以直接去上传分析页验证多人场景。"
      : "将模型文件放入 ./models/pose_landmarker_heavy.task，并在 .env 中设置 MEDIAPIPE_POSE_TASK_PATH=/models/pose_landmarker_heavy.task 后重启服务。";
  const posePathText = poseRuntime?.model_path ?? "未设置";

  if (!isParentMode) {
    return (
      <div className="space-y-6">
        <section className="app-card mx-auto max-w-3xl p-8 text-center tablet:p-10">
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Parent Settings</p>
          <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">家长设置</h1>
          <p className="mt-4 text-base leading-8 text-slate-500">
            进入家长模式后，才可以管理选手信息、API 兼容配置、手动备份和系统数据。
          </p>
          <button
            type="button"
            onClick={() => void enterParentMode()}
            className="mt-8 min-h-[48px] rounded-full bg-blue-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
          >
            进入家长模式
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}

      <section className="app-card p-6 tablet:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Parent Settings</p>
        <h1 className="mt-3 text-3xl font-semibold text-slate-900 tablet:text-4xl">家长设置</h1>
        <p className="mt-4 max-w-3xl text-base leading-8 text-slate-500">
          这里统一管理账号安全、选手展示信息、API 兼容配置，以及本地数据备份与恢复。
        </p>
      </section>

      <section className="grid gap-6 web:grid-cols-[1.04fr_0.96fr]">
        <div className="space-y-6">
          <section className="app-card p-6 tablet:p-7">
            <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Pose Runtime</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">二期姿态模式</h2>
                <p className="mt-3 text-sm leading-7 text-slate-500">
                  这里可以直接确认当前环境是否真正启用了二期多姿态模型，以及为什么会回落到一期兼容模式。
                </p>
              </div>
              <div className={`inline-flex rounded-full border px-4 py-2 text-sm font-semibold ${poseModeBadgeClass}`}>
                {poseModeLabel}
              </div>
            </div>

            <div className="mt-6 grid gap-4 sm:grid-cols-2">
              <div className="stat-panel">
                <p className="stat-label">运行模式</p>
                <p className="stat-value text-[1.1rem]">
                  {poseRuntime?.mode === "multi_pose" ? "multi_pose" : "fallback_single_pose"}
                </p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">多姿态上限</p>
                <p className="stat-value">{poseRuntime?.num_poses ?? 4}</p>
              </div>
            </div>

            <div className="mt-4 rounded-[24px] border border-slate-200 bg-slate-50 p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-700">模型路径</p>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">
                  {poseRuntime?.configured ? "已配置" : "未配置"}
                </p>
              </div>
              <p className="mt-3 break-all rounded-[18px] bg-white px-4 py-3 font-mono text-xs leading-6 text-slate-600">
                {posePathText}
              </p>
              <div className="mt-4 flex flex-wrap gap-3 text-sm">
                <span
                  className={`rounded-full px-3 py-1 font-medium ${
                    poseRuntime?.model_exists ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"
                  }`}
                >
                  {poseRuntime?.model_exists ? "模型文件可读" : "模型文件不可用"}
                </span>
                <span className="rounded-full bg-slate-200 px-3 py-1 font-medium text-slate-600">{poseReasonText}</span>
              </div>
            </div>

            <div className="mt-4 rounded-[24px] border border-blue-100 bg-blue-50 p-5">
              <p className="text-sm font-semibold text-blue-700">启用说明</p>
              <p className="mt-2 text-sm leading-7 text-blue-700">{poseNextStepText}</p>
            </div>

            <div className="mt-5 flex flex-wrap gap-3">
              <Link to="/review" className="app-pill text-sm font-semibold">
                去上传页验证
              </Link>
              <Link to="/settings/api" className="app-pill text-sm font-semibold">
                检查 API 配置
              </Link>
            </div>
          </section>

          <section className="app-card p-6 tablet:p-7">
            <div className="flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Security</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">安全设置</h2>
                <p className="mt-3 text-sm leading-7 text-slate-500">家长 PIN 用于进入家长模式、删除分析记录和执行敏感操作确认。</p>
              </div>
              <button
                type="button"
                onClick={openPinModal}
                className="min-h-[46px] rounded-full bg-blue-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-blue-600"
              >
                修改 PIN
              </button>
            </div>

            <div className="settings-row mt-5 rounded-[24px] border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-medium text-slate-600">当前 PIN 位数</p>
              <p className="mt-2 text-3xl font-semibold text-slate-900">{pinLength} 位</p>
            </div>
          </section>

          <section className="app-card p-6 tablet:p-7">
            <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">API</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">API 配置</h2>
                <p className="mt-3 text-sm leading-7 text-slate-500">检查当前激活的视觉模型和文本模型是否连接正常，也可以进入 API 页面切换供应商。</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Link to="/settings/api" className="app-pill text-sm font-semibold">
                  打开 API 设置
                </Link>
                <button
                  type="button"
                  onClick={() => void handleTestApi()}
                  disabled={isTestingApi}
                  className="min-h-[44px] rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isTestingApi ? "连接中..." : "🔌 测试连接"}
                </button>
              </div>
            </div>

            <div className="mt-6 rounded-[24px] border border-slate-200 bg-slate-50 p-5">
              {!apiTestResult ? (
                <p className="text-sm leading-7 text-slate-500">点击“测试连接”后，系统会用当前已保存的 API Key 发送一次极小请求，用来验证配置是否可用。</p>
              ) : apiTestResult.status === "ok" ? (
                <p className="text-sm font-medium text-emerald-700">✅ 连接正常（延迟 {apiTestResult.latency_ms ?? 0}ms）</p>
              ) : (
                <>
                  <p className="text-sm font-medium text-rose-600">
                    ❌ {getAnalysisErrorMessage(apiTestResult.error_code).title}
                    {apiTestResult.message ? ` — ${apiTestResult.message}` : ""}
                  </p>
                  <p className="mt-2 text-sm leading-7 text-slate-500">{getAnalysisErrorMessage(apiTestResult.error_code).hint}</p>
                </>
              )}
            </div>
          </section>

          <section className="app-card p-6 tablet:p-7">
            <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Profiles</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">选手展示信息</h2>
                <p className="mt-3 text-sm leading-7 text-slate-500">这里修改首页和报告页里展示的昵称、头像和出生年份。</p>
              </div>
              <Link to="/settings/api" className="app-pill text-sm font-semibold">
                打开 API 设置
              </Link>
            </div>

            <div className="mt-6 grid gap-4">
              {skaters.map((skater) => (
                <article key={skater.id} className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                  <div className="grid gap-4 md:grid-cols-3">
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-slate-700">显示名</span>
                      <input
                        value={skater.display_name}
                        onChange={(event) => handleSkaterChange(skater.id, "display_name", event.target.value)}
                        className="app-input"
                        placeholder="显示名"
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-slate-700">头像 Emoji</span>
                      <input
                        value={skater.avatar_emoji}
                        onChange={(event) => handleSkaterChange(skater.id, "avatar_emoji", event.target.value)}
                        className="app-input"
                        placeholder="🐯"
                      />
                    </label>
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-slate-700">出生年份</span>
                      <input
                        value={skater.birth_year}
                        onChange={(event) => handleSkaterChange(skater.id, "birth_year", event.target.value)}
                        className="app-input"
                        placeholder="2021"
                      />
                    </label>
                  </div>

                  <div className="settings-row mt-4 flex flex-wrap items-center justify-between gap-3 rounded-[20px]">
                    <p className="text-sm text-slate-500">内部名：{skater.name}</p>
                    <button
                      type="button"
                      onClick={() => void handleSkaterSave(skater)}
                      disabled={savingSkaterId === skater.id}
                      className="min-h-[44px] rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {savingSkaterId === skater.id ? "保存中..." : "保存"}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        </div>

        <div className="space-y-6">
          <section className="app-card p-6 tablet:p-7">
            <div className="flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Backup</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">备份与恢复</h2>
                <p className="mt-3 text-sm leading-7 text-slate-500">支持手动触发备份，也可以从已有备份恢复本地 data 数据。</p>
              </div>
              <button
                type="button"
                onClick={() => void handleCreateBackup()}
                disabled={isCreatingBackup}
                className="min-h-[46px] rounded-full bg-blue-500 px-5 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCreatingBackup ? "备份中..." : "立即备份"}
              </button>
            </div>

            <div className="mt-5 space-y-3">
              {backups.length ? (
                backups.map((backup) => (
                  <article key={backup.filename} className="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
                    <div className="settings-row flex flex-wrap items-center justify-between gap-3 rounded-[18px]">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{backup.filename}</p>
                        <p className="mt-1 text-sm text-slate-500">
                          {formatDate(backup.created_at)} · {formatBytes(backup.size_bytes)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => void handleRestoreBackup(backup.filename)}
                        disabled={restoringFilename === backup.filename}
                        className="min-h-[42px] rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {restoringFilename === backup.filename ? "恢复中..." : "恢复"}
                      </button>
                    </div>
                  </article>
                ))
              ) : (
                <div className="rounded-[22px] border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-sm leading-7 text-slate-500">
                  还没有手动备份。点击“立即备份”后，会在本地 `backups` 目录生成 zip 备份文件。
                </div>
              )}
            </div>
          </section>

          <section className="app-card p-6 tablet:p-7">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">System</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">系统占用</h2>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <div className="stat-panel">
                <p className="stat-label">版本号</p>
                <p className="stat-value">{systemInfo?.version ?? "--"}</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">数据库</p>
                <p className="stat-value">{systemInfo ? formatBytes(systemInfo.db_size_bytes) : "--"}</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">上传区</p>
                <p className="stat-value">{storageStats ? formatMegabytes(storageStats.uploads_mb) : "--"}</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">备份区</p>
                <p className="stat-value">{storageStats ? formatMegabytes(storageStats.backups_mb) : "--"}</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">归档区</p>
                <p className="stat-value">{storageStats ? formatMegabytes(storageStats.archive_mb) : "--"}</p>
              </div>
              <div className="stat-panel">
                <p className="stat-label">总占用</p>
                <p className="stat-value">{storageStats ? formatMegabytes(storageStats.total_mb) : "--"}</p>
              </div>
            </div>

            <div className="settings-row mt-5 rounded-[24px] border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-medium text-slate-600">已归档视频</p>
              <p className="mt-2 text-3xl font-semibold text-slate-900">{storageStats?.archived_count ?? "--"}</p>
            </div>
          </section>
        </div>
      </section>

      {isPinModalOpen ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/36 px-4 backdrop-blur-sm">
          <section className="app-card w-full max-w-xl p-6 tablet:p-7">
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Security</p>
            <h2 className="mt-3 text-2xl font-semibold text-slate-900">修改家长 PIN</h2>

            <div className="mt-6 space-y-6">
              <div>
                <p className="mb-3 text-sm font-medium text-slate-700">旧 PIN（{pinLength} 位）</p>
                <PinInput length={pinLength} value={oldPin} onChange={setOldPin} error={Boolean(pinError?.includes("旧"))} autoFocus label="旧 PIN" />
              </div>

              <div>
                <p className="text-sm font-medium text-slate-700">新 PIN 位数</p>
                <div className="mt-3 inline-flex rounded-full bg-slate-100 p-1">
                  {[4, 5, 6].map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => handleChangePinLength(option as PinLengthOption)}
                      className={`min-h-[44px] rounded-full px-4 text-sm font-semibold transition ${
                        newPinLength === option ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
                      }`}
                    >
                      {option} 位
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-3 text-sm font-medium text-slate-700">新 PIN</p>
                <PinInput length={newPinLength} value={newPin} onChange={setNewPin} error={Boolean(pinError && !pinError.includes("旧") && newPin.length === newPinLength)} label="新 PIN" />
              </div>

              <div>
                <p className="mb-3 text-sm font-medium text-slate-700">确认新 PIN</p>
                <PinInput
                  length={newPinLength}
                  value={confirmNewPin}
                  onChange={setConfirmNewPin}
                  error={Boolean(pinError && confirmNewPin.length === newPinLength)}
                  label="确认新 PIN"
                />
              </div>
            </div>

            {pinError ? <p className="mt-5 text-sm text-rose-500">{pinError}</p> : null}

            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-end">
              <button type="button" onClick={closePinModal} className="app-pill">
                取消
              </button>
              <button
                type="button"
                onClick={() => void handleSavePin()}
                disabled={isSavingPin || oldPin.length !== pinLength || newPin.length !== newPinLength || confirmNewPin.length !== newPinLength}
                className="min-h-[44px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSavingPin ? "保存中..." : "保存"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
