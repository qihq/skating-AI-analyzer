import axios, { type AxiosError } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { uploadAnalysis } from "./client";

type UploadProgressEventLike = {
  lengthComputable: boolean;
  loaded: number;
  total: number;
};

/**
 * Minimal controlled XMLHttpRequest double. `uploadAnalysis` drives it
 * synchronously (open/configure/send) and the test decides when onload,
 * onerror or ontimeout fires, so every branch can be exercised deterministically.
 */
class FakeXMLHttpRequest {
  static instances: FakeXMLHttpRequest[] = [];

  method = "";
  url = "";
  isAsync = true;
  timeout = 0;
  withCredentials = false;
  responseType = "";
  status = 0;
  statusText = "";
  response: unknown = null;
  rawText = "";
  sentBody: unknown = null;
  aborted = false;
  upload: { onprogress: ((event: UploadProgressEventLike) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ontimeout: (() => void) | null = null;

  constructor() {
    FakeXMLHttpRequest.instances.push(this);
  }

  open(method: string, url: string, isAsync = true) {
    this.method = method;
    this.url = url;
    this.isAsync = isAsync;
  }

  send(body: unknown) {
    this.sentBody = body;
  }

  abort() {
    this.aborted = true;
  }

  get responseText(): string {
    if (this.responseType !== "" && this.responseType !== "text") {
      // Mirrors the browser InvalidStateError for responseType "json": the old
      // uploadAnalysis fallback read this property and left the promise pending.
      throw new DOMException("responseText is only accessible when responseType is '' or 'text'", "InvalidStateError");
    }
    return this.rawText;
  }
}

function currentRequest(): FakeXMLHttpRequest {
  const request = FakeXMLHttpRequest.instances[FakeXMLHttpRequest.instances.length - 1];
  if (!request) {
    throw new Error("uploadAnalysis did not open an XMLHttpRequest");
  }
  return request;
}

function completeRequest(status: number, response: unknown, rawText = ""): FakeXMLHttpRequest {
  const request = currentRequest();
  request.status = status;
  request.response = response;
  request.rawText = rawText;
  request.onload?.();
  return request;
}

async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  return promise.then(
    () => {
      throw new Error("expected uploadAnalysis to reject");
    },
    (error: unknown) => error,
  );
}

function asAxiosError(error: unknown): AxiosError {
  expect(axios.isAxiosError(error)).toBe(true);
  if (!axios.isAxiosError(error)) {
    throw new Error("expected an AxiosError");
  }
  return error;
}

describe("uploadAnalysis XHR error contract", () => {
  beforeEach(() => {
    FakeXMLHttpRequest.instances = [];
    vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves a 202 JSON response and reports upload progress", async () => {
    const formData = new FormData();
    formData.append("file", new File(["x"], "run.mp4", { type: "video/mp4" }));
    const onProgress = vi.fn();

    const promise = uploadAnalysis(formData, { onProgress });
    const request = currentRequest();

    expect(request.method).toBe("POST");
    expect(request.url).toBe("/api/analysis/upload");
    expect(request.responseType).toBe("json");
    expect(request.timeout).toBe(600000);
    expect(request.sentBody).toBe(formData);

    request.upload.onprogress?.({ lengthComputable: false, loaded: 0, total: 0 });
    expect(onProgress).not.toHaveBeenCalled();

    request.upload.onprogress?.({ lengthComputable: true, loaded: 512, total: 1024 });
    expect(onProgress).toHaveBeenCalledWith({ loaded: 512, total: 1024, percent: 50 });

    completeRequest(202, { id: "analysis-1", status: "processing" });
    await expect(promise).resolves.toEqual({ id: "analysis-1", status: "processing" });
  });

  it("rejects a 400 structured detail as a real AxiosError that keeps status and data", async () => {
    const promise = uploadAnalysis(new FormData());
    const detail = { code: "VIDEO_FORMAT_INVALID", message: "仅支持 mp4 / mov / avi" };
    completeRequest(400, { detail });

    const error = asAxiosError(await rejectionOf(promise));
    expect(error.response?.status).toBe(400);
    expect(error.response?.data).toEqual({ detail });
    expect((error as AxiosError & { status?: number }).status).toBe(400);
    expect(error.code).toBe("ERR_BAD_REQUEST");
  });

  it("rejects a 409 string detail without losing the message", async () => {
    const promise = uploadAnalysis(new FormData());
    completeRequest(409, { detail: "同一视频正在处理中，请勿重复提交。" });

    const error = asAxiosError(await rejectionOf(promise));
    expect(error.response?.status).toBe(409);
    expect((error.response?.data as { detail?: string }).detail).toBe("同一视频正在处理中，请勿重复提交。");
  });

  it("rejects a non-JSON error body even though responseText throws in json mode", async () => {
    const promise = uploadAnalysis(new FormData());
    const request = completeRequest(502, null);

    expect(() => request.responseText).toThrow(DOMException);

    const error = asAxiosError(await rejectionOf(promise));
    expect(error.response?.status).toBe(502);
    expect(error.response?.data).toBeNull();
  });

  it("rejects a 202 with an unreadable body instead of resolving a fake success", async () => {
    const promise = uploadAnalysis(new FormData());
    completeRequest(202, null);

    const error = asAxiosError(await rejectionOf(promise));
    expect(error.response?.status).toBe(202);
    expect(error.response?.data).toBeNull();
    expect(error.code).toBe("ERR_BAD_RESPONSE");
  });

  it("rejects a 2xx JSON body that is not an upload response", async () => {
    const promise = uploadAnalysis(new FormData());
    completeRequest(200, { message: "ok" });

    const error = asAxiosError(await rejectionOf(promise));
    expect(error.response?.status).toBe(200);
    expect(error.response?.data).toEqual({ message: "ok" });
  });

  it.each([{ id: "analysis-1" }, { id: " ", status: "pending" }])("rejects an incomplete 2xx upload response: %j", async (body) => {
    const promise = uploadAnalysis(new FormData());
    completeRequest(202, body);
    expect(asAxiosError(await rejectionOf(promise)).code).toBe("ERR_BAD_RESPONSE");
  });

  it("rejects network failures with ERR_NETWORK", async () => {
    const promise = uploadAnalysis(new FormData());
    currentRequest().onerror?.();

    const error = asAxiosError(await rejectionOf(promise));
    expect(error.code).toBe("ERR_NETWORK");
    expect(error.message).toBe("Network Error");
    expect(error.response).toBeUndefined();
  });

  it("rejects timeouts with ECONNABORTED", async () => {
    const promise = uploadAnalysis(new FormData());
    currentRequest().ontimeout?.();

    const error = asAxiosError(await rejectionOf(promise));
    expect(error.code).toBe("ECONNABORTED");
    expect(error.message).toBe("Timeout");
    expect(error.response).toBeUndefined();
  });

  it("keeps abort semantics: aborting the signal rejects with AbortError", async () => {
    const controller = new AbortController();
    const promise = uploadAnalysis(new FormData(), { signal: controller.signal });
    const request = currentRequest();

    controller.abort();

    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    expect(request.aborted).toBe(true);
  });

  it("keeps abort semantics for an already aborted signal", async () => {
    const controller = new AbortController();
    controller.abort();

    const promise = uploadAnalysis(new FormData(), { signal: controller.signal });

    await expect(promise).rejects.toBeInstanceOf(DOMException);
    expect(currentRequest().aborted).toBe(true);
  });
});
