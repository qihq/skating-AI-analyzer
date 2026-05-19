import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  activateProvider,
  createProvider,
  fetchProviders,
  fetchVisionVoteConfig,
  ProviderPublic,
  testProvider,
  updateProvider,
  updateVisionVoteConfig,
  VisionVoteConfig,
} from "../api/client";
import { useAppMode } from "../components/AppModeContext";

type ProviderSlot = "report" | "vision" | "vision_path_a" | "vision_path_b";

type ProviderFormState = {
  provider: string;
  api_key: string;
  model_id: string;
  vision_model: string;
  base_url: string;
};

type ProviderOption = {
  id: string;
  label: string;
  baseUrl: string;
  defaultModel: string;
  modelPlaceholder: string;
  supportsVision: boolean;
};

type SlotSection = {
  slot: ProviderSlot;
  eyebrow: string;
  title: string;
  body: string;
  activeLabel: string;
};

const PROVIDER_OPTIONS: ProviderOption[] = [
  {
    id: "qwen",
    label: "Qwen",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    defaultModel: "qwen3.6-plus",
    modelPlaceholder: "例如：qwen3.6-plus 或 qwen-vl-max-latest",
    supportsVision: true,
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    defaultModel: "deepseek-chat",
    modelPlaceholder: "例如：deepseek-chat",
    supportsVision: true,
  },
  {
    id: "doubao",
    label: "豆包",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-seed-2-0-250615",
    modelPlaceholder: "例如：doubao-seed-2-0-250615 或 ep-xxxxxxxx",
    supportsVision: true,
  },
  {
    id: "glm",
    label: "GLM",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    defaultModel: "glm-5",
    modelPlaceholder: "例如：glm-5 或 glm-4.5v",
    supportsVision: true,
  },
  {
    id: "kimi",
    label: "Kimi",
    baseUrl: "https://api.moonshot.cn/v1",
    defaultModel: "kimi-k2.5",
    modelPlaceholder: "例如：kimi-k2.5",
    supportsVision: true,
  },
  {
    id: "minimax",
    label: "MiniMax",
    baseUrl: "https://api.minimax.chat/v1",
    defaultModel: "MiniMax-Text-01",
    modelPlaceholder: "例如：MiniMax-Text-01",
    supportsVision: true,
  },
  {
    id: "openai_compatible",
    label: "OpenAI 兼容",
    baseUrl: "https://api.openai.com/v1",
    defaultModel: "custom-model",
    modelPlaceholder: "例如：gpt-4o-mini 或你的兼容模型 ID",
    supportsVision: true,
  },
  {
    id: "claude_compatible",
    label: "Claude 兼容",
    baseUrl: "https://api.anthropic.com/v1",
    defaultModel: "claude-custom-model",
    modelPlaceholder: "例如：claude-3-5-sonnet-20241022",
    supportsVision: false,
  },
];

const SLOT_SECTIONS: SlotSection[] = [
  {
    slot: "report",
    eyebrow: "Text Report",
    title: "文本报告",
    body: "用于报告生成、训练计划、记忆建议和冰宝文字能力。",
    activeLabel: "当前文本模型",
  },
  {
    slot: "vision",
    eyebrow: "Primary Vision",
    title: "主视觉",
    body: "用于主结构化视觉分析，也是 Path A / Path B 未单独配置时的回退模型池。",
    activeLabel: "当前主视觉模型",
  },
  {
    slot: "vision_path_a",
    eyebrow: "Path A",
    title: "Path A 纯视觉",
    body: "优先接收动作窗口视频片段，用来观察原始画面和动作完成情况。",
    activeLabel: "当前 Path A 模型",
  },
  {
    slot: "vision_path_b",
    eyebrow: "Path B",
    title: "Path B 骨架量化",
    body: "接收关键帧、骨架叠加图和生物力学上下文，用来做量化核验。",
    activeLabel: "当前 Path B 模型",
  },
];

const ALL_SLOTS: ProviderSlot[] = SLOT_SECTIONS.map((section) => section.slot);

function providerOption(provider: string | undefined): ProviderOption {
  return PROVIDER_OPTIONS.find((item) => item.id === provider) ?? PROVIDER_OPTIONS[0];
}

function providerLabel(provider: string | undefined): string {
  return providerOption(provider).label;
}

function optionsForSlot(slot: ProviderSlot) {
  return slot === "report" ? PROVIDER_OPTIONS : PROVIDER_OPTIONS.filter((item) => item.supportsVision);
}

