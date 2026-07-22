import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { vi } from "vitest";

afterEach(() => cleanup());

Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  configurable: true,
  value: vi.fn((_contextType: string) => {
    const ctx: Record<string, unknown> = {};
    const handler: ProxyHandler<Record<string, unknown>> = {
      get(_target, prop) {
        if (prop === "canvas") return ({ width: 1080, height: 1350 });
        if (prop === "createLinearGradient" || prop === "createRadialGradient") {
          return vi.fn(() => ({ addColorStop: vi.fn() }));
        }
        if (prop === "measureText") {
          return vi.fn((_text: string) => ({ width: 100, actualBoundingBoxAscent: 20, actualBoundingBoxDescent: 5 }));
        }
        if (typeof ctx[prop as string] !== "undefined") return ctx[prop as string];
        const fn = vi.fn();
        ctx[prop as string] = fn;
        return fn;
      },
      set(_target, prop, value) {
        ctx[prop as string] = value;
        return true;
      },
    };
    return new Proxy(ctx, handler);
  }),
});

Object.defineProperty(HTMLCanvasElement.prototype, "toBlob", {
  configurable: true,
  value: vi.fn(function (this: HTMLCanvasElement, callback: (blob: Blob) => void, type = "image/png") {
    callback(new Blob(["fake"], { type }));
  }),
});

Object.defineProperty(HTMLMediaElement.prototype, "play", {
  configurable: true,
  value: vi.fn(() => Promise.resolve()),
});
