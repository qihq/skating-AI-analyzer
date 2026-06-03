import { PointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { confirmTargetLock, fetchAnalysis, fetchTargetPreview, TargetBBox, TargetCandidate, TargetPreviewResponse } from "../api/client";

const AUTO_CONFIRM_THRESHOLD = 0.72;
const MIN_BBOX_SIZE = 0.02;
type SelectionMode = "candidate" | "manual";

function candidateLabel(candidate: TargetCandidate, isAuto: boolean) {
  return `${isAuto ? "自动推荐" : "候选"} · ${(candidate.confidence * 100).toFixed(0)}%`;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(value, max));
}

function normalizeDragBox(start: { x: number; y: number }, end: { x: number; y: number }): TargetBBox {
  const x1 = clamp(Math.min(start.x, end.x), 0, 1);
  const y1 = clamp(Math.min(start.y, end.y), 0, 1);
  const x2 = clamp(Math.max(start.x, end.x), 0, 1);
  const y2 = clamp(Math.max(start.y, end.y), 0, 1);
  return {
    x: Number(x1.toFixed(4)),
    y: Number(y1.toFixed(4)),
    width: Number((x2 - x1).toFixed(4)),
    height: Number((y2 - y1).toFixed(4)),
  };
}

export default function TargetSelectionPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const previewRef = useRef<HTMLDivElement | null>(null);
  const [preview, setPreview] = useState<TargetPreviewResponse | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("candidate");
  const [manualBBox, setManualBBox] = useState<TargetBBox | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftBBox, setDraftBBox] = useState<TargetBBox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!id) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const [previewData, analysis] = await Promise.all([fetchTargetPreview(id), fetchAnalysis(id, { isParentRequest: true })]);
        if (cancelled) {
          return;
        }
        if (analysis.status === "completed") {
          navigate(`/report/${analysis.id}`, { replace: true });
          return;
        }
        setPreview(previewData);
        setSelectedCandidateId(null);
        setSelectionMode("candidate");
      } catch {
        if (!cancelled) {
          setError("主滑行者预览加载失败，请稍后重试。");
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [id, navigate]);

  const selectedCandidate = useMemo(
    () => preview?.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? null,
    [preview, selectedCandidateId],
  );
  const activeBBox = selectionMode === "manual" ? draftBBox ?? manualBBox : selectedCandidate?.bbox ?? null;
  const requiresChoice = (preview?.lock_confidence ?? 0) < AUTO_CONFIRM_THRESHOLD;
  const noPersonDetected = preview?.target_lock_status === "no_person_detected";

  const selectCandidate = (candidateId: string) => {
    setSelectionMode("candidate");
    setSelectedCandidateId(candidateId);
    setManualBBox(null);
    setDraftBBox(null);
    setError(null);
  };

  const enableManualSelection = () => {
    setSelectionMode("manual");
    setSelectedCandidateId(null);
    setError(null);
  };

  const pointFromEvent = (event: PointerEvent<HTMLDivElement>) => {
    const rect = previewRef.current?.getBoundingClientRect();
    if (!rect) {
      return null;
    }
    return {
      x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
      y: clamp((event.clientY - rect.top) / rect.height, 0, 1),
    };
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (selectionMode !== "manual") {
      return;
    }
    const point = pointFromEvent(event);
    if (!point) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragStart(point);
    setDraftBBox({ x: point.x, y: point.y, width: 0, height: 0 });
    setSelectedCandidateId(null);
    setManualBBox(null);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) {
      return;
    }
    const point = pointFromEvent(event);
    if (point) {
      setDraftBBox(normalizeDragBox(dragStart, point));
    }
  };

  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragStart) {
      return;
    }
    const point = pointFromEvent(event);
    setDragStart(null);
    setDraftBBox(null);
    if (!point) {
      return;
    }
    const bbox = normalizeDragBox(dragStart, point);
    if (bbox.width < MIN_BBOX_SIZE || bbox.height < MIN_BBOX_SIZE) {
      setError("框选区域太小，请拖出完整身体范围。");
      return;
    }
    setError(null);
    setManualBBox(bbox);
  };

  const handleConfirm = async () => {
    if (!id) {
      return;
    }
    if (!manualBBox && !selectedCandidateId) {
      setError(requiresChoice ? "请先选择自动候选，或切到手动框选。" : "请先选择自动候选，或手动框选主滑行者。");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const updated = await confirmTargetLock(
        id,
        manualBBox ? { manual_bbox: manualBBox, candidate_id: null } : { candidate_id: selectedCandidateId },
      );
      navigate(`/report/${updated.id}`, { replace: true });
    } catch {
      setError("主滑行者确认失败，请重新选择。");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="app-card p-6 tablet:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Target Lock</p>
        <h1 className="mt-3 text-3xl font-semibold text-slate-900">确认主滑行者</h1>
        <p className="mt-4 max-w-2xl text-base leading-8 text-slate-500">
          冰场多人同框时，请确认这次要分析的选手。可以选择自动候选，也可以切换到手动框选。
        </p>
      </section>

      <section className="app-card p-6 tablet:p-8">
        <div className="mb-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => {
              setSelectionMode("candidate");
              setManualBBox(null);
              setDraftBBox(null);
              setError(null);
            }}
            className={`app-pill min-h-[44px] px-4 text-sm font-semibold ${
              selectionMode === "candidate" ? "text-blue-600 ring-2 ring-blue-100" : "text-slate-600"
            }`}
          >
            自动候选
          </button>
          <button
            type="button"
            onClick={enableManualSelection}
            className={`app-pill min-h-[44px] px-4 text-sm font-semibold ${
              selectionMode === "manual" ? "text-emerald-700 ring-2 ring-emerald-100" : "text-slate-600"
            }`}
          >
            手动框选
          </button>
        </div>

        {selectionMode === "manual" ? (
          <p className="mb-4 rounded-[18px] border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            在画面中按住并拖拽，框出主滑行者完整身体范围。
          </p>
        ) : null}

        <div
          ref={previewRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={finishDrag}
          onPointerCancel={finishDrag}
          className="relative overflow-hidden rounded-[24px] border border-slate-200 bg-slate-100 touch-none"
        >
          {preview?.preview_frame_url ? (
            <img src={preview.preview_frame_url} alt="target preview" draggable={false} className="block w-full select-none object-cover" />
          ) : (
            <div className="p-8 text-sm text-slate-500">预览帧加载中...</div>
          )}

          {activeBBox ? (
            <div
              className={`pointer-events-none absolute border-2 ${
                selectionMode === "manual" ? "border-emerald-300 bg-emerald-300/15" : "border-blue-400 bg-blue-400/15"
              }`}
              style={{
                left: `${activeBBox.x * 100}%`,
                top: `${activeBBox.y * 100}%`,
                width: `${activeBBox.width * 100}%`,
                height: `${activeBBox.height * 100}%`,
              }}
            />
          ) : null}
        </div>

        <div className="mt-6 grid gap-4 tablet:grid-cols-2">
          {preview?.candidates.map((candidate) => {
            const isAuto = candidate.id === preview.auto_candidate_id;
            const isSelected = candidate.id === selectedCandidateId && !manualBBox;
            return (
              <button
                key={candidate.id}
                type="button"
                onClick={() => selectCandidate(candidate.id)}
                className={`rounded-[24px] border p-4 text-left transition ${
                  isSelected ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <p className="text-sm font-semibold text-slate-900">{candidateLabel(candidate, isAuto)}</p>
                <p className="mt-2 text-sm text-slate-500">
                  bbox x {candidate.bbox.x.toFixed(2)} / y {candidate.bbox.y.toFixed(2)} / w {candidate.bbox.width.toFixed(2)} / h{" "}
                  {candidate.bbox.height.toFixed(2)}
                </p>
              </button>
            );
          })}
        </div>

        {manualBBox ? (
          <div className="mt-5 rounded-[24px] border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
            已使用手动框选：x {manualBBox.x.toFixed(2)} / y {manualBBox.y.toFixed(2)} / w {manualBBox.width.toFixed(2)} / h{" "}
            {manualBBox.height.toFixed(2)}
          </div>
        ) : selectedCandidate ? (
          <div className="mt-5 rounded-[24px] border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-900">
            已选择候选框：{selectedCandidate.id}，锁定置信度 {(selectedCandidate.confidence * 100).toFixed(0)}%。
          </div>
        ) : null}

        {noPersonDetected ? (
          <div className="mt-5 rounded-[24px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-700">
            未检测到可用的滑行者，建议重新上传人体更清晰、主体更完整的视频。
          </div>
        ) : null}

        {!noPersonDetected && requiresChoice && !manualBBox && !selectedCandidate ? (
          <div className="mt-5 rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            自动识别置信度不足，需要手动选择后才能继续分析。
          </div>
        ) : null}
        {error ? <div className="mt-5 rounded-[20px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</div> : null}

        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isSubmitting || (!manualBBox && !selectedCandidateId)}
            className="app-pill min-h-[52px] px-5 font-semibold text-blue-600 disabled:opacity-60"
          >
            {isSubmitting ? "确认中..." : preview && preview.lock_confidence >= AUTO_CONFIRM_THRESHOLD ? "确认并继续分析" : "锁定目标并继续分析"}
          </button>
          <button type="button" onClick={() => navigate(`/report/${id}`)} className="app-pill min-h-[52px] px-5 font-semibold text-slate-600">
            返回报告页
          </button>
        </div>
      </section>
    </div>
  );
}
