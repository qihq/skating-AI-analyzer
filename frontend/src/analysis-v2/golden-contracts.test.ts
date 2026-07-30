import { describe, expect, it } from "vitest";

import { isGoldenCatalogSummary, isPilotSanitizedResult } from "./golden-contracts";

describe("Golden V2 transport contract", () => {
  it("accepts only bounded catalog summaries", () => {
    expect(isGoldenCatalogSummary({ dataset_id: "golden-v2-private-catalog", schema_version: "golden-dataset.v2", revision: 1, status: "empty", source_count: 0, event_count: 0, profile_counts: [], observability_counts: [], strata_counts: [], duplicate_sources: [] })).toBe(true);
    expect(isGoldenCatalogSummary({ dataset_id: "golden-v2-private-catalog", schema_version: "golden-dataset.v2", revision: 0, status: "schema-incompatible", source_count: 0, event_count: 0, profile_counts: [], observability_counts: [], strata_counts: [], duplicate_sources: [] })).toBe(true);
    expect(isGoldenCatalogSummary({ schema_version: "golden-dataset.v1", status: "empty" })).toBe(false);
  });

  it("accepts only explicitly diagnostic pilot results", () => {
    const base = { schema_version: "golden-pilot-sanitized-report.v1", diagnostic_only: true, release_claim: false, dataset_fingerprint: "a", pipeline_fingerprint: "b", evaluation_masks: ["tracking"], aggregate: {}, failed_events: [] };
    expect(isPilotSanitizedResult(base)).toBe(true);
    expect(isPilotSanitizedResult({ ...base, release_claim: true })).toBe(false);
  });
});
