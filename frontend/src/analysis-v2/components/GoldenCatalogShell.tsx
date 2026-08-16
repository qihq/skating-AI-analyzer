import axios from "axios";
import { useEffect, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import IslandIcon from "../../modern/IslandIcon";
import { IslandButton, IslandCard, IslandPageHeader, IslandTitle } from "../../modern/IslandSurface";
import { fetchGoldenCatalog, fetchGoldenSanitizedExport, fetchGoldenSchema } from "../api";
import { GoldenCatalogSummary, GoldenSanitizedExport, GoldenSchemaInfo } from "../golden-contracts";
import GoldenAnnotationWorkspace from "./GoldenAnnotationWorkspace";
import GoldenG2StatusCard from "./GoldenG2StatusCard";
import GoldenPilotDashboard from "./GoldenPilotDashboard";

type LoadState = "loading" | "ready" | "error";

function requestError(error: unknown) {
  const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "The private Golden catalog is temporarily unavailable. Please retry.";
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
    Promise.all([fetchGoldenCatalog(parentPin), fetchGoldenSchema(parentPin), fetchGoldenSanitizedExport(parentPin)])
      .then(([nextCatalog, nextSchema, nextExport]) => { if (active) { setCatalog(nextCatalog); setSchema(nextSchema); setExportData(nextExport); setState("ready"); } })
      .catch((reason: unknown) => { if (active) { setError(requestError(reason)); setState("error"); } });
    return () => { active = false; };
  }, [isParentMode, parentPin]);

  if (!isParentMode || !parentPin) return <IslandCard className="modern-me-panel modern-lock-panel" tone="sun"><IslandIcon name="lock"/><h2>Golden 目录仅家长可见</h2><p>孩子模式不能读取私有视频和 Golden 标签。</p><IslandButton onClick={() => void enterParentMode()}>验证家长 PIN</IslandButton></IslandCard>;
  if (state === "loading") return <IslandCard className="modern-me-panel" aria-live="polite"><p>正在打开私有 Golden 工作台...</p></IslandCard>;
  if (state === "error") return <IslandCard className="modern-me-panel" tone="sun"><div role="alert"><h2>Golden 目录暂时不可用</h2><p>{error}</p><p>系统不会拿历史 debug 数据代替当前 Golden。</p></div></IslandCard>;
  if (!catalog || !schema || !exportData) return <IslandCard className="modern-me-panel"><p>No Golden status is available.</p></IslandCard>;
  const heading = catalog.status === "empty" ? "等待新的评测事件" : catalog.status === "schema-incompatible" ? "目录版本需要处理" : catalog.status === "invalid-source" ? "来源记录无效" : catalog.duplicate_sources.length ? "发现需要复核的相近素材" : "目录已准备好";
  return <div className="modern-space" data-testid="golden-catalog-shell"><IslandPageHeader title="Golden 人工标注" description="从下方“上传以后做什么？”开始；可以随时切回以前的视频继续编辑。"/><GoldenAnnotationWorkspace gateTemplate={exportData.gate_template}/><GoldenPilotDashboard/><GoldenG2StatusCard parentPin={parentPin}/><IslandCard className="modern-me-panel" tone={catalog.status === "ready" ? "mint" : "sun"}><IslandTitle>目录状态</IslandTitle><h2>{heading}</h2>{catalog.status === "empty" ? <p>尚未导入视频、人工标注或运行 G1。</p> : null}{catalog.status === "schema-incompatible" ? <p>不会静默丢弃字段或读取旧 debug Golden。</p> : null}<dl className="modern-runtime-status"><div><dt>Revision</dt><dd>{catalog.revision}</dd></div><div><dt>动作事件</dt><dd>{catalog.event_count}</dd></div><div><dt>视频</dt><dd>{catalog.source_count}</dd></div><div><dt>G1</dt><dd>{exportData.gate_template.status}</dd></div></dl></IslandCard><IslandCard className="modern-me-panel"><IslandTitle>隐私安全导出</IslandTitle><p>只有汇总数量可以离开此工作台；路径、文件名、帧、人物和标签都不会导出。</p><IslandButton variant="secondary" onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen}>{detailsOpen ? "收起家长诊断" : "查看家长诊断"}</IslandButton>{detailsOpen ? <details open><summary>家长诊断</summary><p>Schema: {schema.schema_version}; migration: {schema.migration_policy}; legacy debug: {schema.historical_debug_pool}.</p><p>重复素材提示：{catalog.duplicate_sources.join(", ") || "无"}。</p></details> : null}</IslandCard></div>;
}

