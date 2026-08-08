import axios from "axios";
import { useEffect, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import IslandIcon from "../../modern/IslandIcon";
import { IslandCard, IslandTitle } from "../../modern/IslandSurface";
import { fetchAdvancedRuntimeCapabilities } from "../api";
import { AdvancedRuntimeCapabilities } from "../contracts";

const STATUS_TEXT = {
  not_configured: ["尚未配置", "Shadow 需要独立运行目录，当前不会启动。"],
  disabled: ["已停用", "当前使用完整 legacy 分析，不执行 Shadow。"],
  ready: ["准备就绪", "当前仅提供无写入的安全边界，不会生成或修改家庭分析结果。"],
} as const;

export default function ShadowStatusCard() {
  const { isParentMode, parentPin, enterParentMode } = useAppMode();
  const [status, setStatus] = useState<AdvancedRuntimeCapabilities | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isParentMode || !parentPin) return;
    let active = true;
    setLoading(true);
    setError(null);
    void fetchAdvancedRuntimeCapabilities(parentPin)
      .then((next) => { if (active) setStatus(next); })
      .catch((requestError: unknown) => {
        if (!active) return;
        const detail = axios.isAxiosError(requestError) ? requestError.response?.data?.detail : null;
        setError(typeof detail === "string" ? detail : "暂时无法读取 Shadow 状态，请稍后重试。");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isParentMode, parentPin]);

  if (!isParentMode) return <IslandCard className="modern-me-panel modern-lock-panel" tone="sun"><IslandIcon name="lock"/><h2>Shadow 状态仅家长可见</h2><p>进入家长模式并验证 PIN 后，才能查看隔离运行状态。</p><button className="island-button island-button--primary" onClick={() => void enterParentMode()}>进入家长模式</button></IslandCard>;
  if (!parentPin) return <IslandCard className="modern-me-panel modern-lock-panel" tone="sun"><IslandIcon name="lock"/><h2>请重新验证家长 PIN</h2><p>浏览器没有保留 PIN。重新验证后才能向后端读取私有运行状态。</p><button className="island-button island-button--primary" onClick={() => void enterParentMode()}>验证 PIN</button></IslandCard>;
  if (loading) return <IslandCard className="modern-me-panel" aria-live="polite"><p>正在读取 Shadow 状态…</p></IslandCard>;
  if (error) return <IslandCard className="modern-me-panel" tone="sun"><div role="alert"><h2>状态暂不可用</h2><p>{error}</p></div></IslandCard>;
  if (!status) return <IslandCard className="modern-me-panel"><p>尚未读取 Shadow 状态。</p></IslandCard>;

  const [title, description] = STATUS_TEXT[status.shadow_status];
  return <IslandCard className="modern-me-panel" tone={status.shadow_status === "ready" ? "mint" : "sun"}><IslandTitle>Shadow 分析</IslandTitle><h2>{title}</h2><p>{description}</p><dl className="modern-runtime-status"><div><dt>普通页面权威来源</dt><dd>Legacy</dd></div><div><dt>执行方式</dt><dd>Bounded local queue</dd></div><div><dt>家庭数据写入</dt><dd>无</dd></div><div><dt>隔离运行目录</dt><dd>{status.isolated_runtime ? "已确认" : "未确认"}</dd></div><div><dt>Detector</dt><dd>{status.detector_configured ?? "yolo"} / {status.detector_active ?? "unavailable"}</dd></div><div><dt>Tracker</dt><dd>{status.tracker_configured ?? "bytetrack"} / {status.tracker_active ?? "unavailable"}</dd></div><div><dt>Model source</dt><dd>{status.model_source ?? "unknown"}</dd></div><div><dt>Dependencies</dt><dd>{status.dependency_ready ? "ready" : "unavailable"}</dd></div><div><dt>DS918+</dt><dd>{status.ds918_compatible === false ? "not compatible" : "compatible profile"}</dd></div></dl></IslandCard>;
}
