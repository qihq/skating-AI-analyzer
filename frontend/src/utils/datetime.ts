const ISO_WITH_TIMEZONE = /(?:z|[+-]\d{2}:?\d{2})$/i;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

export function parseApiDate(value: string | null | undefined): Date {
  if (!value) {
    return new Date(Number.NaN);
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return new Date(Number.NaN);
  }
  if (DATE_ONLY.test(trimmed)) {
    return new Date(`${trimmed}T00:00:00Z`);
  }
  const isoLike = trimmed.includes(" ") && !trimmed.includes("T") ? trimmed.replace(" ", "T") : trimmed;
  const normalized = ISO_WITH_TIMEZONE.test(isoLike) ? isoLike : `${isoLike}Z`;
  return new Date(normalized);
}

export function apiDateTimeFormatter(options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat("zh-CN", options);
}

export function localDateKey(value: Date = new Date()): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
