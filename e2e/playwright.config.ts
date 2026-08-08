import { defineConfig, devices } from "@playwright/test";

import { BASE_URL } from "./src/config.ts";

/* The suite runs against the Compose stack `just e2e-up` brings up. It does not start one itself, and
 * that is deliberate: a `webServer` block would make every run pay for a build and would hide which
 * of the two things failed when a run went red.
 *
 * ONE WORKER, ALWAYS. Every scenario drives ONE tenant in ONE database, because that is what an
 * end-to-end stack is; two workers would seed over each other's fixtures. Files are therefore
 * serialized, and a file's scenarios share the fixture its `beforeAll` loaded.
 *
 * NO RETRIES, INCLUDING IN CI. A scenario that passes on a second attempt is a scenario nobody can
 * read a result from, and every wait in the harness polls the state it is about rather than sleeping,
 * so a timeout here means the state never arrived.
 */
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  /* Seeding a fixture empties a database, provisions a tenant, declares a week over HTTP and ticks the
   * maintainer, and a scenario may then solve and wait for the worker. Two minutes is what that costs
   * on a cold container plus room for the polls; it is a ceiling, not a budget. */
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
