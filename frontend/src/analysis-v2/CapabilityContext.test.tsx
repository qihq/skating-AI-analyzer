import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fetchRuntimeCapabilities } from "./api";
import { CapabilityProvider, useRuntimeCapabilities } from "./CapabilityContext";

vi.mock("./api", () => ({ fetchRuntimeCapabilities: vi.fn() }));
const mockedFetch = vi.mocked(fetchRuntimeCapabilities);

function Probe() {
  const { capabilities, loadState } = useRuntimeCapabilities();
  return <div><span>{loadState}</span><span>{capabilities.publicAuthority}</span><span>{String(capabilities.enableV2Components)}</span></div>;
}

describe("CapabilityProvider", () => {
  it("renders a complete legacy fallback while capability loading is pending", () => {
    mockedFetch.mockReturnValue(new Promise(() => undefined));
    render(<CapabilityProvider><Probe /></CapabilityProvider>);
    expect(screen.getByText("loading")).toBeInTheDocument();
    expect(screen.getByText("legacy")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
  });

  it("keeps the complete legacy fallback after an API error", async () => {
    mockedFetch.mockRejectedValue(new Error("offline"));
    render(<CapabilityProvider><Probe /></CapabilityProvider>);
    await waitFor(() => expect(screen.getByText("fallback")).toBeInTheDocument());
    expect(screen.getByText("legacy")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
  });

  it("accepts compatible capabilities without enabling V2 in shadow mode", async () => {
    mockedFetch.mockResolvedValue({
      schemaVersion: "runtime-capabilities.v1",
      supportedAnalysisExperienceSchemaVersions: [],
      runtimeMode: "shadow",
      publicAuthority: "legacy",
      enableV2Components: false,
      parentTools: { shadow: true, golden: true, diagnostics: true },
      compatible: true,
    });
    render(<CapabilityProvider><Probe /></CapabilityProvider>);
    await waitFor(() => expect(screen.getByText("ready")).toBeInTheDocument());
    expect(screen.getByText("legacy")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
  });
});
