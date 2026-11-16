// @ts-expect-error Offline fixture IO; no real browser or network.
import {readFileSync, writeFileSync} from "node:fs";
import {render, screen, fireEvent, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, expect, it, vi} from "vitest";
import {apiClient} from "../api/client";
import TargetSelectionPage from "../pages/TargetSelectionPage";
import {Route, Routes} from "react-router-dom";
vi.mock("./AppModeContext", () => ({useAppMode: () => ({parentPin:"offline-pin", isParentMode:true})}));

// @ts-expect-error Node runtime supplies the mandatory backend GET fixture.
const fixture = process.env.SEGMENT_GET_FIXTURE;
if (!fixture) throw new Error("SEGMENT_GET_FIXTURE is required");
const evidence = JSON.parse(readFileSync(fixture, "utf8"));
const adapter = apiClient.defaults.adapter;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
afterEach(() => {apiClient.defaults.adapter = adapter; vi.restoreAllMocks(); vi.unstubAllGlobals();});

function transport() {
  const bodies: {idempotency_key: string; selection: unknown; preview_digest: string}[] = [];
  let previewFails = false;
  URL.createObjectURL = vi.fn(() => "blob:offline-jpeg"); URL.revokeObjectURL = vi.fn();
  apiClient.defaults.adapter = async config => {
    expect(config.headers.get("X-Parent-Pin")).toBe("offline-pin");
    const url = config.url ?? "";
    let data: unknown = evidence.source_get;
    if (url.endsWith("/preview")) {
      if (previewFails) throw new Error("offline preview failure");
      expect(JSON.parse(config.data)).toEqual(evidence.source_get.observations[0].candidates[0].selection);
      data = evidence.preview;
    } else if (url.endsWith("/confirm")) {
      const body = JSON.parse(config.data); bodies.push(body);
      expect(body.idempotency_key).toMatch(uuid);
      expect(body.confirmation).toBe("confirm_manual_segment_target");
      expect(body.preview_digest).toBe(evidence.preview.preview_digest);
      throw new Error("offline response lost; reuse the exact key on retry");
    } else if (url.includes("/images/")) data = new Blob([new Uint8Array([255,216,255,217])], {type:"image/jpeg"});
    return {data, status:200, statusText:"OK", headers:{}, config};
  };
  return {bodies, failPreview: () => {previewFails = true;}};
}
async function select() {
  render(<MemoryRouter initialEntries={["/report/synthetic-segment/target?reanchor=1"]}><Routes>
    <Route path="/report/:id/target" element={<TargetSelectionPage/>}/>
  </Routes></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("combobox", {name:"失锁段"}).querySelectorAll("option").length).toBeGreaterThan(1));
  fireEvent.change(screen.getByRole("combobox", {name:"失锁段"}), {target:{value:"1"}});
  fireEvent.change(screen.getByRole("combobox", {name:"保存观测"}), {target:{value:"6"}});
  fireEvent.click(screen.getByRole("option", {name:/候选 1/}));
}
async function preview() {
  fireEvent.click(screen.getByRole("button", {name:"预览影响"}));
  await waitFor(() => expect(screen.getByRole("button", {name:"预览影响"})).toBeEnabled());
}
async function confirm() {
  fireEvent.click(screen.getByRole("button", {name:"确认本段目标并处理"}));
  await screen.findByText(/提交未成功/);
}

it.each(["missing", "throwing", "malformed"])("secure fallback for randomUUID %s; retries keep the same payload", async mode => {
  const source = globalThis.crypto;
  const random = vi.fn(source.getRandomValues.bind(source));
  vi.stubGlobal("crypto", {getRandomValues:random, randomUUID:mode === "missing" ? undefined : () => {
    if (mode === "throwing") throw new Error("unsupported context");
    return "bad";
  }});
  const test = transport(); await select(); await preview(); await confirm(); await confirm();
  expect(test.bodies).toHaveLength(2); expect(test.bodies[0]).toEqual(test.bodies[1]);
  await preview(); await confirm();
  expect(test.bodies[2]).toEqual(test.bodies[0]); expect(random).toHaveBeenCalledTimes(1);
  // An actual selection change invalidates the previous confirmation, even when
  // returning to the same original box and its genuine preview digest.
  fireEvent.change(screen.getByRole("combobox", {name:"保存观测"}), {target:{value:"7"}});
  fireEvent.change(screen.getByRole("combobox", {name:"保存观测"}), {target:{value:"6"}});
  fireEvent.click(screen.getByRole("option", {name:/候选 1/}));
  await preview(); await confirm();
  expect(test.bodies[3].idempotency_key).not.toBe(test.bodies[0].idempotency_key);
  expect(random).toHaveBeenCalledTimes(2);
  // @ts-expect-error Evidence destination belongs to the offline Node test runner.
  if (process.env.SEGMENT_KEY_EVIDENCE) writeFileSync(process.env.SEGMENT_KEY_EVIDENCE + "/keys-" + mode + ".json", JSON.stringify(test.bodies, null, 2));
});

it.each(["absent", "throws"])("no usable random source %s never exposes a confirmable preview", async mode => {
  vi.stubGlobal("crypto", mode === "absent" ? undefined : {getRandomValues: () => {throw new Error("entropy unavailable");}});
  const test = transport(); await select(); await preview();
  expect(await screen.findByText(/无法提交：浏览器没有可用的安全随机源/)).toBeInTheDocument();
  expect(screen.queryByRole("button", {name:"确认本段目标并处理"})).toBeNull();
  expect(test.bodies).toHaveLength(0);
});

it("preview failure is distinct from random-source failure", async () => {
  const test = transport(); test.failPreview(); await select(); await preview();
  expect(await screen.findByText(/预览失败：候选证据或版本已改变/)).toBeInTheDocument();
  expect(screen.queryByText(/安全随机源/)).toBeNull();
  expect(screen.queryByRole("button", {name:"确认本段目标并处理"})).toBeNull();
});
