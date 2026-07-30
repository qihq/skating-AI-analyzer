import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { useAppMode } from "../../components/AppModeContext";
import { fetchGoldenReviewQueue, fetchGoldenSourceFrame, fetchGoldenSourceMediaUrl, fetchGoldenWorkspace, saveGoldenAnnotations } from "../api";
import GoldenAnnotationWorkspace from "./GoldenAnnotationWorkspace";

vi.mock("../../components/AppModeContext", () => ({ useAppMode: vi.fn() }));
vi.mock("../api", () => ({ fetchGoldenWorkspace: vi.fn(), fetchGoldenReviewQueue: vi.fn(), fetchGoldenSourceFrame: vi.fn(), fetchGoldenSourceMediaUrl: vi.fn(), saveGoldenAnnotations: vi.fn(), importGoldenSource: vi.fn(), attestGoldenReview: vi.fn() }));
vi.mock("../../media/IceMediaPlayer", () => ({ IceMediaPlayer: (props: { onStepSourceFrame: (direction: -1 | 1) => void }) => <button onClick={() => props.onStepSourceFrame(1)}>Next source frame</button> }));

const workspace = vi.mocked(fetchGoldenWorkspace);
const review = vi.mocked(fetchGoldenReviewQueue);
const frame = vi.mocked(fetchGoldenSourceFrame);
const save = vi.mocked(saveGoldenAnnotations);

function mockData() {
  vi.clearAllMocks();
  vi.mocked(useAppMode).mockReturnValue({ parentPin: "1234" } as never);
  workspace.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 2, sources: [{ source_sha256: "d".repeat(64), duration_pts: 8, width: 1280, height: 720, source_frame_count: 240, display_rotation_degrees: 0, redacted_alias: "source-001" }], events: [], tracks: [], poses: [] });
  review.mockResolvedValue([]); frame.mockResolvedValue({ sourceFrameIndex: 1, pts: .033, duration: .033 }); vi.mocked(fetchGoldenSourceMediaUrl).mockResolvedValue("blob:private-video");
}

describe("GoldenAnnotationWorkspace", () => {
  it("adds an unsaved event and keeps a source-frame PTS control available", async () => {
    mockData(); render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/source-001/)).toBeInTheDocument());
    const nextFrame = await screen.findByRole("button", { name: "Next source frame" });
    fireEvent.click(screen.getByRole("button", { name: /Add event/i }));
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    fireEvent.click(nextFrame);
    await waitFor(() => expect(frame).toHaveBeenCalled());
  });

  it("does not claim confirmation after a failed save", async () => {
    mockData(); save.mockRejectedValue(new Error("offline")); render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: /Add event/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Add event/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save confirmed Ground Truth/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Save failed/));
  });

  it("captures a jump moment from the exact returned source frame and sends it as Ground Truth", async () => {
    mockData(); save.mockResolvedValue({ dataset_id: "golden-v2-private-catalog", revision: 3, sources: [], events: [], tracks: [], poses: [] });
    render(<MemoryRouter><GoldenAnnotationWorkspace /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("button", { name: /Add event/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Add event/i }));
    fireEvent.change(screen.getByLabelText("Profile"), { target: { value: "jump" } });
    await waitFor(() => expect(screen.getByText("Jump details")).toBeInTheDocument());
    fireEvent.click(await screen.findByRole("button", { name: "Next source frame" }));
    await waitFor(() => expect(frame).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/Exact source time: 0\.033000 seconds/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Use current frame and PTS/i })).toHaveLength(3));
    fireEvent.click(screen.getAllByRole("button", { name: /Use current frame and PTS/i })[0]);
    await waitFor(() => expect(screen.getByText(/Takeoff: 0\.033000s \/ frame 1/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Save confirmed Ground Truth/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const payload = save.mock.calls[save.mock.calls.length - 1][1];
    expect(payload.events[0]).toMatchObject({ jump: { takeoff: { pts: .033, source_frame_index: 1 } } });
  });
});
