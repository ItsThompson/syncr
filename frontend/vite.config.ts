/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `/api` and the health endpoints are proxied in development so the browser talks to one
// origin and the client's `credentials: include` behaves as it will in the Compose stack,
// where Caddy serves the build and forwards to the api.
const apiOrigin = process.env.SYNCR_API_ORIGIN ?? "http://127.0.0.1:8000";
const proxiedPrefixes = ["/api", "/oauth", "/.well-known", "/healthz", "/readyz"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      proxiedPrefixes.map((prefix) => [prefix, { target: apiOrigin, changeOrigin: true }]),
    ),
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/testing/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}", "scripts/**/*.ts"],
      exclude: ["src/api/schema.d.ts", "src/testing/**", "**/__fixtures__/**", "**/*.test.*"],
    },
  },
});
