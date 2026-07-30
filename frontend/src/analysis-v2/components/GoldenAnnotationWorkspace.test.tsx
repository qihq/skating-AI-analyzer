import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAppMode } from "../../components/AppModeContext";
import { fetchGoldenReviewQueue, fetchGoldenSourceFrame, fetchGoldenWorkspace, saveGoldenAnnotations } from "../api";
import GoldenAnnotationWorkspace from "./GoldenAnnotationWorkspace";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({ fetchGoldenWorkspace: vi.fn(), fetchGoldenReviewQueue: vi.fn(), fetchGoldenSourceFrame: vi.fn(), saveGoldenAnnotations: vi.fn(), importGoldenSource: vi.fn() }));
vi.mock("../../media/IceMediaPlayer", () => ({ IceMediaPlayer: (props: { onStepSourceFrame: (direction: -1 | 1) => void }) => <button onClick={() => props.onStepSourceFrame(1)}>Next source frame</button> }));

const workspace = vi.mocked(fetchGoldenWorkspace);
const review = vi.mocked(fetchGoldenReviewQueue);
const frame = vi.mocked(fetchGoldenSourceFrame);
const save = vi.mocked(saveGoldenAnnotations);

function mockData() {
  vi.mocked(useAppMode).mockReturnValue({ parentPin: "1234" } as never);
  workspace.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 2, sources: [{ source_sha256: "d".repeat(64), duration_pts: 8, width: 1280, height: 720, source_frame_count: 240, display_rotation_degrees: 0, redacted_alias: "source-001" }], events: [], tracks: [], poses: [] });
  review.mockResolvedValue([]); frame.mockResolvedValue({ sourceFrameIndex: 1, pts: .033, duration: .033 });
}

describe("GoldenAnnotationWorkspace", () => {
  it("adds an unsaved event and keeps a source-frame PTS control available", async () => {
    mockData(); render(<GoldenAnnotationWorkspace />);
    await waitFor(() => expect(screen.getByText(/source-001/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Add event/i }));
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(frame).toHaveBeenCalled());
  });

  it("does not claim confirmation after a failed save", async () => {
    mockData(); save.mockRejectedValue(new Error("offline")); render(<GoldenAnnotationWorkspace />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Add event/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Add event/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save confirmed Ground Truth/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Save failed/));
  });
});
