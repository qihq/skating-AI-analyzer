import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { confirmTargetLock, fetchAnalysis, fetchTargetPreview, TargetCandidate, TargetPreviewResponse } from "../api/client";

function candidateLabel(candidate: TargetCandidate, isAuto: boolean) {
  return `${isAuto ? "自动推荐" : "候选"} · ${(candidate.confidence * 100).toFixed(0)}%`;
}

export default function TargetSelectionPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<TargetPreviewResponse | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
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
        setSelectedCandidateId(previewData.auto_candidate_id);
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

  const handleConfirm = async () => {
    if (!id || !selectedCandidateId) {
      setError("请先选择要分析的主滑行者。");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const updated = await confirmTargetLock(id, { candidate_id: selectedCandidateId });
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
          冰场里人比较多时，我们会先自动锁定一位滑行者。请确认这次要分析的是哪一位，后续骨架和动作诊断都会只跟随她。
        </p>
      </section>

      <section className="app-card p-6 tablet:p-8">
        {preview?.preview_frame_url ? (
          <img src={preview.preview_frame_url} alt="target preview" className="w-full rounded-[24px] border border-slate-200 object-cover" />
        ) : (
          <div className="rounded-[24px] border border-dashed border-slate-300 p-8 text-sm text-slate-500">预览帧加载中…</div>
        )}

        <div className="mt-6 grid gap-4 tablet:grid-cols-2">
          {preview?.candidates.map((candidate) => {
            const isAuto = candidate.id === preview.auto_candidate_id;
            const isSelected = candidate.id === selectedCandidateId;
            return (
              <button
                key={candidate.id}
                type="button"
                onClick={() => setSelectedCandidateId(candidate.id)}
                className={`rounded-[24px] border p-4 text-left transition ${
                  isSelected ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <p className="text-sm font-semibold text-slate-900">{candidateLabel(candidate, isAuto)}</p>
                <p className="mt-2 text-sm text-slate-500">
                  框选区域：x {candidate.bbox.x.toFixed(2)} / y {candidate.bbox.y.toFixed(2)} / w {candidate.bbox.width.toFixed(2)} / h {candidate.bbox.height.toFixed(2)}
                </p>
              </button>
            );
          })}
        </div>

        {selectedCandidate ? (
          <div className="mt-5 rounded-[24px] border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-900">
            已选择候选框：{selectedCandidate.id}，锁定置信度 {(selectedCandidate.confidence * 100).toFixed(0)}%。
          </div>
        ) : null}

        {error ? <div className="mt-5 rounded-[20px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</div> : null}

        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isSubmitting || !selectedCandidateId}
            className="app-pill min-h-[52px] px-5 font-semibold text-blue-600 disabled:opacity-60"
          >
            {isSubmitting ? "确认中..." : "确认这位主滑行者"}
          </button>
          <button type="button" onClick={() => navigate(`/report/${id}`)} className="app-pill min-h-[52px] px-5 font-semibold text-slate-600">
            返回报告页
          </button>
        </div>
      </section>
    </div>
  );
}
