import { PointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { confirmTargetLock, fetchAnalysis, fetchTargetPreview, TargetBBox, TargetCandidate, TargetPreviewResponse } from "../api/client";
import SubmitButton from "../modern/SubmitButton";

const AUTO_CONFIRM_THRESHOLD = 0.72;
const MIN_BBOX_SIZE = 0.02;
type SelectionMode = "candidate" | "manual";
type RectSize = { width: number; height: number };
type ImageRect = { left: number; top: number; width: number; height: number };
type ViewTransform = { scale: number; x: number; y: number };
type PointerPoint = { id: number; x: number; y: number };

const MAX_VIEW_SCALE = 4;
const MIN_VIEW_SCALE = 1;

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

function clampPan(value: number, scaledSize: number, containerSize: number) {
  if (scaledSize <= containerSize) {
    return 0;
  }
  return clamp(value, containerSize - scaledSize, 0);
}

function clampTransform(transform: ViewTransform, imageRect: ImageRect, previewSize: RectSize | null): ViewTransform {
  if (!previewSize || imageRect.width <= 0 || imageRect.height <= 0) {
    return { scale: MIN_VIEW_SCALE, x: 0, y: 0 };
  }
  const scale = clamp(transform.scale, MIN_VIEW_SCALE, MAX_VIEW_SCALE);
  return {
    scale,
    x: clampPan(transform.x, imageRect.width * scale, previewSize.width),
    y: clampPan(transform.y, imageRect.height * scale, previewSize.height),
  };
}

function distanceBetween(a: PointerPoint, b: PointerPoint) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function midpoint(a: PointerPoint, b: PointerPoint) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

export default function TargetSelectionPage({ hideHeader = false }: { hideHeader?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const previewRef = useRef<HTMLDivElement | null>(null);
  const activePointersRef = useRef(new Map<number, PointerPoint>());
  const gestureRef = useRef<{
    startDistance: number;
    startMidpoint: { x: number; y: number };
    startTransform: ViewTransform;
  } | null>(null);
  const [previewSize, setPreviewSize] = useState<RectSize | null>(null);
  const [imageSize, setImageSize] = useState<RectSize | null>(null);
  const [preview, setPreview] = useState<TargetPreviewResponse | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("candidate");
  const [manualBBox, setManualBBox] = useState<TargetBBox | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftBBox, setDraftBBox] = useState<TargetBBox | null>(null);
  const [viewTransform, setViewTransform] = useState<ViewTransform>({ scale: 1, x: 0, y: 0 });
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

  useEffect(() => {
    const node = previewRef.current;
    if (!node) {
      return;
    }
    const updateSize = () => {
      const rect = node.getBoundingClientRect();
      setPreviewSize({ width: rect.width, height: rect.height });
    };
    updateSize();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateSize);
      return () => window.removeEventListener("resize", updateSize);
    }
    const observer = new ResizeObserver(updateSize);
    observer.observe(node);
    return () => observer.disconnect();
  }, [preview?.preview_frame_url]);

  useEffect(() => {
    activePointersRef.current.clear();
    gestureRef.current = null;
    setDragStart(null);
    setDraftBBox(null);
    setViewTransform({ scale: 1, x: 0, y: 0 });
  }, [preview?.preview_frame_url]);

  const selectedCandidate = useMemo(
    () => preview?.candidates.find((candidate) => candidate.id === selectedCandidateId) ?? null,
    [preview, selectedCandidateId],
  );
  const activeBBox = selectionMode === "manual" ? draftBBox ?? manualBBox : selectedCandidate?.bbox ?? null;
  const imageRect = useMemo<ImageRect>(() => {
    if (!previewSize || !imageSize || previewSize.width <= 0 || previewSize.height <= 0 || imageSize.width <= 0 || imageSize.height <= 0) {
      return { left: 0, top: 0, width: previewSize?.width ?? 0, height: previewSize?.height ?? 0 };
    }
    const containerRatio = previewSize.width / previewSize.height;
    const imageRatio = imageSize.width / imageSize.height;
    if (containerRatio > imageRatio) {
      const height = previewSize.height;
      const width = height * imageRatio;
      return { left: (previewSize.width - width) / 2, top: 0, width, height };
    }
    const width = previewSize.width;
    const height = width / imageRatio;
    return { left: 0, top: (previewSize.height - height) / 2, width, height };
  }, [imageSize, previewSize]);
  const requiresChoice = (preview?.lock_confidence ?? 0) < AUTO_CONFIRM_THRESHOLD;
  const noPersonDetected = preview?.target_lock_status === "no_person_detected";
  const transformedImageRect = useMemo(
    () => ({
      left: imageRect.left + viewTransform.x,
      top: imageRect.top + viewTransform.y,
      width: imageRect.width * viewTransform.scale,
      height: imageRect.height * viewTransform.scale,
    }),
    [imageRect, viewTransform],
  );

  useEffect(() => {
    setViewTransform((current) => clampTransform(current, imageRect, previewSize));
  }, [imageRect, previewSize]);

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
    if (!rect || imageRect.width <= 0 || imageRect.height <= 0) {
      return null;
    }
    return {
      x: clamp((event.clientX - rect.left - imageRect.left - viewTransform.x) / (imageRect.width * viewTransform.scale), 0, 1),
      y: clamp((event.clientY - rect.top - imageRect.top - viewTransform.y) / (imageRect.height * viewTransform.scale), 0, 1),
    };
  };

  const pointerPointFromEvent = (event: PointerEvent<HTMLDivElement>): PointerPoint | null => {
    const rect = previewRef.current?.getBoundingClientRect();
    if (!rect) {
      return null;
    }
    return { id: event.pointerId, x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const beginGestureIfNeeded = () => {
    const pointers = Array.from(activePointersRef.current.values());
    if (pointers.length < 2) {
      gestureRef.current = null;
      return false;
    }
    const [first, second] = pointers;
    gestureRef.current = {
      startDistance: Math.max(distanceBetween(first, second), 1),
      startMidpoint: midpoint(first, second),
      startTransform: viewTransform,
    };
    setDragStart(null);
    setDraftBBox(null);
    return true;
  };

  const updateGesture = () => {
    const gesture = gestureRef.current;
    const pointers = Array.from(activePointersRef.current.values());
    if (!gesture || pointers.length < 2) {
      return false;
    }
    const [first, second] = pointers;
    const nextMidpoint = midpoint(first, second);
    const nextDistance = Math.max(distanceBetween(first, second), 1);
    const nextScale = clamp(gesture.startTransform.scale * (nextDistance / gesture.startDistance), MIN_VIEW_SCALE, MAX_VIEW_SCALE);
    const imageLocalX = (gesture.startMidpoint.x - imageRect.left - gesture.startTransform.x) / Math.max(gesture.startTransform.scale, 0.001);
    const imageLocalY = (gesture.startMidpoint.y - imageRect.top - gesture.startTransform.y) / Math.max(gesture.startTransform.scale, 0.001);
    setViewTransform(
      clampTransform(
        {
          scale: nextScale,
          x: nextMidpoint.x - imageRect.left - imageLocalX * nextScale,
          y: nextMidpoint.y - imageRect.top - imageLocalY * nextScale,
        },
        imageRect,
        previewSize,
      ),
    );
    return true;
  };

  const resetView = () => {
    activePointersRef.current.clear();
    gestureRef.current = null;
    setDragStart(null);
    setDraftBBox(null);
    setViewTransform({ scale: 1, x: 0, y: 0 });
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const pointer = pointerPointFromEvent(event);
    if (pointer) {
      activePointersRef.current.set(event.pointerId, pointer);
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    if (beginGestureIfNeeded()) {
      return;
    }
    if (selectionMode !== "manual") {
      return;
    }
    const point = pointFromEvent(event);
    if (!point) {
      return;
    }
    setDragStart(point);
    setDraftBBox({ x: point.x, y: point.y, width: 0, height: 0 });
    setSelectedCandidateId(null);
    setManualBBox(null);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const pointer = pointerPointFromEvent(event);
    if (pointer && activePointersRef.current.has(event.pointerId)) {
      activePointersRef.current.set(event.pointerId, pointer);
    }
    if (updateGesture()) {
      return;
    }
    if (!dragStart) {
      return;
    }
    const point = pointFromEvent(event);
    if (point) {
      setDraftBBox(normalizeDragBox(dragStart, point));
    }
  };

  const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
    activePointersRef.current.delete(event.pointerId);
    if (gestureRef.current) {
      if (activePointersRef.current.size < 2) {
        gestureRef.current = null;
      }
      return;
    }
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
      {!hideHeader ? <section className="app-card p-4 phone:p-6 tablet:p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-blue-500">Target Lock</p>
        <h1 className="mt-3 text-3xl font-semibold text-slate-900">确认主滑行者</h1>
        <p className="mt-4 max-w-2xl text-base leading-8 text-slate-500">
          冰场多人同框时，请确认这次要分析的选手。可以选择自动候选，也可以切换到手动框选。
        </p>
      </section> : null}

      <section className="app-card p-6 tablet:p-8">
        <div className="mb-4 flex flex-col gap-3 phone:flex-row phone:flex-wrap">
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
          className="relative h-[62vh] min-h-[340px] w-full overflow-hidden rounded-[24px] border-2 border-slate-300 bg-slate-100 touch-none phone:h-[68vh] phone:min-h-[420px] tablet:h-[min(72vh,680px)] tablet:min-h-[520px]"
        >
          {preview?.preview_frame_url ? (
            <img
              src={preview.preview_frame_url}
              alt="target preview"
              draggable={false}
              onLoad={(event) => setImageSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
              className="absolute select-none"
              style={{
                left: `${imageRect.left}px`,
                top: `${imageRect.top}px`,
                width: `${imageRect.width}px`,
                height: `${imageRect.height}px`,
                transform: `translate3d(${viewTransform.x}px, ${viewTransform.y}px, 0) scale(${viewTransform.scale})`,
                transformOrigin: "top left",
              }}
            />
          ) : (
            <div className="p-8 text-sm text-slate-500">预览帧加载中...</div>
          )}

          <div className="absolute right-3 top-3 z-10 flex items-center gap-2 rounded-full bg-white/90 px-2 py-2 text-xs font-semibold text-slate-600 shadow-sm">
            <span className="px-2">{Math.round(viewTransform.scale * 100)}%</span>
            <button
              type="button"
              onClick={resetView}
              className="min-h-[32px] rounded-full bg-slate-900 px-3 text-white transition hover:bg-slate-700"
            >
              é‡ç½®è§†å›¾
            </button>
          </div>

          {activeBBox ? (
            <div
              className={`pointer-events-none absolute border-4 ${
                selectionMode === "manual" ? "border-emerald-300 bg-emerald-300/18" : "border-blue-400 bg-blue-400/18"
              }`}
              style={{
                left: `${transformedImageRect.left + activeBBox.x * transformedImageRect.width}px`,
                top: `${transformedImageRect.top + activeBBox.y * transformedImageRect.height}px`,
                width: `${activeBBox.width * transformedImageRect.width}px`,
                height: `${activeBBox.height * transformedImageRect.height}px`,
                boxShadow: "0 0 0 9999px rgba(15,23,42,0.22), 0 0 0 2px rgba(255,255,255,0.95), 0 12px 32px rgba(15,23,42,0.32)",
              }}
            >
              <span className="absolute -left-1.5 -top-1.5 h-4 w-4 border-l-4 border-t-4 border-white" />
              <span className="absolute -right-1.5 -top-1.5 h-4 w-4 border-r-4 border-t-4 border-white" />
              <span className="absolute -bottom-1.5 -left-1.5 h-4 w-4 border-b-4 border-l-4 border-white" />
              <span className="absolute -bottom-1.5 -right-1.5 h-4 w-4 border-b-4 border-r-4 border-white" />
            </div>
          ) : null}
        </div>

        <div className="mt-6 grid max-h-[520px] gap-4 overflow-y-auto pr-1 tablet:grid-cols-2 web:grid-cols-3">
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

        <div className="mt-6 flex flex-col gap-3 phone:flex-row phone:flex-wrap">
          <SubmitButton
            onClick={handleConfirm}
            disabled={!manualBBox && !selectedCandidateId}
            status={isSubmitting ? "submitting" : error ? "error" : "idle"}
            error={error}
            loadingLabel="确认中..."
            className="app-pill min-h-[52px] justify-center px-5 font-semibold text-blue-600 disabled:opacity-60"
          >
            {preview && preview.lock_confidence >= AUTO_CONFIRM_THRESHOLD ? "确认并继续分析" : "锁定目标并继续分析"}
          </SubmitButton>
          <button type="button" onClick={() => navigate(`/report/${id}`)} className="app-pill min-h-[52px] justify-center px-5 font-semibold text-slate-600">
            返回报告页
          </button>
        </div>
      </section>
    </div>
  );
}
