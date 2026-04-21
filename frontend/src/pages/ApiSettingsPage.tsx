import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { activateProvider, fetchProviders, ProviderPublic, testProvider, updateProvider } from "../api/client";
import { useAppMode } from "../components/AppModeContext";

type ProviderTab =
  | "deepseek"
  | "doubao"
  | "minimax"
  | "glm"
  | "qwen"
  | "openai_compatible"
  | "claude_compatible";
type ProviderSlot = "report" | "vision";

type ProviderFormState = {
  api_key: string;
  model_id: string;
  vision_model: string;
  base_url: string;
};

type ProviderConfig = {
  title: string;
  body: string;
  baseUrl: string;
  note: string;
  modelLabel: string;
  modelPlaceholder: string;
  supportsVision: boolean;
};

const REPORT_TAB_ORDER: ProviderTab[] = [
  "deepseek",
  "doubao",
  "minimax",
  "glm",
  "qwen",
  "openai_compatible",
  "claude_compatible",
];

const VISION_PROVIDER_ORDER = ["qwen", "glm", "kimi", "doubao", "deepseek", "minimax", "openai_compatible"];

const TAB_CONFIG: Record<ProviderTab, ProviderConfig> = {
  deepseek: {
    title: "DeepSeek",
    body: "适合报告、训练计划和冰宝聊天的默认文本供应商。如果你的接口支持视觉模型，也可以额外填写视觉模型字段。",
    baseUrl: "https://api.deepseek.com/v1",
    note: "DeepSeek 入口仍然走 OpenAI 兼容协议。",
    modelLabel: "文本模型 ID",
    modelPlaceholder: "例如：deepseek-chat",
    supportsVision: true,
  },
  doubao: {
    title: "豆包（火山方舟）",
    body: "豆包走 OpenAI 兼容接口；模型请填写接入点 ID，通常以 ep- 开头。",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    note: "如果你有视觉接入点，也可以单独填在视觉模型字段里。",
    modelLabel: "接入点模型 ID",
    modelPlaceholder: "例如：ep-xxxxxxxx-xxxxx",
    supportsVision: true,
  },
  minimax: {
    title: "MiniMax",
    body: "MiniMax 可作为文本供应商接入；如果你当前只做文本分析，视觉模型字段可以留空。",
    baseUrl: "https://api.minimax.chat/v1",
    note: "MiniMax 配置完成后，可以和其他文本供应商一样参与报告、计划和聊天。",
    modelLabel: "文本模型 ID",
    modelPlaceholder: "例如：MiniMax-Text-01",
    supportsVision: true,
  },
  glm: {
    title: "GLM",
    body: "GLM 适合接入智谱开放平台。你可以把它作为文本模型，也可以在视觉区单独配置 GLM 的视觉模型。",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    note: "如果文本和视觉都用 GLM，建议分别在文本区和视觉区保存，方便独立切换。",
    modelLabel: "模型 ID",
    modelPlaceholder: "例如：glm-5",
    supportsVision: true,
  },
  qwen: {
    title: "Qwen",
    body: "Qwen 走 DashScope 的 OpenAI 兼容接口，适合做文本和视觉双链路配置。",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    note: "如果你希望完全不在群晖环境变量里放 key，可以在这里补文本配置，在视觉区补视觉配置。",
    modelLabel: "模型 ID",
    modelPlaceholder: "例如：qwen-max-latest",
    supportsVision: true,
  },
  openai_compatible: {
    title: "自定义 OpenAI 兼容",
    body: "用于接入任何兼容 OpenAI Chat Completions 协议的自定义服务，比如代理网关、自建兼容层或第三方聚合平台。",
    baseUrl: "https://api.openai.com/v1",
    note: "这个入口支持文本链路；若你的自定义接口也支持视觉模型，可补充视觉模型字段。",
    modelLabel: "文本模型 ID",
    modelPlaceholder: "例如：gpt-4o-mini 或你的自定义模型名",
    supportsVision: true,
  },
  claude_compatible: {
    title: "自定义 Claude 兼容",
    body: "用于接入兼容 Anthropic Messages 协议的服务。当前会接入报告、训练计划、记忆建议和冰宝聊天这些文本链路。",
    baseUrl: "https://api.anthropic.com/v1",
    note: "Claude 兼容入口当前只接文本链路，视频视觉分析仍建议单独配置视觉供应商。",
    modelLabel: "Claude 模型 ID",
    modelPlaceholder: "例如：claude-3-5-sonnet-20241022",
    supportsVision: false,
  },
};

function normalizeProvider(provider: ProviderPublic | undefined, fallbackConfig: ProviderConfig): ProviderFormState {
  return {
    api_key: provider?.api_key === "***" ? "" : provider?.api_key ?? "",
    model_id: provider?.model_id ?? "",
    vision_model: provider?.vision_model ?? "",
    base_url: provider?.base_url ?? fallbackConfig.baseUrl,
  };
}

