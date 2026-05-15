import { AnalysisDetail, CrossValidationData, FusionDiagnostics, VisionStructuredData } from "../api/client";
import ReportCard from "./ReportCard";

type QualityLevel = "good" | "partial" | "poor" | "unknown";

const DATA_QUALITY_LABELS: Record<QualityLevel, string> = {
  good: "完整",
  partial: "部分可用",
  poor: "较弱",
  unknown: "未标注",
};

const CONFLICT_LABELS: Record<string, string> = {
  none: "无明显冲突",
  low: "轻微冲突",
  medium: "中等冲突",
  high: "高冲突",
  unknown: "未标注",
};

const STATUS_STYLES: Record<string, string> = {
  good: "border-emerald-200 bg-emerald-50 text-emerald-700",
  none: "border-emerald-200 bg-emerald-50 text-emerald-700",
  low: "border-sky-200 bg-sky-50 text-sky-700",
  partial: "border-amber-200 bg-amber-50 text-amber-700",
  medium: "border-amber-200 bg-amber-50 text-amber-700",
  poor: "border-rose-200 bg-rose-50 text-rose-700",
  high: "border-rose-200 bg-rose-50 text-rose-700",
  unknown: "border-slate-200 bg-slate-50 text-slate-600",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function normalizeDataQuality(value: unknown): QualityLevel {
  const text = asString(value);
  if (text === "good" || text === "partial" || text === "poor") {
    return text;
  }
  return "unknown";
}

function normalizeConflictLevel(value: unknown): string {
  const text = asString(value)?.toLowerCase();
  return text && text in CONFLICT_LABELS ? text : "unknown";
}

function resolveFusionDiagnostics(crossValidation: CrossValidationData | null | undefined): FusionDiagnostics {
  const direct = asRecord(crossValidation?.fusion_diagnostics);
  if (direct) {
    return direct as FusionDiagnostics;
  }
  return {
    conflict_level: asString(crossValidation?.conflict_level) ?? "unknown",
    downgraded_reasons: asStringArray(crossValidation?.downgraded_reasons),
    needs_human_review: Boolean(crossValidation?.needs_human_review),
  };
}

function resolveKeyFrameOrderValid(crossValidation: CrossValidationData | null | undefined, diagnostics: FusionDiagnostics): boolean | null {
  if (typeof crossValidation?.auto_eval?.key_frame_order_valid === "boolean") {
    return crossValidation.auto_eval.key_frame_order_valid;
  }
  if (typeof diagnostics.key_frame_order_invalid === "boolean") {
    return !diagnostics.key_frame_order_invalid;
  }
  return null;
}

function resolveDataQuality(analysis: AnalysisDetail): QualityLevel {
  const vision = analysis.vision_structured as VisionStructuredData | null;
  return normalizeDataQuality(vision?.data_quality_hint ?? analysis.report?.data_quality);
}

function MetricTile({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`rounded-[22px] border px-4 py-3 ${STATUS_STYLES[tone] ?? STATUS_STYLES.unknown}`}>
      <p className="text-xs font-semibold uppercase tracking-[0.18em] opacity-70">{label}</p>
      <p className="mt-2 text-base font-semibold">{value}</p>
    </div>
  );
}

export default function AnalysisQualityPanel({ analysis }: { analysis: AnalysisDetail }) {
  const diagnostics = resolveFusionDiagnostics(analysis.cross_validation);
  const dataQuality = resolveDataQuality(analysis);
  const conflictLevel = normalizeConflictLevel(diagnostics.conflict_level ?? analysis.vision_structured?.conflict_level);
  const needsHumanReview = Boolean(diagnostics.needs_human_review);
  const keyFrameOrderValid = resolveKeyFrameOrderValid(analysis.cross_validation, diagnostics);
  const reasons = asStringArray(diagnostics.downgraded_reasons).slice(0, 4);

  return (
    <ReportCard title="质量诊断" eyebrow="Quality Check">
      <div className="grid gap-3 sm:grid-cols-2">
        <MetricTile label="数据质量" value={DATA_QUALITY_LABELS[dataQuality]} tone={dataQuality} />
        <MetricTile label="冲突等级" value={CONFLICT_LABELS[conflictLevel] ?? conflictLevel} tone={conflictLevel} />
        <MetricTile label="建议复查" value={needsHumanReview ? "建议人工复查" : "暂不需要"} tone={needsHumanReview ? "high" : "none"} />
        <MetricTile
          label="关键帧顺序"
          value={keyFrameOrderValid == null ? "未标注" : keyFrameOrderValid ? "顺序正常" : "顺序异常"}
          tone={keyFrameOrderValid == null ? "unknown" : keyFrameOrderValid ? "none" : "high"}
        />
      </div>

      {reasons.length ? (
        <div className="mt-4 rounded-[22px] border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-sm font-semibold text-slate-900">降权原因</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {reasons.map((reason) => (
              <span key={reason} className="rounded-full bg-white px-3 py-1 text-xs text-slate-600">
                {reason}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </ReportCard>
  );
}
