/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `/auth` and the rest of the api are proxied in development so the browser talks to ONE
// origin. Two things depend on that rather than merely benefiting from it. The session cookie
// sets `Secure` unconditionally, and while Chrome and Firefox treat http://localhost as a
// trustworthy origin, a same-origin path avoids the question entirely. And every unsafe method
// is behind an origin check that answers 403 to an origin this deployment does not serve, so a
// cross-origin dev loop would be rejected rather than merely unauthenticated.
const apiOrigin = process.env.SYNCR_API_ORIGIN ?? "http://127.0.0.1:8000";
const proxiedPrefixes = ["/api", "/auth", "/oauth", "/.well-known", "/healthz", "/readyz"];

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