function buildVisionFallbackConfig(provider: ProviderPublic | undefined): ProviderConfig {
  const providerName = provider?.provider ?? "vision";
  const defaults: Record<string, { title: string; baseUrl: string; placeholder: string }> = {
    qwen: {
      title: "Qwen 视觉",
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      placeholder: "例如：qwen3.6-plus",
    },
    glm: {
      title: "GLM 视觉",
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      placeholder: "例如：glm-4.5v",
    },
    kimi: {
      title: "Kimi 视觉",
      baseUrl: "https://api.moonshot.cn/v1",
      placeholder: "例如：kimi-k2.5",
    },
    doubao: {
      title: "豆包视觉",
      baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
      placeholder: "例如：doubao-seed-2-0-250615",
    },
  };

  const fallback = defaults[providerName] ?? {
    title: provider?.name ?? "视觉供应商",
    baseUrl: provider?.base_url ?? "https://dashscope.aliyuncs.com/compatible-mode/v1",
    placeholder: provider?.model_id ?? "请输入视觉模型 ID",
  };

  return {
    title: provider?.name ?? fallback.title,
    body: "这里专门配置视频抽帧后的视觉识别链路。上传视频后的动作阶段分析、帧级观察和结构化视觉结果，都会走这里的激活供应商。",
    baseUrl: provider?.base_url ?? fallback.baseUrl,
    note: "建议把视觉链路和文本链路分开配置，这样后续切换模型时更清晰，也不用把视觉 key 放到容器环境变量里。",
    modelLabel: "视觉主模型 ID",
    modelPlaceholder: fallback.placeholder,
    supportsVision: true,
  };
}