function slotTitle(slot: ProviderSlot) {
  return SLOT_SECTIONS.find((section) => section.slot === slot)?.title ?? slot;
}

function formKey(provider: ProviderPublic) {
  return `${provider.slot}:${provider.id}`;
}

function draftKey(slot: ProviderSlot) {
  return `draft:${slot}`;
}

function providerNameForSave(slot: ProviderSlot, provider: string, modelId: string) {
  const model = modelId.trim();
  const suffix = model ? ` / ${model}` : "";
  return `${providerLabel(provider)} ${slotTitle(slot)}${suffix}`.slice(0, 120);
}

function defaultDraftForm(slot: ProviderSlot): ProviderFormState {
  const defaultProvider = slot === "report" ? "deepseek" : "qwen";
  const option = providerOption(defaultProvider);
  const defaultModelBySlot: Record<ProviderSlot, string> = {
    report: option.defaultModel,
    vision: "qwen3-omni-flash",
    vision_path_a: "qwen3-omni-flash",
    vision_path_b: "qwen3.6-plus",
  };
  return {
    provider: defaultProvider,
    api_key: "",
    model_id: defaultModelBySlot[slot],
    vision_model: "",
    base_url: option.baseUrl,
  };
}

function normalizeProvider(provider: ProviderPublic): ProviderFormState {
  return {
    provider: provider.provider,
    api_key: provider.api_key === "***" ? "" : provider.api_key,
    model_id: provider.model_id,
    vision_model: provider.vision_model ?? "",
    base_url: provider.base_url,
  };
}

function rebuildForms(providers: ProviderPublic[], current: Record<string, ProviderFormState> = {}) {
  const next = { ...current };
  for (const provider of providers) {
    next[formKey(provider)] = normalizeProvider(provider);
  }
  for (const slot of ALL_SLOTS) {
    next[draftKey(slot)] = current[draftKey(slot)] ?? defaultDraftForm(slot);
  }
  return next;
}

function sortProviders(items: ProviderPublic[]) {
  return [...items].sort((a, b) => {
    if (a.is_active !== b.is_active) {
      return a.is_active ? -1 : 1;
    }
    const orderA = PROVIDER_OPTIONS.findIndex((item) => item.id === a.provider);
    const orderB = PROVIDER_OPTIONS.findIndex((item) => item.id === b.provider);
    const normalizedA = orderA === -1 ? Number.MAX_SAFE_INTEGER : orderA;
    const normalizedB = orderB === -1 ? Number.MAX_SAFE_INTEGER : orderB;
    if (normalizedA !== normalizedB) {
      return normalizedA - normalizedB;
    }
    return a.created_at.localeCompare(b.created_at);
  });
}

function getStatus(provider: ProviderPublic) {
  if (provider.is_active) {
    return { label: "已激活", className: "bg-emerald-100 text-emerald-700" };
  }
  if (provider.api_key === "***") {
    return { label: "已配置", className: "bg-sky-100 text-sky-700" };
  }
  return { label: "未配置", className: "bg-slate-200 text-slate-600" };
}

function isSlot(value: string): value is ProviderSlot {
  return ALL_SLOTS.includes(value as ProviderSlot);
}

