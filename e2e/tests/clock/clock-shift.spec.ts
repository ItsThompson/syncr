/* The clock seam's own demonstration, run by the `clock` project alone.
 *
 * Everything a clock-moving scenario will build on is asserted here once, at the seam rather than
 * inside any one scenario's subject:
 *
 * - the shift reaches BOTH processes that hold readers. Asserted against the running containers,
 *   not against the compose configuration: an `exec` asks the process that has been up since the
 *   restart, where a one-shot would boot a fresh process from today's files and answer for a
 *   stack the running one had never become.
 * - the browser can be pinned to the same instant, so a scenario's assertions compare ONE clock
 *   read twice instead of two clocks.
 *
 * The shift is stack state and outlives this file on purpose; putting it back is nobody here's
 * job. The rule and its owner are stated in `harness.ts`, and the restore project asserts the
 * outcome on its way out.
 */

import { expect, pinBrowserClock, test } from "../harness.ts";
import { stackInstant, setStackClock } from "../../src/harness/clock.ts";
import { BASE_URL } from "../../src/config.ts";

/* Long enough that no reading of it could be confused with a drift of the wall clock during a
 * run, and spelled the way `syncr_api.core.clock` reads durations. */
const SHIFT = "P3D";
const SHIFT_MS = 3 * 24 * 60 * 60 * 1000;

test.describe.configure({ mode: "serial" });

/* Recreating two containers takes longer than the default ceiling allows; the shift itself is
 * what costs, and every wait here polls the state it is about rather than sleeping. */
test.setTimeout(240_000);

test("a shifted stack reports the shifted instant in both processes, and the pinned browser reads the same one", async ({
  page,
}) => {
  const opened = Date.now();
  await setStackClock(SHIFT);

  // The lower bound is fixed: the process was restarted after `opened`, so its clock can only
  // clear `opened + SHIFT` if its offset moved. The upper bound is re-read each poll, because
  // the wall clock advances while the containers come back.
  for (const service of ["api", "worker"] as const) {
    await expect
      .poll(async () => (await stackInstant(service)).getTime() >= opened + SHIFT_MS, {
        timeout: 120_000,
      })
      .toBe(true);
    const reported = await stackInstant(service);
    expect(reported.getTime()).toBeLessThanOrEqual(Date.now() + SHIFT_MS);
  }

  // The same instant the stack now reports, handed to the helper rather than derived there.
  const shared = await stackInstant("api");
  await page.goto(BASE_URL);
  await pinBrowserClock(page, shared);

  expect(await page.evaluate(() => Date.now())).toBe(shared.getTime());
});
