import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { AnalysisDetail, fetchAnalysis, fetchAnalysisPose, PoseResponse } from "../api/client";
import AnalysisFollowUpPanel from "../components/AnalysisFollowUpPanel";
import AnalysisDebugLogPanel, { TargetPoseDebugPanel } from "../components/AnalysisDebugLogPanel";
import BiomechanicsPanel from "../components/BiomechanicsPanel";
import KeyframeEvidencePanel, { type KeyframeSyncPatch } from "../components/KeyframeEvidencePanel";
import { useAppMode } from "../components/AppModeContext";
import PoseViewer from "../components/PoseViewer";
import AnalysisQualityPanel from "../components/AnalysisQualityPanel";
import { getAnalysisStatusLabel } from "../constants/analysisStatus";
import { parseApiDate, apiDateTimeFormatter } from "../utils/datetime";

type WorkspaceTab = "pose" | "evidence" | "diagnostics" | "followup";

const TAB_META: Array<{ id: WorkspaceTab; label: string; description: string }> = [
  { id: "pose", label: "姿态", description: "骨架与生物力学" },
  { id: "evidence", label: "证据", description: "关键帧与语义帧" },
  { id: "diagnostics", label: "诊断", description: "日志与质量" },
  { id: "followup", label: "追问", description: "AI 追问与修正" },
];

function formatDate(value: string) {
  return apiDateTimeFormatter({
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(value));
}

function buildTitle(analysis: AnalysisDetail) {
  return [analysis.skater_name, analysis.action_type, analysis.action_subtype].filter(Boolean).join(" · ") || analysis.id;
}

function frameValue(value: unknown) {
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(record.frame_id ?? record.frame ?? record.timestamp ?? "");
  }
  return value == null ? "" : String(value);
}

function draftKeyframesFromAnalysis(analysis: AnalysisDetail | null) {
  const keyFrames = analysis?.bio_data?.key_frames ?? {};
  return {
    T: frameValue(keyFrames.T),
    A: frameValue(keyFrames.A),
    L: frameValue(keyFrames.L),
  };
}