export default function ApiSettingsPage() {
  const { isParentMode, enterParentMode } = useAppMode();
  const [providers, setProviders] = useState<ProviderPublic[]>([]);
  const [forms, setForms] = useState<Record<string, ProviderFormState>>({});
  const [draftOpen, setDraftOpen] = useState<Record<ProviderSlot, boolean>>({
    report: false,
    vision: false,
    vision_path_a: false,
    vision_path_b: false,
  });
  const [expandedProviderKey, setExpandedProviderKey] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; detail: string }>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [testingKey, setTestingKey] = useState<string | null>(null);
  const [activatingKey, setActivatingKey] = useState<string | null>(null);
  const [visionVoteConfig, setVisionVoteConfig] = useState<VisionVoteConfig>({
    primary_provider_id: null,
    secondary_provider_id: null,
  });
  const [savingVisionVote, setSavingVisionVote] = useState(false);

  useEffect(() => {
    if (!isParentMode) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const [data, voteConfig] = await Promise.all([fetchProviders(), fetchVisionVoteConfig()]);
        if (cancelled) {
          return;
        }
        setProviders(data);
        setVisionVoteConfig(voteConfig);
        setForms(rebuildForms(data));
        setError(null);
      } catch {
        if (!cancelled) {
          setError("API 设置加载失败，请稍后再试。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [isParentMode]);

  const providersBySlot = useMemo(() => {
    const grouped = {} as Record<ProviderSlot, ProviderPublic[]>;
    for (const slot of ALL_SLOTS) {
      grouped[slot] = sortProviders(providers.filter((provider) => provider.slot === slot));
    }
    return grouped;
  }, [providers]);

  const visionVoteProviders = providersBySlot.vision.filter((provider) => provider.api_key === "***");
  const primaryVoteProvider = visionVoteProviders.find((provider) => provider.id === visionVoteConfig.primary_provider_id) ?? null;
  const secondaryVoteProvider = visionVoteProviders.find((provider) => provider.id === visionVoteConfig.secondary_provider_id) ?? null;

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2600);
  };

  const refreshProviders = (nextProviders: ProviderPublic[]) => {
    setProviders(nextProviders);
    setForms((current) => rebuildForms(nextProviders, current));
  };

  const setFormField = (key: string, field: keyof ProviderFormState, value: string) => {
    setForms((current) => ({
      ...current,
      [key]: {
        ...(current[key] ?? defaultDraftForm("vision")),
        [field]: value,
      },
    }));
  };

  const setFormProvider = (key: string, slot: ProviderSlot, provider: string) => {
    const option = providerOption(provider);
    setForms((current) => ({
      ...current,
      [key]: {
        ...(current[key] ?? defaultDraftForm(slot)),
        provider,
        base_url: option.baseUrl,
        model_id: option.defaultModel,
      },
    }));
  };

  const handleCreateProvider = async (slot: ProviderSlot) => {
    const key = draftKey(slot);
    const form = forms[key] ?? defaultDraftForm(slot);
    const selectedProvider = providerOption(form.provider);
    if (!form.api_key.trim()) {
      setError("请先填写 API Key。");
      return;
    }
    if (!form.model_id.trim()) {
      setError("请先填写模型 ID。");
      return;
    }

    setSavingKey(key);
    setError(null);
    try {
      const created = await createProvider({
        slot,
        provider: form.provider,
        name: providerNameForSave(slot, form.provider, form.model_id),
        base_url: form.base_url.trim() || selectedProvider.baseUrl,
        model_id: form.model_id.trim(),
        vision_model: slot !== "report" && selectedProvider.supportsVision ? form.vision_model.trim() || null : null,
        api_key: form.api_key.trim(),
        notes: `模型实例：${slotTitle(slot)}`,
      });
      refreshProviders([...providers, created]);
      setForms((current) => ({ ...current, [key]: defaultDraftForm(slot) }));
      setDraftOpen((current) => ({ ...current, [slot]: false }));
      setExpandedProviderKey(formKey(created));
      showNotice(`${providerLabel(created.provider)} / ${created.model_id} 已创建。`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "创建模型实例失败，请稍后再试。"));
      } else {
        setError("创建模型实例失败，请稍后再试。");
      }
    } finally {
      setSavingKey(null);
    }
  };

  const handleSave = async (provider: ProviderPublic) => {
    const slot = isSlot(provider.slot) ? provider.slot : "vision";
    const key = formKey(provider);
    const form = forms[key] ?? normalizeProvider(provider);
    const selectedProvider = providerOption(form.provider);
    if (!form.api_key.trim() && provider.api_key !== "***") {
      setError("请先填写 API Key。");
      return;
    }
    if (!form.model_id.trim()) {
      setError("请先填写模型 ID。");
      return;
    }

    setSavingKey(key);
    setError(null);
    try {
      const updated = await updateProvider(provider.id, {
        provider: form.provider,
        name: providerNameForSave(slot, form.provider, form.model_id),
        api_key: form.api_key.trim() || undefined,
        model_id: form.model_id.trim(),
        vision_model: slot !== "report" && selectedProvider.supportsVision ? form.vision_model.trim() || null : null,
        base_url: form.base_url.trim() || selectedProvider.baseUrl,
      });
      refreshProviders(providers.map((item) => (item.id === updated.id ? updated : item)));
      showNotice(`${providerLabel(updated.provider)} / ${updated.model_id} 已保存。`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "保存失败，请稍后再试。"));
      } else {
        setError("保存失败，请稍后再试。");
      }
    } finally {
      setSavingKey(null);
    }
  };

  const handleTest = async (provider: ProviderPublic) => {
    const key = formKey(provider);
    setTestingKey(key);
    setError(null);
    try {
      const result = await testProvider(provider.id);
      setTestResults((current) => ({ ...current, [key]: result }));
      showNotice(result.success ? `${providerLabel(provider.provider)} / ${provider.model_id} 连接成功。` : result.detail);
      if (!result.success) {
        setError(result.detail);
      }
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? String(requestError.response?.data?.detail ?? "测试连接失败。")
        : "测试连接失败。";
      setTestResults((current) => ({ ...current, [key]: { success: false, detail } }));
      setError(detail);
    } finally {
      setTestingKey(null);
    }
  };

  const handleActivate = async (provider: ProviderPublic) => {
    const key = formKey(provider);
    setActivatingKey(key);
    setError(null);
    try {
      const updated = await activateProvider(provider.id);
      refreshProviders(
        providers.map((item) => (item.slot === updated.slot ? { ...item, is_active: item.id === updated.id } : item)),
      );
      showNotice(`${providerLabel(updated.provider)} / ${updated.model_id} 已设为${slotTitle(updated.slot as ProviderSlot)}。`);
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "切换失败，请稍后再试。"));
      } else {
        setError("切换失败，请稍后再试。");
      }
    } finally {
      setActivatingKey(null);
    }
  };

  const handleVisionVoteSave = async () => {
    if (!visionVoteConfig.primary_provider_id) {
      setError("请先选择主视觉投票模型。");
      return;
    }
    if (!visionVoteConfig.secondary_provider_id) {
      setError("请先选择辅助投票模型；如果只想用同一个模型，可以选择相同实例。");
      return;
    }

    setSavingVisionVote(true);
    setError(null);
    try {
      const updated = await updateVisionVoteConfig(visionVoteConfig);
      setVisionVoteConfig(updated);
      showNotice("主视觉投票配置已保存。");
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "主视觉投票配置保存失败。"));
      } else {
        setError("主视觉投票配置保存失败。");
      }
    } finally {
      setSavingVisionVote(false);
    }
  };

  const renderProviderSelect = (key: string, slot: ProviderSlot, value: string) => (
    <label className="space-y-2">
      <span className="text-sm font-medium text-slate-700">模型公司</span>
      <select value={value} onChange={(event) => setFormProvider(key, slot, event.target.value)} className="app-select">
        {optionsForSlot(slot).map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );

  const renderProviderCard = (provider: ProviderPublic, section: SlotSection) => {
    const key = formKey(provider);
    const form = forms[key] ?? normalizeProvider(provider);
    const status = getStatus(provider);
    const isExpanded = expandedProviderKey === key;
    const result = testResults[key];
    const connectionLabel = result ? (result.success ? "连接正常" : "连接失败") : provider.api_key === "***" ? "待测试" : "未配置 Key";
    const connectionClass = result
      ? result.success
        ? "bg-emerald-100 text-emerald-700"
        : "bg-rose-100 text-rose-600"
      : provider.api_key === "***"
        ? "bg-amber-100 text-amber-700"
        : "bg-slate-200 text-slate-600";

    return (
      <article key={provider.id} className="rounded-[28px] border border-slate-200 bg-slate-50 p-5">
        <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-2xl font-semibold text-slate-900">{providerLabel(provider.provider)}</h3>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${status.className}`}>{status.label}</span>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${connectionClass}`}>{connectionLabel}</span>
              {provider.is_active ? (
                <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">{section.activeLabel}</span>
              ) : null}
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
              <span className="rounded-full bg-white px-3 py-1">用途：{section.title}</span>
              <span className="rounded-full bg-white px-3 py-1">模型 ID：{provider.model_id || "未填写"}</span>
              <span className="rounded-full bg-white px-3 py-1">API Key：{provider.api_key === "***" ? "已保存" : "未保存"}</span>
            </div>
            <p className="mt-3 truncate text-sm text-slate-500">Base URL: {provider.base_url}</p>
            {result?.detail ? <p className="mt-2 text-sm leading-6 text-slate-500">{result.detail}</p> : null}
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setExpandedProviderKey((current) => (current === key ? null : key))}
              className="app-pill min-h-[44px] px-4 text-sm font-semibold"
            >
              {isExpanded ? "收起" : "配置"}
            </button>
            <button
              type="button"
              onClick={() => void handleTest(provider)}
              disabled={testingKey === key || provider.api_key !== "***"}
              className="app-pill min-h-[44px] px-4 text-sm font-semibold"
            >
              {testingKey === key ? "测试中..." : "测试"}
            </button>
            {!provider.is_active ? (
              <button
                type="button"
                onClick={() => void handleActivate(provider)}
                disabled={activatingKey === key}
                className="app-pill min-h-[44px] px-4 text-sm font-semibold"
              >
                {activatingKey === key ? "切换中..." : "设为当前"}
              </button>
            ) : null}
          </div>
        </div>

        {isExpanded ? (
          <div className="mt-5 grid gap-4 rounded-[24px] border border-white bg-white p-4">
            <div className="grid gap-4 tablet:grid-cols-2">
              {renderProviderSelect(key, section.slot, form.provider)}
              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-700">模型 ID</span>
                <input
                  value={form.model_id}
                  onChange={(event) => setFormField(key, "model_id", event.target.value)}
                  className="app-input"
                  placeholder={providerOption(form.provider).modelPlaceholder}
                />
              </label>
            </div>

            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">API Key</span>
              <input
                value={form.api_key}
                onChange={(event) => setFormField(key, "api_key", event.target.value)}
                className="app-input"
                placeholder={provider.api_key === "***" ? "已保存，可留空不改" : "请输入 API Key"}
              />
            </label>

            {section.slot !== "report" ? (
              <label className="space-y-2">
                <span className="text-sm font-medium text-slate-700">备用视觉模型（可选）</span>
                <input
                  value={form.vision_model}
                  onChange={(event) => setFormField(key, "vision_model", event.target.value)}
                  className="app-input"
                  placeholder="可选：备用模型 ID"
                />
              </label>
            ) : null}

            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">API 根地址</span>
              <input
                value={form.base_url}
                onChange={(event) => setFormField(key, "base_url", event.target.value)}
                className="app-input"
              />
            </label>

            <div className="flex flex-col gap-3 tablet:flex-row">
              <button
                type="button"
                onClick={() => void handleSave(provider)}
                disabled={savingKey === key}
                className="min-h-[48px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {savingKey === key ? "保存中..." : "保存实例"}
              </button>
            </div>
          </div>
        ) : null}
      </article>
    );
  };

  const renderDraftCard = (slot: ProviderSlot) => {
    const key = draftKey(slot);
    const form = forms[key] ?? defaultDraftForm(slot);
    const option = providerOption(form.provider);

    return (
      <div className="rounded-[28px] border border-dashed border-slate-300 bg-white p-5">
        <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
          <div>
            <h3 className="text-xl font-semibold text-slate-900">新增模型实例</h3>
            <p className="mt-2 text-sm leading-7 text-slate-500">
              可以继续选择 {providerLabel(form.provider)}，只要填写不同模型 ID，就能在同一公司下保存多个实例。
            </p>
          </div>
          <button
            type="button"
            onClick={() => setDraftOpen((current) => ({ ...current, [slot]: false }))}
            className="app-pill min-h-[44px] px-4 text-sm font-semibold"
          >
            收起
          </button>
        </div>

        <div className="mt-5 grid gap-4">
          <div className="grid gap-4 tablet:grid-cols-2">
            {renderProviderSelect(key, slot, form.provider)}
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">模型 ID</span>
              <input
                value={form.model_id}
                onChange={(event) => setFormField(key, "model_id", event.target.value)}
                className="app-input"
                placeholder={option.modelPlaceholder}
              />
            </label>
          </div>

          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">API Key</span>
            <input
              value={form.api_key}
              onChange={(event) => setFormField(key, "api_key", event.target.value)}
              className="app-input"
              placeholder="请输入 API Key"
            />
          </label>

          {slot !== "report" ? (
            <label className="space-y-2">
              <span className="text-sm font-medium text-slate-700">备用视觉模型（可选）</span>
              <input
                value={form.vision_model}
                onChange={(event) => setFormField(key, "vision_model", event.target.value)}
                className="app-input"
                placeholder="可选：备用模型 ID"
              />
            </label>
          ) : null}

          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">API 根地址</span>
            <input
              value={form.base_url}
              onChange={(event) => setFormField(key, "base_url", event.target.value)}
              className="app-input"
            />
          </label>

          <button
            type="button"
            onClick={() => void handleCreateProvider(slot)}
            disabled={savingKey === key}
            className="min-h-[48px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60 tablet:w-fit"
          >
            {savingKey === key ? "创建中..." : "创建实例"}
          </button>
        </div>
      </div>
    );
  };

  if (!isParentMode) {
    return (
      <section className="app-card mx-auto max-w-3xl p-8 text-center tablet:p-10">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">API Settings</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">API 设置</h1>
        <p className="mt-4 text-base leading-8 text-slate-500">进入家长模式后，才可以配置文本模型和视觉模型实例。</p>
        <button
          type="button"
          onClick={() => void enterParentMode()}
          className="mt-8 min-h-[48px] rounded-full bg-blue-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
        >
          进入家长模式
        </button>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">API Settings</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-900 tablet:text-4xl">模型实例管理</h1>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/debug" className="app-pill text-sm font-semibold">
            调试日志
          </Link>
          <Link to="/settings" className="app-pill text-sm font-semibold">
            返回家长设置
          </Link>
        </div>
      </div>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}

      <section className="app-card p-6 tablet:p-8">
        <p className="max-w-4xl text-base leading-8 text-slate-500">
          这里按用途 slot 管理模型实例：文本报告、主视觉、Path A、Path B 和主视觉投票。卡片标题只显示模型公司，
          具体版本通过“模型 ID”区分，所以同一个公司可以同时保存多个不同模型。
        </p>
      </section>

      <div className="space-y-6">
        {SLOT_SECTIONS.map((section) => {
          const sectionProviders = providersBySlot[section.slot];
          return (
            <section key={section.slot} className="app-card p-6 tablet:p-8">
              <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
                <div className="max-w-4xl">
                  <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">{section.eyebrow}</p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-900">{section.title}</h2>
                  <p className="mt-3 text-sm leading-7 text-slate-500">{section.body}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setDraftOpen((current) => ({ ...current, [section.slot]: !current[section.slot] }))}
                  className="app-pill min-h-[46px] px-5 text-sm font-semibold"
                >
                  {draftOpen[section.slot] ? "收起新增" : "新增模型实例"}
                </button>
              </div>

              <div className="mt-6 grid gap-5">
                {draftOpen[section.slot] ? renderDraftCard(section.slot) : null}
                {sectionProviders.map((provider) => renderProviderCard(provider, section))}
                {!sectionProviders.length && !draftOpen[section.slot] ? (
                  <div className="rounded-[28px] border border-dashed border-slate-300 bg-slate-50 px-5 py-5 text-sm leading-7 text-slate-500">
                    当前用途还没有模型实例。点击“新增模型实例”后，可以选择模型公司并填写模型 ID。
                  </div>
                ) : null}
              </div>
            </section>
          );
        })}
      </div>

      <section className="app-card p-6 tablet:p-8">
        <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Primary Vision Voting</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">主视觉投票</h2>
            <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-500">
              这里只从“主视觉”slot 里选择两个已保存 API Key 的模型实例，用于主视觉分析内部投票。Path A 和 Path B 仍按各自 slot 选择当前激活模型。
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleVisionVoteSave()}
            disabled={savingVisionVote || !visionVoteProviders.length}
            className="min-h-[48px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {savingVisionVote ? "保存中..." : "保存投票配置"}
          </button>
        </div>

        <div className="mt-6 grid gap-4 tablet:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">主投票模型</span>
            <select
              value={visionVoteConfig.primary_provider_id ?? ""}
              onChange={(event) =>
                setVisionVoteConfig((current) => ({
                  ...current,
                  primary_provider_id: event.target.value || null,
                }))
              }
              className="app-select"
            >
              <option value="">请选择模型实例</option>
              {visionVoteProviders.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {providerLabel(provider.provider)} / {provider.model_id}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium text-slate-700">辅助投票模型</span>
            <select
              value={visionVoteConfig.secondary_provider_id ?? ""}
              onChange={(event) =>
                setVisionVoteConfig((current) => ({
                  ...current,
                  secondary_provider_id: event.target.value || null,
                }))
              }
              className="app-select"
            >
              <option value="">请选择模型实例</option>
              {visionVoteProviders.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {providerLabel(provider.provider)} / {provider.model_id}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-5 grid gap-3 tablet:grid-cols-2">
          <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            <p className="font-semibold text-slate-900">主投票</p>
            <p className="mt-1">{primaryVoteProvider ? `${providerLabel(primaryVoteProvider.provider)} / ${primaryVoteProvider.model_id}` : "尚未选择"}</p>
          </div>
          <div className="rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            <p className="font-semibold text-slate-900">辅助投票</p>
            <p className="mt-1">
              {secondaryVoteProvider ? `${providerLabel(secondaryVoteProvider.provider)} / ${secondaryVoteProvider.model_id}` : "尚未选择"}
            </p>
          </div>
        </div>

        {!visionVoteProviders.length ? (
          <div className="mt-5 rounded-[22px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            请先在“主视觉”slot 中保存至少一个带 API Key 的模型实例。
          </div>
        ) : null}
      </section>
    </div>
  );
}
