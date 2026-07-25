import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";

function scopeAnimalIslandStyles() {
  return {
    name: "scope-animal-island-styles",
    enforce: "pre" as const,
    transform(code: string, id: string) {
      if (!id.includes("animal-island-ui") || !id.endsWith("index.css")) return null;
      return code
        .replace(":root{", '.modern-island-shell,[class^="animal-"],[class*=" animal-"]{')
        .replace("*,*:before,*:after{box-sizing:border-box}", ".modern-island-shell *,.modern-island-shell *:before,.modern-island-shell *:after{box-sizing:border-box}");
    },
  };
}

export default defineConfig({
  plugins: [scopeAnimalIslandStyles(), react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    server: { deps: { inline: ["animal-island-ui"] } },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
});
