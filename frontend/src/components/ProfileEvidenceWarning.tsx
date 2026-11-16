type ProfileEvidenceWarningProps = {
  reportWarning?: string | null;
  bioWarning?: string | null;
};

export function normalizeProfileWarning(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Report-level warning wins over the biomechanics fallback. Both are authored
 * by the backend; this helper only trims and selects, it never infers a
 * warning from an internal profile enum.
 */
export function resolveProfileWarning(reportWarning: unknown, bioWarning: unknown): string {
  const fromReport = normalizeProfileWarning(reportWarning);
  if (fromReport) {
    return fromReport;
  }
  return normalizeProfileWarning(bioWarning);
}

export default function ProfileEvidenceWarning({ reportWarning, bioWarning }: ProfileEvidenceWarningProps) {
  const warning = resolveProfileWarning(reportWarning, bioWarning);
  if (!warning) {
    return null;
  }

  return (
    <p
      role="status"
      aria-live="polite"
      aria-label="分类不确定提示"
      data-testid="profile-evidence-warning"
      style={{
        margin: "8px 0",
        padding: "10px 12px",
        border: "1px solid #f0c36d",
        borderRadius: 8,
        background: "#fffbeb",
        color: "#7a4f01",
        lineHeight: 1.5,
      }}
    >
      {warning}
    </p>
  );
}
