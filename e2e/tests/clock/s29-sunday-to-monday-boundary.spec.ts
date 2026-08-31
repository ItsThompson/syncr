/* S29: the clock crosses a Sunday-to-Monday boundary.
 *
 * Two observations, in one case:
 *
 * 1. The newly covered week acquires a plan with no user action, observed as a live plan appearing.
 *    The clock moves from inside one ISO week to inside the next, the rolling horizon advances, and
 *    the maintainer materializes the week that just entered it -- no solve, no pin, no read asked for.
 *
 * 2. A frame span crossing the boundary is emitted exactly ONCE across the two-week horizon,
 *    asserted as a COUNT rather than a presence, because the count is the figure that can vary.
 *    A boundary-crossing Sleep occurrence belongs to the week its START falls in (the overhang
 *    module states the rule), so it appears in one week's plan and not in the other's. The case
 *    reddens if the span is emitted twice (once in each week) or not at all.
 *
 * THE DST_WEEKS FIXTURE supplies the frame span: Sleep at 23:00 for 8 hours every night, so every
 * Sunday night's occurrence crosses the ISO week boundary. The fixture's own boundary assertions
 * (in the domain suite) are not touched.
 *
 * THIS FILE LIVES UNDER tests/clock/ because it moves the stack clock, which is stack state that
 * outlives the file. The clock project's teardown puts the real clock back. A beforeAll resets the
 * clock to PT0S before the fixture loads, so the initial materialization is against the real clock
 * and the only shift is the one this case makes.
 */

import { expect, test, usingFixture } from "../harness.ts";
import { setStackClock, stackInstant } from "../../src/harness/clock.ts";
import { tickHorizon } from "../../src/harness/compose.ts";
import {
  civilDateIn,
  instantAt,
  isoWeekOf,
  isoWeekShift,
  mondayOf,
  type IsoWeekId,
} from "../../src/api/weeks.ts";
import { HOME_ZONE } from "../../src/config.ts";
import { weekView } from "../../src/harness/week.ts";
import type { Block } from "../../src/api/schemas.ts";

/* Reset the clock to the real instant before the fixture loads, so the initial horizon is the real
 * one and the only shift is the one this case makes. The clock-shift case above may have left the
 * stack shifted; the clock-restore teardown puts it back after every clock file finishes, but a
 * file running between them would see the shifted stack. */
test.beforeAll(async () => {
  test.setTimeout(240_000);
  await setStackClock("PT0S");
});

usingFixture("dst_weeks");

test.describe.configure({ mode: "serial" });
test.setTimeout(300_000);

/** Does this block's interval cross an ISO week boundary, read in the tenant's home zone?
 *
 * A frame span like Sleep 23:00 + 8h crosses midnight every night, but only on Sunday night does it
 * cross from one ISO week into the next. The check is on the civil dates in the home zone, not on
 * the raw instants, because a UTC midnight and a London midnight are different dates in summer. */
const crossesWeekBoundary = (block: Block): boolean => {
  const startDate = civilDateIn(HOME_ZONE, new Date(block.interval.start));
  const endDate = civilDateIn(HOME_ZONE, new Date(block.interval.end));
  return isoWeekOf(startDate) !== isoWeekOf(endDate);
};

test("S29 the clock crosses a Sunday-to-Monday boundary; the newly covered week acquires a plan, and a frame span crossing the boundary is emitted exactly once", async ({
  api,
}) => {
  // 1. Read the real stack instant (the beforeAll reset it to PT0S).
  const stackNow = await stackInstant("api");
  const civilNow = civilDateIn(HOME_ZONE, stackNow);
  const currentWeek = isoWeekOf(civilNow);

  // 2. Before the shift, record which weeks hold a live plan. The initial tick materialized every
  //    week inside the real horizon; a week beyond it holds none.
  const hadPlan = new Set<string>();
  for (let i = 0; i < 5; i++) {
    const week = isoWeekShift(currentWeek, i);
    const view = await weekView(api, week);
    if (view.live !== null) hadPlan.add(week);
  }

  // 3. Compute the offset to the Monday that opens the next ISO week, one minute past midnight.
  //    Monday 00:01 is one minute past the Sunday-to-Monday boundary, so the shift always crosses it.
  const nextWeek = isoWeekShift(currentWeek, 1);
  const nextMonday = mondayOf(nextWeek);
  const targetInstant = instantAt(nextMonday, "00:01:00", HOME_ZONE);
  const offsetMs = Date.parse(targetInstant) - stackNow.getTime();
  const totalSeconds = Math.max(60, Math.floor(offsetMs / 1000));
  const offset = `PT${totalSeconds}S`;

  // 4. Shift the clock. The recipe restarts api and worker and blocks until they are healthy.
  const opened = Date.now();
  await setStackClock(offset);

  // The containers report the shifted instant once they are back; poll until they do. The lower
  // bound is the wall time the shift started at plus the offset, and the upper bound is re-read
  // each poll because the wall clock advances while the containers come back.
  await expect
    .poll(async () => (await stackInstant("api")).getTime() >= opened + offsetMs, {
      timeout: 120_000,
    })
    .toBe(true);

  // 5. Tick the horizon maintainer. The one-shot runs two iterations: the first sets the runner's
  //    due time and the second plans every week inside the shifted horizon.
  await tickHorizon();

  // 6. Compute the shifted week and find the weeks that newly hold a plan.
  const shifted = await stackInstant("api");
  const shiftedCivil = civilDateIn(HOME_ZONE, shifted);
  const shiftedWeek = isoWeekOf(shiftedCivil);

  let newlyCovered = 0;
  for (let i = 0; i < 5; i++) {
    const week = isoWeekShift(shiftedWeek, i);
    const view = await weekView(api, week);
    if (view.live !== null && !hadPlan.has(week)) {
      newlyCovered++;
      // The plan holds blocks: the frame materialized, which is what "a live plan appearing" means.
      expect(view.live.blocks.length, `${week} acquired a plan holding no blocks`).toBeGreaterThan(
        0,
      );
      expect(view.emptyWeek, `${week} reports an empty week despite holding a plan`).toBeNull();
    }
  }
  expect(newlyCovered, "no newly covered week acquired a plan with no user action").toBeGreaterThan(
    0,
  );

  // 7. Count frame spans crossing the boundary across the two-week horizon. After a shift to Monday
  //    00:01, the 14-day horizon covers exactly two whole ISO weeks: the shifted week and the one
  //    after it. The Sunday night between them has one Sleep occurrence that crosses the boundary.
  //
  //    The count is the figure that can vary: 0 if the span is not emitted, 2 if it is emitted in
  //    both weeks. The overhang module's rule -- a boundary-crossing occurrence belongs to the week
  //    its START falls in, and the week it runs into carries the time as occupancy rather than as a
  //    block -- is what makes it 1.
  const horizonWeeks: IsoWeekId[] = [shiftedWeek, isoWeekShift(shiftedWeek, 1)];
  let crossingCount = 0;
  for (const week of horizonWeeks) {
    const view = await weekView(api, week);
    if (!view.live) continue;
    for (const block of view.live.blocks) {
      if (block.origin === "frame" && crossesWeekBoundary(block)) {
        crossingCount++;
      }
    }
  }

  expect(
    crossingCount,
    `expected exactly 1 frame span crossing the boundary across ${horizonWeeks.join(" and ")}, ` +
      `got ${crossingCount} (0 = not emitted, 2 = emitted in both weeks)`,
  ).toBe(1);
});
