import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { fetchAnalysisExperienceV2 } from "../analysis-v2/api";
import { AnalysisExperienceV2 } from "../analysis-v2/contracts";
import { actionEventLabel } from "../analysis-v2/profilePresentation";
import { AnalysisDetail, fetchAnalysis, fetchGrowthSummary, fetchSkaters, GrowthSummary, Skater } from "../api/client";
import { useAppMode } from "../components/AppModeContext";
import IslandIcon from "./IslandIcon";
import { IslandCard, IslandPageHeader, IslandTitle } from "./IslandSurface";

function message(error: unknown) {
  if (axios.isAxiosError(error) && error.response?.status === 404) {
    return "成长摘要暂未准备好，你仍然可以开始复盘或打开其他岛屿空间。";
  }
  return "岛上信号有点弱，部分成长信息暂时没有更新，请稍后再试。";
}

function claimValue(experience: AnalysisExperienceV2 | null, type: string): string | null {
  const claim = experience?.claims.find((item) => item.claimType === type);
  return claim?.status === "unobservable" ? null : claim?.value == null ? null : String(claim.value);
}

export default function ModernTodayIsland() {
  const { isParentMode } = useAppMode();
  const [skaters, setSkaters] = useState<Skater[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [summary, setSummary] = useState<GrowthSummary | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [experience, setExperience] = useState<AnalysisExperienceV2 | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSkaters().then((items) => {
      if (cancelled) return;
      setSkaters(items);
      setSelectedId(items.find((item) => item.is_default)?.id ?? items[0]?.id ?? "");
    }).catch((reason) => !cancelled && setError(message(reason))).finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSummary(null);
    setAnalysis(null);
    setExperience(null);
    const loadSummary = async () => {
      try {
        const nextSummary = await fetchGrowthSummary(selectedId);
        if (cancelled) return;
        setSummary(nextSummary);
        if (nextSummary.latest_analysis_id) {
          try {
            const nextExperience = await fetchAnalysisExperienceV2(nextSummary.latest_analysis_id);
            if (!cancelled) setExperience(nextExperience);
          } catch {
            const nextAnalysis = await fetchAnalysis(nextSummary.latest_analysis_id);
            if (!cancelled) setAnalysis(nextAnalysis);
          }
        }
      } catch (reason) {
        if (!cancelled) setError(message(reason));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void loadSummary();
    return () => { cancelled = true; };
  }, [selectedId]);

  const selected = useMemo(() => skaters.find((item) => item.id === selectedId), [selectedId, skaters]);
  const nextAction = claimValue(experience, "next_action") ?? analysis?.report?.improvements?.[0]?.action ?? analysis?.report?.training_focus ?? summary?.current_focus?.label;
  const latestSummary = claimValue(experience, "report_summary") ?? analysis?.report?.summary;
  const latestEvent = experience?.events[0];
  const latestProfile = latestEvent ? actionEventLabel(latestEvent) : analysis?.action_type ?? summary?.current_focus?.label;

  return (
    <div className="today-island">
      <IslandPageHeader
        title={`你好，${selected?.display_name || selected?.name || "小滑手"}`}
        description={isParentMode ? "今天的训练、最近进步和下一步都在这座小岛上。" : "看看今天最值得完成的一件事吧。"}
        action={skaters.length > 1 ? (
          <select aria-label="当前练习档案" className="island-select" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
            {skaters.map((skater) => <option key={skater.id} value={skater.id}>{skater.display_name || skater.name}</option>)}
          </select>
        ) : undefined}
      />

      {error ? <div role="alert" className="island-notice island-notice--error">{error}</div> : null}
      {loading ? <div className="island-skeleton" aria-label="正在读取今日岛屿"><span /><span /><span /></div> : null}

      {!loading ? (
        <div className="today-island__layout">
          <IslandCard className="today-island__hero" tone="sky">
            <div className="today-island__snow" aria-hidden="true">❄</div>
            <div className="today-island__hero-copy">
              <IslandTitle as="h2">今天先做这件事</IslandTitle>
              <h2>{nextAction || "上传一段训练视频，开始第一次复盘"}</h2>
              <p>{latestSummary || "一次只看一个重点，让每次训练都留下清楚的成长线索。"}</p>
              <Link className="island-cta" to="/review"><IslandIcon name="review" />开始复盘</Link>
            </div>
            <div className="today-island__rink" aria-hidden="true"><span>⛸</span><i /><b /></div>
          </IslandCard>

          <div className="today-island__stats">
            <IslandCard tone="sun"><strong>{summary?.current_month_analysis_count ?? 0}</strong><span>本月复盘</span></IslandCard>
            <IslandCard tone="mint"><strong>{summary?.milestone_count ?? 0}</strong><span>成长里程碑</span></IslandCard>
            <IslandCard><strong>{selected?.current_streak ?? 0}</strong><span>连续训练</span></IslandCard>
          </div>

          <IslandCard className="today-island__map">
            <div className="today-island__map-head"><div><IslandTitle>岛屿地图</IslandTitle><p>从一个清楚的入口到达每片区域</p></div></div>
            <div className="today-island__places">
              <Link to="/review" className="island-place island-place--rink"><span>🎥</span><strong>冰场小屋</strong><small>上传与复盘</small></Link>
              <Link to="/growth" className="island-place island-place--growth"><span>🌲</span><strong>成长群岛</strong><small>趋势与故事</small></Link>
              <Link to="/me" className="island-place island-place--service"><span>🏡</span><strong>居民服务处</strong><small>家庭与设置</small></Link>
              {summary?.latest_analysis_id ? <Link to={`/analysis/${summary.latest_analysis_id}`} className="island-place island-place--report"><span>📋</span><strong>最近报告</strong><small>继续上次复盘</small></Link> : null}
            </div>
          </IslandCard>

          <IslandCard className="today-island__latest">
            <IslandTitle>最近的进步</IslandTitle>
            <h3>{latestProfile || "等待第一次记录"}</h3>
            <p>{latestSummary || "完成复盘后，岛上会为你保存训练结论和成长里程碑。"}</p>
            <div className="today-island__latest-actions">
              {summary?.latest_analysis_id ? <Link to={`/analysis/${summary.latest_analysis_id}`}>查看分析 <IslandIcon name="arrow" /></Link> : null}
              <Link to="/growth">打开成长群岛 <IslandIcon name="arrow" /></Link>
            </div>
          </IslandCard>
        </div>
      ) : null}
    </div>
  );
}
