import { defineConfig, devices } from "@playwright/test";

import { BASE_URL } from "./src/config.ts";

/* The suite runs against the Compose stack `just e2e-up` brings up. It does not start one itself, and
 * that is deliberate: a `webServer` block would make every run pay for a build and would hide which
 * of the two things failed when a run went red.
 *
 * ONE WORKER, ALWAYS. Every scenario drives ONE tenant in ONE database, because that is what an
 * end-to-end stack is; two workers would seed over each other's fixtures. Files are therefore
 * serialized, and a file's scenarios share the fixture its `beforeAll` loaded. One worker also
 * serializes ACROSS projects, so the `clock` project below cannot interleave with a file that
 * expects the real clock.
 *
 * NO RETRIES, INCLUDING IN CI. A scenario that passes on a second attempt is a scenario nobody can
 * read a result from, and every wait in the harness polls the state it is about rather than sleeping,
 * so a timeout here means the state never arrived.
 *
 * THE CLOCK PROJECTS. Scenarios that move the stack's clock live under `tests/clock/` and run only
 * in the `clock` project, because a shift is stack state that outlives the file that asked for it;
 * the rule and its owner are stated in `tests/harness.ts` beside the seeding rule it resembles. The
 * project's teardown is the `clock-restore` project, whose single file puts the real clock back when
 * the project finishes and asserts it sees it. The default project ignores those directories, so an
 * ordinary run never meets a shifted clock: they run after every chromium file, and restore before
 * the process exits.
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
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      // A file outside the two directories below never sees a shifted clock: the shift happens
      // only inside the `clock` project and is undone by its teardown before anything else runs.
      testIgnore: [/\/clock\//, /\/clock-restore\//],
    },
    {
      name: "clock",
      testMatch: /\/clock\/[^/]+\.spec\.ts/,
      teardown: "clock-restore",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "clock-restore",
      testMatch: /\/clock-restore\/[^/]+\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
