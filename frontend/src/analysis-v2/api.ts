import { apiClient } from "../api/client";
import { AdvancedRuntimeCapabilities, decodeRuntimeCapabilities, RuntimeCapabilities } from "./contracts";

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
