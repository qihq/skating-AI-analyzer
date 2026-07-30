export type GoldenCatalogStatus = "empty" | "ready" | "invalid-source" | "schema-incompatible";

export interface GoldenCatalogSummary {
  dataset_id: string;
  schema_version: "golden-dataset.v2";
  revision: number;
  status: GoldenCatalogStatus;
  source_count: number;
  event_count: number;
  profile_counts: GoldenCount[];
  observability_counts: GoldenCount[];
  strata_counts: GoldenCount[];
  duplicate_sources: string[];
}

export interface GoldenSchemaInfo {
  schema_version: "golden-dataset.v2";
  supported_schema_versions: string[];
  migration_policy: "future-v2-only";
  historical_debug_pool: "not-imported";
}

export interface GoldenSanitizedExport {
  schema_version: "golden-sanitized-summary.v1";
  dataset_id: string;
  golden_schema_version: "golden-dataset.v2";
  revision: number;
  aggregate: {
    source_count: number;
    event_count: number;
    profile_counts: GoldenCount[];
    observability_counts: GoldenCount[];
    strata_counts: GoldenCount[];
  };
  redacted_aliases: string[];
  gate_template: { gate: "G1"; status: "not-run"; required_new_events: number };
}

export interface GoldenCount { key: string; count: number; }

export function isGoldenCatalogSummary(value: unknown): value is GoldenCatalogSummary {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return record.schema_version === "golden-dataset.v2" &&
    (record.status === "empty" || record.status === "ready" || record.status === "invalid-source" || record.status === "schema-incompatible") &&
    typeof record.dataset_id === "string" && typeof record.revision === "number" &&
    typeof record.source_count === "number" && typeof record.event_count === "number" &&
    Array.isArray(record.duplicate_sources);
}