export default function ReportWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const { isParentMode, enterParentMode } = useAppMode();
  const [searchParams] = useSearchParams();
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [pose, setPose] = useState<PoseResponse | null>(null);
  const [selectedPoseFrame, setSelectedPoseFrame] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeTab = (searchParams.get("tab") as WorkspaceTab | null) ?? "pose";
  const title = analysis ? buildTitle(analysis) : "报告工作台";
  const draftKeyframes = useMemo(() => draftKeyframesFromAnalysis(analysis), [analysis]);

  useEffect(() => {
    setAnalysis(null);
    setPose(null);
    setSelectedPoseFrame(null);
    setNotice(null);
    setError(null);
  }, [id]);

  useEffect(() => {
    if (!id) {
      setError("无效的报告 ID。");
      return;
    }

    let cancelled = false;
    const load = async () => {
      setError(null);
      try {
        const data = await fetchAnalysis(id, { isParentRequest: true });
        if (cancelled) {
          return;
        }
        setAnalysis(data);
      } catch (requestError) {
        if (!cancelled) {
          setError(
            axios.isAxiosError(requestError)
              ? String(requestError.response?.data?.detail ?? "工作台加载失败。")
              : "工作台加载失败。",
          );
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!id || !analysis) {
      return;
    }

    if (activeTab === "pose" || activeTab === "diagnostics" || activeTab === "evidence" || activeTab === "followup") {
      let cancelled = false;
      const loadPose = async () => {
        try {
          const data = await fetchAnalysisPose(id).catch(() => analysis.pose_data);
          if (!cancelled) {
            setPose(data ?? analysis.pose_data);
          }
        } catch {
          if (!cancelled) {
            setPose(analysis.pose_data);
          }
        }
      };

      void loadPose();
      return () => {
        cancelled = true;
      };
    }
  }, [activeTab, analysis, id]);

  const showNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 2200);
  };

  const syncKeyframesToForm = (patch: KeyframeSyncPatch, sourceLabel: string) => {
    showNotice(`已从 ${sourceLabel} 选中关键帧：${Object.entries(patch)
      .map(([key, value]) => `${key}=${value}`)
      .join(" ")}`);
  };

  if (!isParentMode) {
    return (
      <section className="app-card mx-auto max-w-3xl p-8 text-center tablet:p-10">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Report Workspace</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">报告工作台</h1>
        <p className="mt-4 text-base leading-8 text-slate-500">进入家长模式后，才能查看完整姿态、证据、诊断和追问内容。</p>
        <button
          type="button"
          onClick={() => void enterParentMode()}
          className="mt-8 min-h-[48px] rounded-full bg-blue-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-600"
        >
          进入家长模式
        </button>
      </section>
    );
  }

  const tabLink = (tab: WorkspaceTab) => `/report/${id}/workspace?tab=${tab}`;

  return (
    <div className="min-w-0 space-y-6 overflow-x-hidden">
      {notice ? <div className="rounded-[24px] border border-blue-100 bg-blue-50 px-5 py-4 text-sm text-blue-700">{notice}</div> : null}
      {error ? <div className="rounded-[24px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}

      <section className="app-card overflow-hidden p-4 phone:p-5 tablet:p-7">
        <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Report Workspace</p>
            <h1 className="mt-2 break-words text-3xl font-semibold text-slate-900 tablet:text-4xl">{analysis ? title : "报告工作台"}</h1>
            {analysis ? (
              <div className="mt-3 flex flex-wrap gap-2 text-sm text-slate-500">
                <span>{getAnalysisStatusLabel(analysis.status)}</span>
                <span>{formatDate(analysis.created_at)}</span>
                {analysis.skill_category ? <span>{analysis.skill_category}</span> : null}
              </div>
            ) : null}
          </div>
          <Link to={`/report/${id}`} className="app-pill w-fit text-sm font-semibold">
            返回报告
          </Link>
        </div>

        <div className="mt-5 grid gap-2 tablet:grid-cols-2 web:grid-cols-4">
          {TAB_META.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <Link
                key={tab.id}
                to={tabLink(tab.id)}
                className={`rounded-[18px] border px-4 py-3 transition ${active ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50/40"}`}
              >
                <p className="text-sm font-semibold">{tab.label}</p>
                <p className={`mt-1 text-xs ${active ? "text-white/75" : "text-slate-500"}`}>{tab.description}</p>
              </Link>
            );
          })}
        </div>
      </section>

      {!analysis ? (
        <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-6 text-sm text-slate-500">正在加载工作台...</div>
      ) : activeTab === "pose" ? (
        <div className="grid min-w-0 gap-6 web:grid-cols-[minmax(0,1fr)_340px]">
          <section className="min-w-0 space-y-6">
            {pose?.frames?.length ? (
              <PoseViewer pose={pose} activeFrameId={selectedPoseFrame} onFrameChange={setSelectedPoseFrame} variant="debug" />
            ) : (
              <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-8 text-sm text-slate-500">当前分析没有可展示的姿态帧。</div>
            )}
            {analysis.bio_data ? <BiomechanicsPanel bioData={analysis.bio_data} mode="parent" onSelectFrame={setSelectedPoseFrame} /> : null}
            <TargetPoseDebugPanel analysisId={analysis.id} targetLock={analysis.target_lock} poseData={pose ?? analysis.pose_data} />
          </section>
          <aside className="min-w-0 space-y-4">
            <AnalysisQualityPanel analysis={analysis} />
          </aside>
        </div>
      ) : activeTab === "evidence" ? (
        <section className="space-y-4">
          <KeyframeEvidencePanel analysis={analysis} draftKeyframes={draftKeyframes} onSyncFrames={syncKeyframesToForm} />
          <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-4 text-sm text-slate-500">这里展示关键帧、语义帧和候选证据的对应关系。</div>
        </section>
      ) : activeTab === "diagnostics" ? (
        <div className="grid gap-6">
          <AnalysisQualityPanel analysis={analysis} />
          <AnalysisDebugLogPanel
            logs={analysis.processing_logs ?? []}
            timings={analysis.processing_timings}
            pipelineVersion={analysis.pipeline_version}
            videoTemporalDiagnostics={analysis.video_temporal_diagnostics}
            analysisId={analysis.id}
            targetLock={analysis.target_lock}
            poseData={pose ?? analysis.pose_data}
          />
        </div>
      ) : (
        <AnalysisFollowUpPanel
          analysis={analysis}
          compact
          variant="workspace"
          onAnalysisRefresh={() => void fetchAnalysis(analysis.id, { isParentRequest: true }).then((next) => setAnalysis(next))}
          onAnalysisRetryQueued={() => void fetchAnalysis(analysis.id, { isParentRequest: true }).then((next) => setAnalysis(next))}
          onNotice={showNotice}
        />
      )}
    </div>
  );
}