export default function ApiSettingsPage() {
  const { isParentMode, enterParentMode } = useAppMode();
  const [providers, setProviders] = useState<ProviderPublic[]>([]);
  const [activeTab, setActiveTab] = useState<ProviderTab>("deepseek");
  const [forms, setForms] = useState<Record<string, ProviderFormState>>({});
  const [expandedVisionId, setExpandedVisionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [testingKey, setTestingKey] = useState<string | null>(null);
  const [activatingKey, setActivatingKey] = useState<string | null>(null);

  useEffect(() => {
    if (!isParentMode) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchProviders();
        if (cancelled) {
          return;
        }

        setProviders(data);

        const nextForms: Record<string, ProviderFormState> = {};
        for (const tab of REPORT_TAB_ORDER) {
          const provider = data.find((item) => item.slot === "report" && item.provider === tab);
          nextForms[`report:${tab}`] = normalizeProvider(provider, TAB_CONFIG[tab]);
        }
        for (const provider of data.filter((item) => item.slot === "vision")) {
          nextForms[`vision:${provider.id}`] = normalizeProvider(provider, buildVisionFallbackConfig(provider));
        }
        setForms(nextForms);

        const activeVision = data.find((item) => item.slot === "vision" && item.is_active);
        setExpandedVisionId(activeVision?.id ?? data.find((item) => item.slot === "vision")?.id ?? null);
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

  const reportProvider = providers.find((item) => item.slot === "report" && item.provider === activeTab);
  const reportConfig = TAB_CONFIG[activeTab];
  const reportFormKey = `report:${activeTab}`;

  const visionProviders = useMemo(() => {
    const visionItems = providers.filter((item) => item.slot === "vision");
    return visionItems.sort((a, b) => {
      const orderA = VISION_PROVIDER_ORDER.indexOf(a.provider);
      const orderB = VISION_PROVIDER_ORDER.indexOf(b.provider);
      const normalizedA = orderA === -1 ? Number.MAX_SAFE_INTEGER : orderA;
      const normalizedB = orderB === -1 ? Number.MAX_SAFE_INTEGER : orderB;
      if (normalizedA !== normalizedB) {
        return normalizedA - normalizedB;
      }
      return a.created_at.localeCompare(b.created_at);
    });
  }, [providers]);

  const setFormField = (formKey: string, field: keyof ProviderFormState, value: string) => {
    setForms((current) => ({
      ...current,
      [formKey]: {
        ...(current[formKey] ?? { api_key: "", model_id: "", vision_model: "", base_url: "" }),
        [field]: value,
      },
    }));
  };

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2600);
  };

  const getProviderStatus = (provider: ProviderPublic) => {
    if (provider.is_active) {
      return { label: "当前激活", className: "bg-emerald-100 text-emerald-700" };
    }
    if (provider.api_key === "***") {
      return { label: "已配置", className: "bg-sky-100 text-sky-700" };
    }
    return { label: "未配置", className: "bg-slate-200 text-slate-600" };
  };

  const refreshProviders = (nextProviders: ProviderPublic[]) => {
    setProviders(nextProviders);
    setForms((current) => {
      const nextForms = { ...current };
      for (const tab of REPORT_TAB_ORDER) {
        const provider = nextProviders.find((item) => item.slot === "report" && item.provider === tab);
        nextForms[`report:${tab}`] = normalizeProvider(provider, TAB_CONFIG[tab]);
      }
      for (const provider of nextProviders.filter((item) => item.slot === "vision")) {
        nextForms[`vision:${provider.id}`] = normalizeProvider(provider, buildVisionFallbackConfig(provider));
      }
      return nextForms;
    });
  };

  const handleSave = async (provider: ProviderPublic, formKey: string, config: ProviderConfig) => {
    const form = forms[formKey] ?? normalizeProvider(provider, config);
    if (!form.api_key.trim() && provider.api_key !== "***") {
      setError("请先填写 API Key。");
      return;
    }
    if (!form.model_id.trim()) {
      setError("请先填写模型 ID。");
      return;
    }

    setSavingKey(formKey);
    setError(null);
    try {
      const updated = await updateProvider(provider.id, {
        api_key: form.api_key.trim() || undefined,
        model_id: form.model_id.trim(),
        vision_model: config.supportsVision ? form.vision_model.trim() || null : null,
        base_url: form.base_url.trim(),
      });
      const nextProviders = providers.map((item) => (item.id === updated.id ? updated : item));
      refreshProviders(nextProviders);
      showNotice(`${provider.name} 已保存。`);
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

  const handleTest = async (provider: ProviderPublic, formKey: string) => {
    setTestingKey(formKey);
    setError(null);
    try {
      const result = await testProvider(provider.id);
      showNotice(result.success ? `${provider.name} 连接成功。` : result.detail);
      if (!result.success) {
        setError(result.detail);
      }
    } catch (requestError) {
      if (axios.isAxiosError(requestError)) {
        setError(String(requestError.response?.data?.detail ?? "测试连接失败。"));
      } else {
        setError("测试连接失败。");
      }
    } finally {
      setTestingKey(null);
    }
  };

  const handleActivate = async (provider: ProviderPublic, formKey: string) => {
    setActivatingKey(formKey);
    setError(null);
    try {
      const updated = await activateProvider(provider.id);
      const nextProviders = providers.map((item) =>
        item.slot === updated.slot ? { ...item, is_active: item.id === updated.id } : item,
      );
      refreshProviders(nextProviders);
      if (provider.slot === "vision") {
        setExpandedVisionId(updated.id);
      }
      showNotice(`${provider.name} 已设为当前${provider.slot === "vision" ? "视觉" : "文本"}供应商。`);
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

  const renderProviderCard = (
    provider: ProviderPublic,
    slot: ProviderSlot,
    formKey: string,
    config: ProviderConfig,
    collapsed = false,
  ) => {
    const form = forms[formKey] ?? normalizeProvider(provider, config);
    const activeLabel = slot === "vision" ? "当前视觉供应商" : "当前文本供应商";
    const status = getProviderStatus(provider);
    const isVisionExpanded = slot !== "vision" || expandedVisionId === provider.id;

    return (
      <div key={provider.id} className="rounded-[30px] border border-slate-200 bg-slate-50 p-6">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 tablet:flex-row tablet:items-start tablet:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-2xl font-semibold text-slate-900">{provider.name}</h2>
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${status.className}`}>{status.label}</span>
                {provider.is_active ? (
                  <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">{activeLabel}</span>
                ) : null}
              </div>
              <p className="mt-3 text-sm leading-7 text-slate-500">{config.body}</p>
              {slot === "vision" && collapsed ? (
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span className="rounded-full bg-white px-3 py-1">模型: {form.model_id || "未填写"}</span>
                  <span className="rounded-full bg-white px-3 py-1">Base URL: {form.base_url || "未填写"}</span>
                </div>
              ) : (
                <p className="mt-2 text-sm leading-7 text-slate-500">{config.note}</p>
              )}
            </div>

            <div className="flex flex-wrap gap-3">
              {slot === "vision" ? (
                <button
                  type="button"
                  onClick={() => setExpandedVisionId((current) => (current === provider.id ? null : provider.id))}
                  className="app-pill min-h-[46px] px-5 text-sm font-semibold"
                >
                  {isVisionExpanded ? "收起配置" : "展开配置"}
                </button>
              ) : null}
              {!provider.is_active ? (
                <button
                  type="button"
                  onClick={() => void handleActivate(provider, formKey)}
                  disabled={activatingKey === formKey}
                  className="app-pill min-h-[46px] px-5 text-sm font-semibold"
                >
                  {activatingKey === formKey ? "切换中..." : "设为当前"}
                </button>
              ) : null}
            </div>
          </div>

          {slot === "vision" && collapsed && !isVisionExpanded ? null : (
            <>
              <p className="text-sm leading-7 text-slate-500">{config.note}</p>

              <div className="grid gap-4">
                <label className="space-y-2">
                  <span className="text-sm font-medium text-slate-700">API Key</span>
                  <input
                    value={form.api_key}
                    onChange={(event) => setFormField(formKey, "api_key", event.target.value)}
                    className="app-input"
                    placeholder="请输入 API Key"
                  />
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-medium text-slate-700">{config.modelLabel}</span>
                  <input
                    value={form.model_id}
                    onChange={(event) => setFormField(formKey, "model_id", event.target.value)}
                    className="app-input"
                    placeholder={config.modelPlaceholder}
                  />
                </label>

                {config.supportsVision ? (
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-slate-700">备用视觉模型（可选）</span>
                    <input
                      value={form.vision_model}
                      onChange={(event) => setFormField(formKey, "vision_model", event.target.value)}
                      className="app-input"
                      placeholder="可选：填写支持视觉的备选模型名"
                    />
                  </label>
                ) : (
                  <div className="rounded-[20px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm leading-7 text-amber-700">
                    这个入口当前只接入文本链路，不参与视频视觉分析。
                  </div>
                )}

                <label className="space-y-2">
                  <span className="text-sm font-medium text-slate-700">API 根地址</span>
                  <input
                    value={form.base_url}
                    onChange={(event) => setFormField(formKey, "base_url", event.target.value)}
                    className="app-input"
                  />
                </label>
              </div>

              <div className="mt-8 flex flex-col gap-3 tablet:flex-row">
                <button
                  type="button"
                  onClick={() => void handleSave(provider, formKey, config)}
                  disabled={savingKey === formKey}
                  className="min-h-[48px] rounded-full bg-blue-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {savingKey === formKey ? "保存中..." : "保存配置"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleTest(provider, formKey)}
                  disabled={testingKey === formKey}
                  className="app-pill min-h-[48px] px-5 text-sm font-semibold"
                >
                  {testingKey === formKey ? "测试中..." : "测试连接"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    );
  };

  if (!isParentMode) {
    return (
      <section className="app-card mx-auto max-w-3xl p-8 text-center tablet:p-10">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">API Settings</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">API 设置</h1>
        <p className="mt-4 text-base leading-8 text-slate-500">进入家长模式后，才可以配置文本模型和视觉模型供应商。</p>
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
          <h1 className="mt-2 text-3xl font-semibold text-slate-900 tablet:text-4xl">API 兼容配置</h1>
        </div>
        <Link to="/settings" className="app-pill text-sm font-semibold">
          返回家长设置
        </Link>
      </div>

      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}

      <section className="app-card p-6 tablet:p-8">
        <p className="max-w-3xl text-base leading-8 text-slate-500">
          这里分开管理文本链路和视觉链路。报告、训练计划、聊天走文本供应商；视频上传后的逐帧识别、动作阶段判断和视觉结构化输出走视觉供应商。
        </p>
      </section>

      <section className="app-card p-6 tablet:p-8">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Report Models</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">文本模型配置</h2>
          <p className="mt-3 text-sm leading-7 text-slate-500">这部分对应报告生成、训练计划、记忆建议和冰宝聊天等文本能力。</p>
        </div>

        <div className="mt-8 flex flex-wrap gap-3 rounded-[28px] bg-slate-100 p-2">
          {REPORT_TAB_ORDER.map((tab) => {
            const selected = tab === activeTab;
            const provider = providers.find((item) => item.slot === "report" && item.provider === tab);
            const status = provider ? getProviderStatus(provider) : null;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`min-h-[50px] rounded-[22px] px-5 py-3 text-sm font-semibold transition ${
                  selected ? "bg-white text-slate-900 shadow-[0_12px_24px_rgba(15,23,42,0.10)]" : "bg-transparent text-slate-500"
                }`}
              >
                {TAB_CONFIG[tab].title}
                {status ? ` · ${status.label}` : ""}
              </button>
            );
          })}
        </div>

        <div className="mt-8">
          {reportProvider ? renderProviderCard(reportProvider, "report", reportFormKey, reportConfig) : null}
        </div>
      </section>

      <section className="app-card p-6 tablet:p-8">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-400">Vision Models</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">视觉模型配置</h2>
          <p className="mt-3 text-sm leading-7 text-slate-500">
            视觉供应商现在默认折叠显示。你可以先看状态卡片，再按需展开配置。上传视频后，系统会使用当前激活的
            `vision` 供应商做抽帧识别和结构化视觉分析。
          </p>
        </div>

        <div className="mt-8 grid gap-6">
          {visionProviders.map((provider) =>
            renderProviderCard(provider, "vision", `vision:${provider.id}`, buildVisionFallbackConfig(provider), true),
          )}
        </div>
      </section>
    </div>
  );
}
