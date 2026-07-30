import axios from "axios";
import { useEffect, useState } from "react";

import { useAppMode } from "../../components/AppModeContext";
import IslandIcon from "../../modern/IslandIcon";
import { IslandButton, IslandCard, IslandPageHeader, IslandTitle } from "../../modern/IslandSurface";
import { fetchGoldenCatalog, fetchGoldenSanitizedExport, fetchGoldenSchema } from "../api";
import { GoldenCatalogSummary, GoldenSanitizedExport, GoldenSchemaInfo } from "../golden-contracts";
import GoldenAnnotationWorkspace from "./GoldenAnnotationWorkspace";
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

  if (!isParentMode || !parentPin) return <IslandCard className="modern-me-panel modern-lock-panel" tone="sun"><IslandIcon name="lock"/><h2>Golden 目录仅家长可见</h2><p>Private source video and Golden labels cannot be read in child mode.</p><IslandButton onClick={() => void enterParentMode()}>Verify parent PIN</IslandButton></IslandCard>;
  if (state === "loading") return <IslandCard className="modern-me-panel" aria-live="polite"><p>Loading the private Golden workspace...</p></IslandCard>;
  if (state === "error") return <IslandCard className="modern-me-panel" tone="sun"><div role="alert"><h2>Catalog unavailable</h2><p>{error}</p><p>Historic debug Golden records are never used as a fallback.</p></div></IslandCard>;
  if (!catalog || !schema || !exportData) return <IslandCard className="modern-me-panel"><p>No Golden status is available.</p></IslandCard>;
  const heading = catalog.status === "empty" ? "等待新的评测事件" : catalog.status === "schema-incompatible" ? "目录版本需要处理" : catalog.status === "invalid-source" ? "来源记录无效" : catalog.duplicate_sources.length ? "发现需要复核的相近素材" : "目录已准备好";
  return <div className="modern-space" data-testid="golden-catalog-shell"><IslandPageHeader title="Golden private catalog" description="New videos only. Historic debug media remains outside this workflow."/><GoldenPilotDashboard/><IslandCard className="modern-me-panel" tone={catalog.status === "ready" ? "mint" : "sun"}><IslandTitle>Catalog status</IslandTitle><h2>{heading}</h2>{catalog.status === "empty" ? <p>尚未导入视频、人工标注或运行 G1。</p> : null}{catalog.status === "schema-incompatible" ? <p>不会静默丢弃字段或读取旧 debug Golden。</p> : null}<dl className="modern-runtime-status"><div><dt>Revision</dt><dd>{catalog.revision}</dd></div><div><dt>Events</dt><dd>{catalog.event_count}</dd></div><div><dt>Sources</dt><dd>{catalog.source_count}</dd></div><div><dt>G1</dt><dd>{exportData.gate_template.status}</dd></div></dl></IslandCard><GoldenAnnotationWorkspace/><IslandCard className="modern-me-panel"><IslandTitle>Privacy-safe export</IslandTitle><p>Only aggregate counts can leave this workspace. No paths, filenames, frames, people, or labels are exposed.</p><IslandButton variant="secondary" onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen}>{detailsOpen ? "收起家长诊断" : "查看家长诊断"}</IslandButton>{detailsOpen ? <details open><summary>Parent diagnostics</summary><p>Schema: {schema.schema_version}; migration: {schema.migration_policy}; legacy debug: {schema.historical_debug_pool}.</p><p>Duplicate flags: {catalog.duplicate_sources.join(", ") || "none"}.</p></details> : null}</IslandCard></div>;
}
