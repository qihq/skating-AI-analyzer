import { apiClient } from "../api/client";
import { AdvancedRuntimeCapabilities, decodeRuntimeCapabilities, RuntimeCapabilities } from "./contracts";
import { GoldenCatalogSummary, GoldenReviewItem, GoldenSanitizedExport, GoldenSchemaInfo, GoldenWorkspace } from "./golden-contracts";

export async function fetchRuntimeCapabilities(): Promise<RuntimeCapabilities> {
  const response = await apiClient.get<unknown>("/capabilities", { timeout: 10_000 });
  return decodeRuntimeCapabilities(response.data);
}

export async function fetchAdvancedRuntimeCapabilities(parentPin: string): Promise<AdvancedRuntimeCapabilities> {
  const response = await apiClient.get<AdvancedRuntimeCapabilities>("/capabilities/advanced", {
    headers: { "X-Parent-Pin": parentPin }, timeout: 10_000,
  });
  return response.data;
}

export async function fetchGoldenCatalog(parentPin: string): Promise<GoldenCatalogSummary> {
  const response = await apiClient.get<GoldenCatalogSummary>("/golden/v2/catalog", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenSchema(parentPin: string): Promise<GoldenSchemaInfo> {
  const response = await apiClient.get<GoldenSchemaInfo>("/golden/v2/schema", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenSanitizedExport(parentPin: string): Promise<GoldenSanitizedExport> {
  const response = await apiClient.get<GoldenSanitizedExport>("/golden/v2/sanitized-export", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenWorkspace(parentPin: string): Promise<GoldenWorkspace> {
  const response = await apiClient.get<GoldenWorkspace>("/golden/v2/workspace", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenReviewQueue(parentPin: string): Promise<GoldenReviewItem[]> {
  const response = await apiClient.get<GoldenReviewItem[]>("/golden/v2/review-queue", { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function fetchGoldenSourceFrame(parentPin: string, sourceHash: string, frameIndex: number) {
  const response = await apiClient.get<{ source_frame_index: number; pts: number; duration: number | null }>(`/golden/v2/sources/${sourceHash}/frames/${frameIndex}`, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return { sourceFrameIndex: response.data.source_frame_index, pts: response.data.pts, duration: response.data.duration };
}

export async function saveGoldenAnnotations(parentPin: string, payload: { expected_revision: number; annotator_alias: string; change_note?: string | null; events: unknown[]; tracks: unknown[]; poses: unknown[] }): Promise<GoldenWorkspace> {
  const response = await apiClient.put<GoldenWorkspace>("/golden/v2/annotations", payload, { headers: { "X-Parent-Pin": parentPin }, timeout: 10_000 });
  return response.data;
}

export async function importGoldenSource(parentPin: string, form: FormData): Promise<GoldenWorkspace["sources"][number]> {
  const response = await apiClient.post<GoldenWorkspace["sources"][number]>("/golden/v2/sources/import", form, { headers: { "X-Parent-Pin": parentPin }, timeout: 60_000 });
  return response.data;
}
