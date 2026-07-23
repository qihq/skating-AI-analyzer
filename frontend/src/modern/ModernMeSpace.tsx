import { lazy, ReactNode, Suspense } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAppMode } from "../components/AppModeContext";
import IslandIcon from "./IslandIcon";
import { IslandCard, IslandPageHeader, IslandTitle } from "./IslandSurface";
import { IslandPeriod, IslandThemePreference, useIslandTheme } from "./IslandThemeContext";
import SectionNav from "./SectionNav";

const ApiSettingsPage = lazy(() => import("../pages/ApiSettingsPage"));
const DebugPage = lazy(() => import("../pages/DebugPage"));
const SettingsPage = lazy(() => import("../pages/SettingsPage"));

export type MeView = "overview" | "family" | "appearance" | "advanced" | "about";
type AdvancedTool = "providers" | "debug" | "golden";

const ITEMS = [
  { id: "overview", label: "总览", to: "/me" },
  { id: "family", label: "家庭与模式", to: "/me?view=family" },
  { id: "appearance", label: "外观", to: "/me?view=appearance" },
  { id: "advanced", label: "高级工具", to: "/me?view=advanced" },
  { id: "about", label: "关于", to: "/me?view=about" },
] as const;

const THEME_OPTIONS: Array<{ id: IslandThemePreference; label: string; emoji: string }> = [
  { id: "auto", label: "跟随时间", emoji: "🕰️" }, { id: "morning", label: "晨间", emoji: "🌅" },
  { id: "day", label: "白天", emoji: "☀️" }, { id: "sunset", label: "傍晚", emoji: "🌇" }, { id: "night", label: "夜间", emoji: "🌙" },
];

function MeFrame({ view, children }: { view: MeView; children: ReactNode }) {
  return <div className="modern-space"><IslandPageHeader title="居民服务处" description="家庭成员、界面模式、岛屿外观和高级工具都集中在这里。"/><SectionNav label="居民服务处分区" items={[...ITEMS]} activeId={view}/>{children}</div>;
}

function AppearancePanel() {
  const { period, preference, setPreference } = useIslandTheme();
  return <IslandCard className="modern-me-panel"><IslandTitle>岛屿时段</IslandTitle><h2>现在是{({morning:"晨间",day:"白天",sunset:"傍晚",night:"夜间"} as Record<IslandPeriod,string>)[period]}主题</h2><p>自动主题只改变天空、背景与氛围色，分数和警告颜色始终保持一致。</p><div className="island-theme-grid">{THEME_OPTIONS.map((item)=><button key={item.id} type="button" className={preference===item.id?"is-active":""} onClick={()=>setPreference(item.id)}><span>{item.emoji}</span><strong>{item.label}</strong></button>)}</div></IslandCard>;
}

function AboutPanel() {
  return <div className="modern-me-grid"><IslandCard className="modern-me-panel"><IslandTitle>关于 IceBuddy</IslandTitle><h2>为家庭训练准备的冰上成长岛</h2><p>现代界面以清楚的成长主线连接复盘、报告、训练计划和长期故事。经典界面仍可随时切换。</p></IslandCard><IslandCard className="modern-me-panel" tone="mint"><IslandTitle>开源许可</IslandTitle><h2>Animal Island UI</h2><p>本界面的自然色、圆润卡片和交互语言参考并适配自 guokaigdg/animal-island-ui。</p><a className="island-text-link" href="https://github.com/guokaigdg/animal-island-ui" target="_blank" rel="noreferrer">查看原仓库 <IslandIcon name="arrow"/></a><p className="modern-license">Creative Commons Attribution-NonCommercial 4.0 International · 仅用于个人非商业用途，并保留原作者署名。</p></IslandCard></div>;
}

function AdvancedOverview() {
  const { isParentMode, enterParentMode } = useAppMode();
  if (!isParentMode) return <IslandCard className="modern-me-panel modern-lock-panel" tone="sun"><IslandIcon name="lock"/><h2>高级工具需要家长模式</h2><p>API 配置、调试和 Golden 标注会影响分析结果，需要家长确认后使用。</p><button className="island-button island-button--primary" onClick={()=>void enterParentMode()}>进入家长模式</button></IslandCard>;
  return <div className="modern-tool-grid"><Link to="/me/advanced?tool=providers"><span>🔌</span><strong>模型与 API</strong><small>供应商和连接配置</small></Link><Link to="/me/advanced?tool=debug"><span>🧭</span><strong>诊断调试</strong><small>管线、日志和运行状态</small></Link><Link to="/me/advanced?tool=golden"><span>🏷️</span><strong>Golden 标注</strong><small>高精度目标与关键帧</small></Link></div>;
}

export default function ModernMeSpace() {
  const [params] = useSearchParams();
  const requested = params.get("view") as MeView | null;
  const view = ITEMS.some((item)=>item.id===requested)?requested!:"overview";
  const content: Record<MeView,ReactNode> = {overview:<div className="modern-me-grid"><IslandCard className="modern-me-panel" tone="mint"><IslandTitle>家庭岛民</IslandTitle><h2>儿童与家长共享同一座岛</h2><p>切换模式只调整内容密度、措辞和高级权限，不会改变页面结构或丢失当前任务。</p><Link className="island-text-link" to="/me?view=family">管理家庭与模式 <IslandIcon name="arrow"/></Link></IslandCard><IslandCard className="modern-me-panel" tone="sky"><IslandTitle>岛屿外观</IslandTitle><h2>让天空跟着时间变化</h2><p>晨间、白天、傍晚与夜间都拥有独立氛围，也可以手动固定。</p><Link className="island-text-link" to="/me?view=appearance">调整外观 <IslandIcon name="arrow"/></Link></IslandCard><IslandCard className="modern-me-panel"><IslandTitle>高级工具</IslandTitle><h2>专业能力集中管理</h2><p>调试、Golden 标注与 API 配置不再散落在业务页面。</p><Link className="island-text-link" to="/me?view=advanced">打开高级工具 <IslandIcon name="arrow"/></Link></IslandCard></div>,family:<div className="modern-legacy-surface"><SettingsPage/></div>,appearance:<AppearancePanel/>,advanced:<AdvancedOverview/>,about:<AboutPanel/>};
  return <MeFrame view={view}><Suspense fallback={<div className="island-route-loading">正在打开居民服务处…</div>}>{content[view]}</Suspense></MeFrame>;
}

export function ModernAdvancedTool({ initialTool }: { initialTool?: AdvancedTool } = {}) {
  const [params] = useSearchParams();
  const tool=(params.get("tool") as AdvancedTool|null)??initialTool??"providers";
  const content:Record<AdvancedTool,ReactNode>={providers:<ApiSettingsPage/>,debug:<DebugPage/>,golden:<DebugPage workspace="golden"/>};
  return <MeFrame view="advanced"><div className="modern-advanced-tabs"><Link className={tool==="providers"?"is-active":""} to="/me/advanced?tool=providers">模型与 API</Link><Link className={tool==="debug"?"is-active":""} to="/me/advanced?tool=debug">诊断调试</Link><Link className={tool==="golden"?"is-active":""} to="/me/advanced?tool=golden">Golden 标注</Link></div><div className="modern-legacy-surface"><Suspense fallback={<div className="island-route-loading">正在加载高级工具…</div>}>{content[tool]??content.providers}</Suspense></div></MeFrame>;
}
