/* The proof of the restore rule: a file running after the clock-moving ones sees the real clock.
 *
 * The `clock` project shifts stack state that outlives each of its files, so nothing any single
 * file could do would settle who restores it. The project settles it: its teardown is this file,
 * which runs after every clock-moving scenario whatever happened to them, puts the real clock
 * back through the same recipe that moved it, and then makes the claim the rule exists for as an
 * observation rather than a promise. The next suite to touch this stack starts from the clock it
 * actually has.
 */

import { expect, test } from "../harness.ts";
import { setStackClock, stackInstant } from "../../src/harness/clock.ts";

test.describe.configure({ mode: "serial" });

test.setTimeout(240_000);

test("after the clock project restores, both processes report the real instant", async () => {
  const opened = Date.now();
  await setStackClock("PT0S");

  // A still-shifted container fails the upper bound, so the poll waits out the recreation
  // instead of reading whichever process answered first.
  for (const service of ["api", "worker"] as const) {
    await expect
      .poll(
        async () => {
          const instant = await stackInstant(service);
          return instant.getTime() >= opened && instant.getTime() <= Date.now();
        },
        { timeout: 120_000 },
      )
      .toBe(true);
  }
});
