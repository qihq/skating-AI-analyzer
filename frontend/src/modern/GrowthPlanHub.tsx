import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { AnalysisListItem, createPlan, fetchAnalyses, fetchLatestPlanForSkater, fetchSkaters, Skater, TrainingPlanDetail } from "../api/client";
import IslandIcon from "./IslandIcon";
import { useAnalysisExperiences } from "../analysis-v2/useAnalysisExperiences";
import { presentAnalysisExperience } from "../analysis-v2/presenter";

function skaterLabel(skater: Skater) { return skater.display_name || skater.name; }

export default function GrowthPlanHub() {
  const navigate = useNavigate();
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [skaterId, setSkaterId] = useState("");
  const [analyses, setAnalyses] = useState<AnalysisListItem[]>([]);
  const [latestPlan, setLatestPlan] = useState<TrainingPlanDetail | null>(null);
  const [analysisId, setAnalysisId] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { experiences } = useAnalysisExperiences(analyses.map((item) => item.id));

  useEffect(() => {
    let active = true;
    void fetchSkaters().then((items) => {
      if (!active) return;
      setSkaters(items);
      setSkaterId(items.find((item) => item.is_default)?.id || items[0]?.id || "");
    }).catch(() => active && setError("练习档案加载失败，请稍后重试。"));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!skaterId) { setLoading(false); return; }
    let active = true;
    setLoading(true); setError(null);
    void Promise.all([
      fetchAnalyses({ skater_id: skaterId, limit: 50 }),
      fetchLatestPlanForSkater(skaterId).catch((reason) => axios.isAxiosError(reason) && reason.response?.status === 404 ? null : Promise.reject(reason)),
    ]).then(([items, plan]) => {
      if (!active) return;
      const completed = items.filter((item) => item.status === "completed");
      setAnalyses(completed); setAnalysisId(completed[0]?.id || ""); setLatestPlan(plan);
    }).catch(() => active && setError("训练计划资料加载失败，请稍后重试。"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [skaterId]);

  const selectedSkater = useMemo(() => skaters.find((item) => item.id === skaterId), [skaterId, skaters]);
  const handleCreate = async () => {
    if (!analysisId || creating) return;
    setCreating(true); setError(null);
    try { const plan = await createPlan(analysisId); navigate(`/plan/${plan.id}`); }
    catch (reason) { setError(axios.isAxiosError(reason) ? String(reason.response?.data?.detail || "训练计划生成失败，请稍后重试。") : "训练计划生成失败，请稍后重试。"); }
    finally { setCreating(false); }
  };

  return (
    <div className="island-workspace space-y-5">
      <section className="island-card island-hub-hero">
        <div><span className="island-hub-hero__icon"><IslandIcon name="growth" /></span><p className="island-kicker">Nook Training Plan</p><h1>训练计划中心</h1><p>从一次已完成的复盘生成七天计划，之后在这里继续训练与打卡。</p></div>
        <label className="island-field"><span>练习档案</span><select value={skaterId} onChange={(event) => setSkaterId(event.target.value)}>{skaters.map((item) => <option key={item.id} value={item.id}>{skaterLabel(item)}</option>)}</select></label>
      </section>
      {error ? <div className="island-notice island-notice--error" role="alert">{error}</div> : null}
      {loading ? <div className="island-route-loading">正在整理训练计划…</div> : latestPlan ? (
        <section className="island-card island-hub-panel"><div><p className="island-kicker">最近计划</p><h2>{latestPlan.plan_json.title}</h2><p>训练聚焦：{latestPlan.plan_json.focus_skill}</p></div><Link className="island-button island-button--primary" to={`/plan/${latestPlan.id}`}>继续训练 <IslandIcon name="arrow" className="island-button__icon" /></Link></section>
      ) : <section className="island-card island-empty-state"><IslandIcon name="growth" /><h2>还没有训练计划</h2><p>{selectedSkater ? `${skaterLabel(selectedSkater)}完成一次视频复盘后，就可以从诊断结果生成七天计划。` : "先建立练习档案并完成一次视频复盘。"}</p></section>}
      <section className="island-card island-hub-panel"><div><p className="island-kicker">新计划</p><h2>选择一次已完成的复盘</h2><p>计划会根据报告重点生成；已有计划不会因为打开此页面而失效。</p></div><div className="island-hub-actions"><select className="island-select" aria-label="用于生成计划的复盘" value={analysisId} onChange={(event) => setAnalysisId(event.target.value)}><option value="">暂无可用复盘</option>{analyses.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleDateString("zh-CN")} · {experiences[item.id] ? presentAnalysisExperience(experiences[item.id]!).selectedEvent?.label : "复盘摘要加载中"}</option>)}</select><button type="button" className="island-button island-button--primary" disabled={!analysisId || creating} onClick={() => void handleCreate()}>{creating ? <><span className="island-leaf-spinner" />生成中…</> : "生成训练计划"}</button></div></section>
    </div>
  );
}
