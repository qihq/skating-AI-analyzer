// @ts-expect-error Offline Node fixture reader; no browser or model execution.
import {readFileSync} from "node:fs";
import {render, screen, fireEvent, waitFor} from "@testing-library/react";
import {MemoryRouter, Routes, Route, useSearchParams, useLocation} from "react-router-dom";
import {it, expect, vi, afterEach} from "vitest";
import {apiClient} from "../api/client";
import TargetSelectionPage from "../pages/TargetSelectionPage";
import {SegmentRevisionChooser, SegmentRevisionReplay} from "./SegmentReanchor";
vi.mock("./AppModeContext", () => ({useAppMode: () => ({parentPin: "offline-pin", isParentMode: true})}));
// @ts-expect-error Test runner provides process; fixture is mandatory, never skipped.
const fixturePath = process.env.SEGMENT_GET_FIXTURE;
if (!fixturePath) throw new Error("SEGMENT_GET_FIXTURE must name actual backend GET evidence");
const evidence = JSON.parse(readFileSync(fixturePath, "utf8"));
const adapter = apiClient.defaults.adapter;
afterEach(() => {apiClient.defaults.adapter = adapter; vi.restoreAllMocks();});
function Detail() {
  const [p] = useSearchParams(); const location=useLocation();
  return <><output aria-label="位置">{location.search}</output><SegmentRevisionChooser id="synthetic-segment"/>
    {p.has("aux") ? <SegmentRevisionReplay key={p.get("aux")} id="synthetic-segment" revision={Number(p.get("aux"))}/> : <p>原自动结果保留</p>}</>;
}
it("consumes actual saved GET through user entry, confirmation, status, canvas and revision switching", async () => {
  const requests: string[]=[]; let confirmed=false; let reads=0;
  vi.stubGlobal("URL", URL);
  URL.createObjectURL=vi.fn(() => "blob:offline-saved-jpeg"); URL.revokeObjectURL=vi.fn();
  apiClient.defaults.adapter=async config => {
    expect(config.headers.get("X-Parent-Pin")).toBe("offline-pin");
    const url=config.url ?? ""; requests.push(config.method+" "+url);
    let data: unknown;
    if (url.endsWith("/preview")) {
      expect(JSON.parse(config.data)).toEqual(evidence.source_get.observations[0].candidates[0].selection);
      data=evidence.preview;
    } else if (url.endsWith("/confirm")) {
      const payload=JSON.parse(config.data); expect(payload.preview_digest).toBe(evidence.preview.preview_digest);
      expect(payload.confirmation).toBe("confirm_manual_segment_target"); confirmed=true; data=evidence.submitted;
    } else if (url.includes("/images/")) {
      const name=url.split("/images/")[1]?.split("?")[0];
      const bytes=atob(evidence.image_bytes[name] ?? Object.values(evidence.image_bytes)[0] as string);
      data=new Blob([Uint8Array.from(bytes,c=>c.charCodeAt(0))],{type:"image/jpeg"});
    }
    else if (url.endsWith("/pose")) data=evidence.pose;
    else if (url.endsWith("/revisions/1")) {
      reads++; data=reads===1 ? {...evidence.detail,status:"processing"} : evidence.detail;
    } else data=confirmed ? {...evidence.source_get,current_revision:1,revisions:[evidence.detail]} : evidence.source_get;
    return {data,status:200,statusText:"OK",headers:{},config};
  };
  const view=render(<MemoryRouter initialEntries={["/report/synthetic-segment/target?reanchor=1"]}><Routes>
    <Route path="/report/:id/target" element={<TargetSelectionPage/>}/><Route path="/analysis/:id" element={<Detail/>}/>
  </Routes></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("combobox",{name:"失锁段"}).querySelectorAll("option").length).toBeGreaterThan(1));
  fireEvent.change(screen.getByRole("combobox",{name:"失锁段"}),{target:{value:"1"}});
  fireEvent.change(screen.getByRole("combobox",{name:"保存观测"}),{target:{value:"6"}});
  fireEvent.click(screen.getByRole("option",{name:/候选 1/}));
  fireEvent.click(screen.getByRole("button",{name:"预览影响"}));
  fireEvent.click(await screen.findByRole("button",{name:"确认本段目标并处理"}));
  expect(await screen.findByText("处理中")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("姿态证据图例")).toBeInTheDocument(),{timeout:4000});
  expect(view.container.querySelector("canvas")).toBeTruthy();
  expect(view.container.querySelector('input[type="range"]')).toBeTruthy();
  expect(view.container.querySelector("video")).toBeNull();
  const slider=view.container.querySelector('input[type="range"]')!;
  fireEvent.change(slider,{target:{value:"4"}}); expect(slider).toHaveValue("4");
  fireEvent.change(screen.getByRole("combobox",{name:"结果版本"}),{target:{value:"automatic"}});
  expect(screen.getByText("原自动结果保留")).toBeInTheDocument(); expect(screen.getByLabelText("位置")).toHaveTextContent("");
  expect(view.container.querySelector("canvas")).toBeNull();
  fireEvent.change(screen.getByRole("combobox",{name:"结果版本"}),{target:{value:"1"}});
  await waitFor(() => expect(view.container.querySelector('input[type="range"]')).toHaveValue("0"));
  expect(requests.filter(r=>r.startsWith("post"))).toHaveLength(2);
  expect(requests.some(r=>r.includes("saved_only=true"))).toBe(true);
});
