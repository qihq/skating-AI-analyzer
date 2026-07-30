import axios from "axios";
import { useEffect, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import IslandIcon from "../../modern/IslandIcon";
import { IslandButton, IslandCard, IslandPageHeader, IslandTitle } from "../../modern/IslandSurface";
import { fetchGoldenCatalog, fetchGoldenSanitizedExport, fetchGoldenSchema } from "../api";
import { GoldenCatalogSummary, GoldenSanitizedExport, GoldenSchemaInfo } from "../golden-contracts";

type LoadState = "loading" | "ready" | "error";

function requestError(error: unknown) {
  const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "暂时无法读取私有 Golden 目录，请稍后重试。";
}

export default function GoldenCatalogShell() {
  const { isParentMode, parentPin, enterParentMode } = useAppMode();
  const [state, setState] = useState<LoadState>("loading");
  const [catalog, setCatalog] = useState<GoldenCatalogSummary | null>(null);
  const [schema, setSchema] = useState<GoldenSchemaInfo | null>(null);
  const [exportData, setExportData] = useState<GoldenSanitizedExport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
    if (!isParentMode || !parentPin) return;
    let active = true;
    setState("loading");
    setError(null);
    Promise.all([fetchGoldenCatalog(parentPin), fetchGoldenSchema(parentPin), fetchGoldenSanitizedExport(parentPin)])
      .then(([nextCatalog, nextSchema, nextExport]) => {
        if (!active) return;
        setCatalog(nextCatalog); setSchema(nextSchema); setExportData(nextExport); setState("ready");
      })
      .catch((reason: unknown) => { if (active) { setError(requestError(reason)); setState("error"); } });
    return () => { active = false; };
  }, [isParentMode, parentPin]);

  if (!isParentMode || !parentPin) return <IslandCard className="modern-me-panel modern-lock-panel" tone="sun"><IslandIcon name="lock"/><h2>Golden 目录仅家长可见</h2><p>这里保存的是未来 V2 评测的私有目录；进入家长模式并验证 PIN 后才会读取它。</p><IslandButton onClick={() => void enterParentMode()}>验证家长 PIN</IslandButton></IslandCard>;
  if (state === "loading") return <IslandCard className="modern-me-panel" aria-live="polite"><p>正在读取 Golden V2 私有目录…</p></IslandCard>;
  if (state === "error") return <IslandCard className="modern-me-panel" tone="sun"><div role="alert"><h2>目录暂不可用</h2><p>{error}</p><p>不会显示或回退到历史 debug Golden 数据。</p></div></IslandCard>;
  if (!catalog || !schema || !exportData) return <IslandCard className="modern-me-panel"><p>Golden 目录暂无可显示状态。</p></IslandCard>;

  const issue = catalog.duplicate_sources.length ? "duplicate" : catalog.status;
  const title = issue === "empty" ? "等待新的评测事件" : issue === "duplicate" ? "发现需要复核的相近素材" : issue === "schema-incompatible" ? "目录版本需要处理" : issue === "invalid-source" ? "来源记录无效" : "目录已准备好";
  const description = issue === "empty" ? "当前是私有空 manifest。尚未导入视频、人工标注或运行 G1。" : issue === "schema-incompatible" ? "目录版本与当前 V2 合同不兼容，不会静默丢弃字段或读取旧 debug Golden。" : issue === "invalid-source" ? "来源记录未通过 V2 校验，内容保持私有且不会进入评测。" : "仅显示汇总，不展示视频、路径、人物或原始标签。";
  return <div className="modern-space" data-testid="golden-catalog-shell"><IslandPageHeader title="Golden 私有目录" description="用于未来 V2 的新视频评测；历史 debug 样本保持原样，不会迁入这里。"/><IslandCard className="modern-me-panel" tone={issue === "ready" ? "mint" : "sun"}><IslandTitle>目录状态</IslandTitle><h2>{title}</h2><p>{description}</p><dl className="modern-runtime-status"><div><dt>数据集修订</dt><dd>{catalog.revision}</dd></div><div><dt>新事件</dt><dd>{catalog.event_count}</dd></div><div><dt>来源素材</dt><dd>{catalog.source_count}</dd></div><div><dt>G1</dt><dd>{exportData.gate_template.status}</dd></div></dl></IslandCard><IslandCard className="modern-me-panel"><IslandTitle>私有导出</IslandTitle><h2>仅可分享脱敏汇总</h2><p>导出模板只含版本、总数、分层和 Gate 状态；不包含路径、文件名、帧、人物或标签。</p><IslandButton variant="secondary" onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen}>{detailsOpen ? "收起家长诊断" : "查看家长诊断"}</IslandButton>{detailsOpen ? <details open><summary>精确状态（仅家长）</summary><p>Schema: {schema.schema_version}; migration: {schema.migration_policy}; legacy debug pool: {schema.historical_debug_pool}.</p><p>Duplicate flags: {catalog.duplicate_sources.join(", ") || "none"}.</p></details> : null}</IslandCard></div>;
}
