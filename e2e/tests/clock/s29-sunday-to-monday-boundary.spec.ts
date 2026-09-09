/* S29: the clock crosses a Sunday-to-Monday boundary.
 *
 * Two observations, in one case:
 *
 * 1. The newly covered week acquires a plan with no user action, observed as a live plan appearing.
 *    The clock moves to the first Monday boundary that advances the rolling horizon, and
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
import { signIn } from "../../src/api/client.ts";
import { setStackClock, stackInstant } from "../../src/harness/clock.ts";
import { tickHorizon } from "../../src/harness/compose.ts";
import {
  civilDateIn,
  dateShift,
  instantAt,
  isoWeekOf,
  isoWeekShift,
  mondayOf,
  type IsoWeekId,
} from "../../src/api/weeks.ts";
import { E2E_EMAIL, E2E_PASSWORD, HOME_ZONE } from "../../src/config.ts";
import { awaitLivePlan, weekView } from "../../src/harness/week.ts";
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

/** Return the ISO week for an instant as read in the tenant's home zone. */
const weekOfInstant = (instant: string): IsoWeekId =>
  isoWeekOf(civilDateIn(HOME_ZONE, new Date(instant)));

const crossesBoundaryBetween = (block: Block, startWeek: IsoWeekId, endWeek: IsoWeekId): boolean =>
  block.origin === "frame" &&
  weekOfInstant(block.interval.start) === startWeek &&
  weekOfInstant(block.interval.end) === endWeek;

test("S29 the clock crosses a Sunday-to-Monday boundary; the newly covered week acquires a plan, and a frame span crossing the boundary is emitted exactly once", async ({
  api,
}) => {
  // 1. Read the real stack instant (the beforeAll reset it to PT0S).
  const stackNow = await stackInstant("api");
  const civilNow = civilDateIn(HOME_ZONE, stackNow);
  const currentWeek = isoWeekOf(civilNow);

  // 2. Choose the first Monday that moves exactly one new ISO week into the horizon. If today is
  //    Monday, next Monday leaves the following week new. On every other weekday, the following
  //    Monday would leave no new week, so use the Monday after it. Both targets are deterministic
  //    Monday boundaries, and the selected entering week is outside today's 14-day date set.
  const targetWeekOffset = civilNow === mondayOf(currentWeek) ? 1 : 2;
  const shiftedWeek = isoWeekShift(currentWeek, targetWeekOffset);
  const followingWeek = isoWeekShift(shiftedWeek, 1);
  const currentHorizonWeeks = new Set(
    Array.from({ length: 14 }, (_, dayOffset) => isoWeekOf(dateShift(civilNow, dayOffset))),
  );
  expect(currentHorizonWeeks.has(followingWeek)).toBe(false);
  const beforeShift = await weekView(api, followingWeek);
  expect(beforeShift.live, `${followingWeek} was already planned before the shift`).toBeNull();
  expect(beforeShift.emptyReason).toBe("outside_horizon");

  // 3. Land one minute after Monday midnight. The local boundary is crossed while the exact entering
  //    week remains known before the shift.
  const targetInstant = instantAt(mondayOf(shiftedWeek), "00:01:00", HOME_ZONE);
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
  const shifted = await stackInstant("api");
  const shiftedDate = civilDateIn(HOME_ZONE, shifted);
  expect(shiftedDate).toBe(mondayOf(shiftedWeek));
  expect(isoWeekOf(shiftedDate)).toBe(shiftedWeek);

  // The original session was issued before the shift and can expire under the shifted clock. Sign in
  // again after the shift so a session-expiry response cannot hide the plan assertion.
  const shiftedApi = await signIn(api.baseUrl, E2E_EMAIL, E2E_PASSWORD);

  // 6. Read both complete plans in the shifted two-week horizon. Missing either plan is a setup
  //    failure, not an empty contribution to the count.
  const owningView = await awaitLivePlan(shiftedApi, shiftedWeek);
  const followingView = await awaitLivePlan(shiftedApi, followingWeek);
  expect(owningView.live, `${shiftedWeek} did not acquire a live plan`).not.toBeNull();
  expect(followingView.live, `${followingWeek} did not acquire a live plan`).not.toBeNull();
  if (!owningView.live || !followingView.live) {
    throw new Error("the selected two-week horizon must contain two live plans");
  }

  // 7. Count only the Sunday-to-Monday boundary between these two selected weeks. A frame block
  //    belongs to the week its start falls in, so exactly one matching span must occur across both
  //    complete plans. A duplicate in the following plan, or no span in the owning plan, changes the
  //    count to two or zero.
  const crossingCount = [...owningView.live.blocks, ...followingView.live.blocks].filter((block) =>
    crossesBoundaryBetween(block, shiftedWeek, followingWeek),
  ).length;

  expect(
    crossingCount,
    `expected exactly 1 frame span from ${shiftedWeek} into ${followingWeek}, got ${crossingCount}`,
  ).toBe(1);
});
