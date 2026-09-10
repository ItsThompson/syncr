/* The suite's own `test`, with the fixture a file needs and the browser credential a scenario needs.
 *
 * A FILE DECLARES ITS FIXTURE AND GETS A FRESH DATABASE FOR IT:
 *
 *   usingFixture("off_plan_week");
 *
 * WHY A `beforeAll` RATHER THAN A WORKER FIXTURE. The first version made the seed a worker-scoped
 * fixture keyed on a worker option, on the reasoning that Playwright restarts a worker when a
 * worker option's value changes between files. It does, and that is exactly the trap: four files
 * naming the SAME fixture share one worker, so the seed ran once and the first file's solves and
 * approvals were still there when the fourth file made its observations. Measured, in a full run:
 * two cases that pass alone failed together, one reading a solved week it expected to be
 * unsolved and one finding a tradeoff already approved. A `beforeAll` runs once per file, which is
 * the granularity the state actually needs.
 *
 * Not once per TEST, deliberately. Emptying a database, provisioning a tenant, declaring a fixture
 * over HTTP and ticking the maintainer is fifteen seconds, and several scenarios are sequences whose
 * later observations are about what the earlier ones left. A file is the unit of shared state, and
 * `test.describe.configure({ mode: "serial" })` in such a file makes that dependence explicit.
 *
 * THE STACK CLOCK HAS ONE WRITER, AND THE PROJECT THAT MOVED IT PUTS IT BACK. The same reasoning,
 * one level up. `just e2e-clock <offset>` shifts the clock every service reads (the offset
 * `syncr_api.core.clock.utc_now` applies, read nowhere else in the tree) and restarts api and
 * worker. That shift is STACK STATE, not
 * test state: it outlives the file that asked for it, survives a suite restart, and nothing else in
 * the tree sets it. So a FILE may no more shift the clock than it may skip another file's seed:
 * clock-moving scenarios live under `tests/clock/`, which only the `clock` project runs, and that
 * project declares `clock-restore` as its teardown project. The teardown puts the real clock back
 * when the project finishes (success, failure, or a bite mid-file) and then asserts, as a file
 * running after the clock-moving ones, that it sees the real clock. Every other file treats the
 * stack clock as the real one, because by the time it can run, it is.
 */

import { test as base, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

import type { ApiClient } from "../src/api/client.ts";
import { SESSION_COOKIE } from "../src/api/headers.ts";
import { BASE_URL } from "../src/config.ts";
import { loadFixture, type FixturePlanState } from "../src/seed/load.ts";

export type TestFixtures = {
  /** The seeded client, with the browser context carrying the same session. */
  api: ApiClient;
};

/* Set by `usingFixture`'s `beforeAll` and read by the `api` fixture. Module state rather than a
 * fixture because it is the file's state, and a file is what `beforeAll` is scoped to. */
let seeded: ApiClient | null = null;

export const test = base.extend<TestFixtures>({
  api: async ({ context }, provide) => {
    if (!seeded) {
      throw new Error("this file declared no fixture: call usingFixture(<name>) at the top of it");
    }
    // The same credential in the browser, on the origin Caddy serves. `Secure` is set by the api and
    // Chromium accepts a Secure cookie on http://localhost, which is what lets one origin serve both.
    await context.addCookies([
      {
        name: SESSION_COOKIE,
        value: seeded.sessionCookie,
        url: BASE_URL,
        httpOnly: true,
        sameSite: "Lax",
        secure: true,
      },
    ]);
    await provide(seeded);
  },
});

/** Load `name` into a freshly emptied database, once, before this file's scenarios run. */
export const usingFixture = (name: string, planState: FixturePlanState = "solved"): void => {
  test.beforeAll(async () => {
    test.setTimeout(180_000);
    seeded = (await loadFixture(name, planState)).client;
  });
  test.afterAll(() => {
    seeded = null;
  });
};

/** Pin the browser's own clock to `instant`, which is the instant the shifted stack reports.
 *
 * WHY THIS EXISTS AND WHY THE CALLER PASSES THE INSTANT IN: the week grid reads `Date.now()`
 * (`WeekRoute.tsx:60,147,178`) to place the current hour, and the browser's clock is one of the clocks
 * a stack shift does not move: the offset lives in the api and worker processes only. A server-only
 * shift therefore leaves a browser assertion comparing two clocks, which passes whenever both are
 * wrong the same way. Pinning the page to the SAME instant the stack reports makes the two agree by
 * construction rather than by luck; deriving the instant inside the helper would be exactly the kind
 * of second reading that lets them disagree again.
 */
export const pinBrowserClock = async (page: Page, instant: Date | number): Promise<void> => {
  await page.clock.setFixedTime(instant);
};

export { expect };
