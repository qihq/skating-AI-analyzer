import { apiClient } from "../api/client";
import { AdvancedRuntimeCapabilities, decodeRuntimeCapabilities, RuntimeCapabilities } from "./contracts";
import { GoldenCatalogSummary, GoldenSanitizedExport, GoldenSchemaInfo } from "./golden-contracts";

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
