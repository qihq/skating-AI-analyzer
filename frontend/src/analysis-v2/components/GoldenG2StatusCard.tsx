import { useEffect, useState } from "react";

import { IslandCard, IslandTitle } from "../../modern/IslandSurface";
import { fetchGoldenG2Status } from "../api";
import type { GoldenG2Status } from "../golden-contracts";

export default function GoldenG2StatusCard({ parentPin }: { parentPin: string }) {
  const [status, setStatus] = useState<GoldenG2Status | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchGoldenG2Status(parentPin)
      .then((value) => { if (active) setStatus(value); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [parentPin]);

  if (failed) return <IslandCard className="modern-me-panel" tone="sun"><p role="alert">G2 状态暂时不可用；没有修改任何 Golden 数据。</p></IslandCard>;
  if (!status) return <IslandCard className="modern-me-panel" aria-live="polite"><p>正在读取 G2 数据集状态...</p></IslandCard>;

  const [minimum, maximum] = status.required_event_range;
  const collecting = status.status === "collecting" || status.status === "ready_to_freeze";
  return <IslandCard className="modern-me-panel" tone={collecting ? "sun" : "mint"}>
    <IslandTitle>G2 冻结与 Legacy baseline</IslandTitle>
    <dl className="modern-runtime-status">
      <div><dt>事件</dt><dd>{status.event_count}/{minimum}-{maximum}</dd></div>
      <div><dt>录制场次</dt><dd>{status.distribution.recording_session_count}/5+</dd></div>
      <div><dt>状态</dt><dd>{status.status}</dd></div>
    </dl>
    {collecting ? <p>达到 60-80 条、分组分区和 profile 覆盖要求前不能冻结；当前不会运行正式 baseline。</p> : <p>冻结版本已绑定 fingerprint；任何成员变化都必须创建新的明确 revision。</p>}
    {status.legacy_pipeline_fingerprint ? <p>Legacy fingerprint: {status.legacy_pipeline_fingerprint}</p> : null}
    <p>此状态只表示数据冻结或 baseline 记录，不代表发布通过。</p>
  </IslandCard>;
}
