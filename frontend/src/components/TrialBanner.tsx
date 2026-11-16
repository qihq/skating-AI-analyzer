import { useEffect, useState } from "react";
export default function TrialBanner() {
  const [trial, setTrial] = useState<{profile: string; version: string; limitation: string} | null>(null);
  useEffect(() => { fetch("/api/trial").then(r => r.ok ? r.json() : null).then(setTrial).catch(() => {}); }, []);
  if (!trial || trial.profile === "off") return null;
  return <aside role="status" style={{position: "relative", zIndex: 100, padding: "10px 16px", background: "#fff4d6", color: "#563900", fontSize: 13, overflowWrap: "anywhere"}}>
    <strong>V2 NAS {trial.profile} · {trial.version}</strong><br />{trial.limitation} NAS 实机尚未验证。仅局域网试用，请勿输入供应商密钥。
  </aside>;
}
