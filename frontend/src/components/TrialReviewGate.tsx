import TrialTrainingSessions from "./TrialTrainingSessions";
import { ReactNode, createContext, useEffect, useState } from "react";
export const LocalTrialContext = createContext(false);
export default function TrialReviewGate({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<string | null>(null);
  useEffect(() => { fetch("/api/trial").then(r => r.ok ? r.json() : {profile: "unavailable"}).then(t => setProfile(t.profile)).catch(() => setProfile("unavailable")); }, []);
  if (profile === null) return <p role="status">正在确认试用功能…</p>;
  if (profile === "web-preview" || profile === "unavailable") return <section style={{padding: 24}}><h2>本版暂不支持视频分析</h2><p>网页试用版可测试首页、档案、训练课次和数据保存。上传、重试、报告生成和新诊断均未开放，不会创建分析任务。</p>{profile === "web-preview" && <TrialTrainingSessions />}</section>;
  return <LocalTrialContext.Provider value={profile === "legacy-analysis-preview"}>{children}</LocalTrialContext.Provider>;
}
