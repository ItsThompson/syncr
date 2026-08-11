/* The probe's own config, so the probe never joins the committed suite.
 *
 * The suite's include is `src/**` and `scripts/**`; this file's is this directory only, and it is run explicitly:
 *
 *   npx vite build && npx vitest run --config probe/vitest.config.mts
 *
 * The root stays the frontend, so the plugin chain, the aliases and the tsconfig are the application's own. The
 * timeouts are generous because one case builds a page, spawns Chrome and waits for a virtual time budget.
 */

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  test: {
    include: ["probe/**/*.probe.test.tsx"],
    testTimeout: 120000,
    hookTimeout: 120000,
  },
});
