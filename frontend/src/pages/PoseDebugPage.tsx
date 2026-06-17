import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { AnalysisDetail, fetchAnalysis, fetchAnalysisPose, PoseFrame, PoseResponse } from "../api/client";
import { normalizePoseDiagnosticFrames, TargetPoseDebugPanel } from "../components/AnalysisDebugLogPanel";
import { useAppMode } from "../components/AppModeContext";
import BiomechanicsPanel from "../components/BiomechanicsPanel";
import PoseViewer from "../components/PoseViewer";
import { getAnalysisStatusLabel } from "../constants/analysisStatus";
import { parseApiDate } from "../utils/datetime";

type LoadState = "idle" | "loading" | "ready" | "error";

function frameIdFromName(frame: string) {
  return frame.replace(/\.jpg$/i, "");
}

function buildTitle(analysis: AnalysisDetail) {
  return [analysis.skater_name, analysis.action_type, analysis.action_subtype].filter(Boolean).join(" · ") || analysis.id;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDate(value));
}

function formatConfidence(value: number | null | undefined) {
  return typeof value === "number" && !Number.isNaN(value) ? value.toFixed(3) : "-";
}

function formatBBox(frame: PoseFrame | undefined) {
  const bbox = frame?.target_bbox;
  if (!bbox) {
    return "-";
  }
  return `x ${bbox.x.toFixed(3)} · y ${bbox.y.toFixed(3)} · w ${bbox.width.toFixed(3)} · h ${bbox.height.toFixed(3)}`;
}

export default function PoseDebugPage() {
  const { id } = useParams();
  const { isParentMode, enterParentMode } = useAppMode();
  const [analysis, setAnalysis] = useState<AnalysisDetail | null>(null);
  const [pose, setPose] = useState<PoseResponse | null>(null);
  const [selectedPoseFrame, setSelectedPoseFrame] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id || !isParentMode) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      setState("loading");
      setError(null);
      try {
        const analysisData = await fetchAnalysis(id, { isParentRequest: true });
        const poseData = await fetchAnalysisPose(id).catch(() => analysisData.pose_data);
        if (cancelled) {
          return;
        }
        setAnalysis(analysisData);
        setPose(poseData ?? analysisData.pose_data);
        setState("ready");
      } catch (requestError) {
        if (cancelled) {
          return;
        }
        setState("error");
        setError(
          axios.isAxiosError(requestError)
            ? String(requestError.response?.data?.detail ?? "Pose Debug 加载失败，请稍后重试。")
            : "Pose Debug 加载失败，请稍后重试。",
        );
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [id, isParentMode]);

  const poseFrames = pose?.frames ?? [];
  const currentFrame = useMemo(() => {
    if (!poseFrames.length) {
      return undefined;
    }
    if (!selectedPoseFrame) {
      return poseFrames[0];
    }
    return poseFrames.find((frame) => frameIdFromName(frame.frame) === selectedPoseFrame) ?? poseFrames[0];
  }, [poseFrames, selectedPoseFrame]);
  const diagnostics = useMemo(() => normalizePoseDiagnosticFrames(pose), [pose]);
  const currentDiagnostic = useMemo(() => {
    if (!currentFrame) {
      return undefined;
    }
    return diagnostics.find((frame) => frame.frame === currentFrame.frame);
  }, [currentFrame, diagnostics]);

  if (!isParentMode) {
    return (
      <section className="app-card mx-auto max-w-3xl p-8 text-center tablet:p-10">
        <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Pose Debug</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-900 tablet:text-4xl">骨架调试</h1>
        <p className="mt-4 text-base leading-8 text-slate-500">进入家长模式后，才能查看完整骨架、追踪和逐帧诊断数据。</p>
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

  return (
    <div className="safe-bottom min-w-0 space-y-6 overflow-x-hidden">
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-start tablet:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-blue-500">Pose Debug</p>
          <h1 className="mt-2 break-words text-3xl font-semibold text-slate-900 tablet:text-4xl">
            {analysis ? buildTitle(analysis) : "骨架调试"}
          </h1>
          {analysis ? (
            <div className="mt-3 flex flex-wrap gap-2 text-sm text-slate-500">
              <span>{getAnalysisStatusLabel(analysis.status)}</span>
              <span>{formatDate(analysis.created_at)}</span>
              <span>Pipeline {analysis.pipeline_version ?? "v5.2.1"}</span>
              {analysis.analysis_profile ? <span>{analysis.analysis_profile}</span> : null}
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-3">
          {analysis ? (
            <Link to={`/report/${analysis.id}`} className="app-pill text-sm font-semibold">
              返回报告
            </Link>
          ) : null}
          <Link to="/debug" className="app-pill text-sm font-semibold">
            调试日志
          </Link>
        </div>
      </div>

      {error ? <div className="rounded-[24px] border border-rose-100 bg-rose-50 px-5 py-4 text-sm text-rose-600">{error}</div> : null}

      {state === "loading" ? (
        <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-6 text-sm text-slate-500">正在加载骨架调试数据...</div>
      ) : null}

      {state === "ready" && analysis ? (
        <>
          <section className="grid min-w-0 gap-5 web:grid-cols-[minmax(0,1fr)_340px] web:items-start">
            <div className="min-w-0">
              {pose?.frames?.length ? (
                <PoseViewer pose={pose} activeFrameId={selectedPoseFrame} onFrameChange={setSelectedPoseFrame} variant="debug" />
              ) : (
                <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-5 py-8 text-sm text-slate-500">当前分析没有可展示的骨架帧。</div>
              )}
            </div>

            <aside className="min-w-0 rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">Current Frame</p>
              <p className="mt-3 break-all font-mono text-sm font-semibold text-slate-900">{currentFrame?.frame ?? "-"}</p>
              <div className="mt-5 grid gap-3 text-sm text-slate-600 tablet:grid-cols-2 web:grid-cols-1">
                <div className="rounded-[18px] bg-slate-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">State</p>
                  <p className="mt-2 break-words text-slate-900">{currentFrame?.tracking_state ?? currentDiagnostic?.tracking_state ?? "-"}</p>
                </div>
                <div className="rounded-[18px] bg-slate-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Confidence</p>
                  <p className="mt-2 text-slate-900">{formatConfidence(currentFrame?.tracking_confidence ?? currentDiagnostic?.tracking_confidence)}</p>
                </div>
                <div className="rounded-[18px] bg-slate-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Candidates</p>
                  <p className="mt-2 text-slate-900">{currentFrame?.pose_candidates?.length ?? currentDiagnostic?.candidate_count ?? "-"}</p>
                </div>
                <div className="rounded-[18px] bg-slate-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">BBox</p>
                  <p className="mt-2 break-words font-mono text-xs leading-6 text-slate-900">{formatBBox(currentFrame)}</p>
                </div>
              </div>
            </aside>
          </section>

          {analysis.bio_data ? (
            <section className="app-card p-5 tablet:p-6">
              <div className="mb-4">
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Biomechanics</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-900">生物力学关键帧</h2>
              </div>
              <BiomechanicsPanel bioData={analysis.bio_data} mode="parent" onSelectFrame={setSelectedPoseFrame} />
            </section>
          ) : null}

          <TargetPoseDebugPanel analysisId={analysis.id} targetLock={analysis.target_lock} poseData={pose ?? analysis.pose_data} />
        </>
      ) : null}
    </div>
  );
}
