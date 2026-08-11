/* S36's two clock-free halves: which span a verdict measures capacity over, and what a skip does to a
 * shortfall.
 *
 * S36 IS THREE OBSERVATIONS AND THIS FILE MAKES TWO OF THEM. The third needs the clock moved past a
 * deadline with work remaining, which nothing in this stack can do. What is here needs no clock MOVED,
 * and each half is asserted as a figure rather than as a comparison between two readings, because a
 * comparison passes whenever both readings are wrong the same way.
 *
 * THE FIRST HALF IS ASSERTED ON TWO WEEKS AT ONCE, AND THAT PAIR IS THE POINT. The current week and
 * the plan week hold identical declarations and one demand, and they differ in one respect: the clock
 * has reached into one of them. So the plan week's capacity before the deadline is its whole span,
 * exactly, and the current week's is the distance from the reading instant to its end. Asserting only
 * the second would pass against a capacity computed from any fixed offset; asserting the pair is what
 * makes the reading instant the thing being measured.
 *
 * WHY THE SKIP IS OBSERVED ON THE PLAN WEEK RATHER THAN THE CURRENT ONE, which is the narrowing this
 * file owes a reader. A skip's whole subject is attribution: the work stops counting toward the task
 * and the block's span stays committed, so the gap rises by the block's own minutes. Both halves of
 * that are figures, and on the current week the second one moves while the case runs: free capacity is
 * clipped to the reading instant, so any part of the week that is unplaced and ahead of that instant
 * shrinks between the two reads of a before-and-after. On the plan week nothing is behind the clock,
 * so the capacity side is constant and a rise of exactly the block's minutes is assertable.
 *
 * WHAT THAT COSTS, MEASURED RATHER THAN ARGUED: the block this case skips lies ahead of the reading
 * instant rather than behind it. No block can lie behind it here. The solver's own gap set is clipped
 * to that instant and every placement it makes lands on the fifteen-minute grid at or after it, a pin
 * is refused both for a block that has begun and for a start already gone, and no other path places a
 * block at all. So the earliest task block a fresh seed can produce begins in the future, and a suite
 * that wanted one behind the clock would have to wait for the grid instant it starts at. The rule
 * under test does not read the difference: what a placement contributes to its content is decided by
 * the outcome alone, and where its span falls decides only which side of the reading instant those
 * minutes are counted on, which is the same figure while nothing is confirmed.
 */

import { expect, test, usingFixture } from "./harness.ts";
import type { Shortfall, Verdict, WeekView } from "../src/api/schemas.ts";
import { dateIn, instantAt, isoWeekShift, MONDAY, type IsoWeekId } from "../src/api/weeks.ts";
import { HOME_ZONE } from "../src/config.ts";
import { currentWeek, planWeek } from "../src/harness/subject-weeks.ts";
import { solveAndSettle, weekView } from "../src/harness/week.ts";
import {
  DEADLINE_TASKS,
  DEMAND_MINUTES,
  EACH_MINUTES,
} from "../src/seed/fixtures/owes-more-than-a-week.ts";

usingFixture("owes_more_than_a_week");

const MINUTE_MS = 60_000;

/** Local midnight on the Monday that opens `isoWeek`, which is where a week's span begins. */
const opensAt = (isoWeek: IsoWeekId): number =>
  Date.parse(instantAt(dateIn(isoWeek, MONDAY), "00:00:00", HOME_ZONE));

/** Local midnight on the Monday that closes it. Read through the zone, so a transition week is 169
 * or 167 hours here exactly as it is to the product. */
const closesAt = (isoWeek: IsoWeekId): number => opensAt(isoWeekShift(isoWeek, 1));

const spanMinutes = (isoWeek: IsoWeekId): number =>
  (closesAt(isoWeek) - opensAt(isoWeek)) / MINUTE_MS;

const blockMinutes = (interval: { start: string; end: string }): number =>
  (Date.parse(interval.end) - Date.parse(interval.start)) / MINUTE_MS;

/** `5h`, `1h20m`, `45m`, `0m`: the one rendering the domain gives a duration wherever it names one. */
const renderedMinutes = (rendered: string): number => {
  const parts = /^(?:(\d+)h)?(?:(\d+)m)?$/.exec(rendered);
  if (!parts || (parts[1] === undefined && parts[2] === undefined)) {
    throw new Error(`${rendered} is not a duration this product renders`);
  }
  return Number(parts[1] ?? 0) * 60 + Number(parts[2] ?? 0);
};

/** What the week said it had left before the deadline, read back out of the gap's honored constraints. */
const capacityItMeasured = (shortfall: Shortfall): number => {
  const stated = shortfall.honoring
    .map((honored) => /^the (\S+) still uncommitted before it$/.exec(honored))
    .find((match) => match !== null);
  if (!stated) {
    throw new Error(
      `no honored constraint names the capacity: ${JSON.stringify(shortfall.honoring)}`,
    );
  }
  return renderedMinutes(stated[1]!);
};

/** The one gap this week carries, refusing anything but one, so a second kind cannot hide behind it.
 *
 * WHICH TASKS IT NAMES IS STATE, NOT A CONSTANT, so it is asserted at the call sites that know the
 * state and only bounded here. A task whose placements already cover its own estimate before the
 * deadline owes nothing and leaves the demand, which is netting working; and a skip puts it back. */
const theOneGap = (verdict: Verdict | null): Shortfall => {
  const gaps = verdict?.shortfalls ?? [];
  expect(gaps.map((gap) => gap.kind)).toEqual(["deadline_capacity"]);
  expect(gaps[0]!.against.length).toBeGreaterThan(0);
  for (const named of gaps[0]!.against) expect(DEADLINE_TASKS).toContain(named);
  return gaps[0]!;
};

/** The week as the seed leaves it: a plan holding nothing, which is what makes the span readable. */
const asSeeded = (view: WeekView, isoWeek: IsoWeekId): void => {
  expect(
    view.live?.blocks ?? null,
    `${isoWeek} holds blocks, so something has already been placed in it`,
  ).toEqual([]);
  expect(view.live?.forbiddenWindows ?? null, `${isoWeek} holds a declared window`).toEqual([]);
};

test("S36 a verdict read mid-week counts capacity from now onward, and keeps the whole week as its denominator", async ({
  api,
}) => {
  const lived = currentWeek();
  const unlived = planWeek();

  // Bracketing the reads is what makes an exact figure assertable at all: the instant the api stamps
  // its assembly with lies between these two, and a minute boundary can fall inside that window.
  const before = Date.now();
  const current = await weekView(api, lived);
  const plan = await weekView(api, unlived);
  const after = Date.now();

  // THE STATE THE FIGURES BELOW ARE EXACT IN, ASSERTED RATHER THAN ASSUMED. No frame, no window and
  // nothing placed, so each week's discretionary time is its own span and the capacity before a
  // deadline beyond the week is what is left of that span.
  asSeeded(current, lived);
  asSeeded(plan, unlived);

  // THE DENOMINATOR KEEPS THE WHOLE WEEK, in the week that has been lived into as much as in the one
  // that has not. Each is compared against its own span rather than against the other, because a week
  // whose clocks change is 167 or 169 hours long and both figures are then correct and unequal.
  expect(current.verdict!.discretionaryMinutes).toBe(spanMinutes(lived));
  expect(plan.verdict!.discretionaryMinutes).toBe(spanMinutes(unlived));

  // THE UNLIVED WEEK COUNTS ITS WHOLE SPAN. Exact: every boundary of it is a minute boundary, and the
  // clock has reached none of it. Nothing is placed in either week, so both owe the whole demand and
  // the gap names both halves of it.
  const ahead = theOneGap(plan.verdict);
  expect(ahead.against).toEqual([...DEADLINE_TASKS]);
  expect(capacityItMeasured(ahead)).toBe(spanMinutes(unlived));
  expect(ahead.minutes).toBe(DEMAND_MINUTES - spanMinutes(unlived));

  // THE LIVED WEEK COUNTS FROM THE READING INSTANT ONWARD, and the hours it has already spent are
  // offered to nothing. The bracket is one minute wide and the figure it excludes is the whole span.
  const behind = theOneGap(current.verdict);
  expect(behind.against).toEqual([...DEADLINE_TASKS]);
  const measured = capacityItMeasured(behind);
  expect(measured).toBeLessThanOrEqual(Math.ceil((closesAt(lived) - before) / MINUTE_MS));
  expect(measured).toBeGreaterThanOrEqual(Math.floor((closesAt(lived) - after) / MINUTE_MS));

  // And the gap is the difference between the demand and that capacity, so the figure the panel shows
  // grows by every hour the week spends rather than staying where the week started.
  expect(behind.minutes).toBe(DEMAND_MINUTES - measured);

  // THE TWO SPANS ARE NOT THE SAME SPAN. It holds at every instant except the first minute of the ISO
  // week, when nothing has elapsed for the clip to remove; the bracket above is what bites there.
  expect(
    measured,
    "no discretionary minute of this week has elapsed yet, so the clip has nothing to remove and this " +
      "comparison cannot discriminate: re-read it later in the week",
  ).toBeLessThan(current.verdict!.discretionaryMinutes);
});

test("S36 skipping a committed block raises the shortfall by that block's own minutes and returns none of its span to capacity", async ({
  api,
}) => {
  const week = planWeek();
  asSeeded(await weekView(api, week), week);

  await solveAndSettle(api, week);
  const solved = await weekView(api, week);
  const placed = solved.live!.blocks.filter((block) => block.origin === "task");
  expect(
    placed.length,
    "the solve placed no task block, so there is nothing to skip",
  ).toBeGreaterThan(0);

  // A PLACEMENT DOES NOT MOVE THE GAP, which is what makes the rise below attributable to the skip
  // alone: both sides of the comparison are net of what is placed, so the same figure survives a solve.
  const before = theOneGap(solved.verdict);
  expect(before.minutes).toBe(DEMAND_MINUTES - spanMinutes(week));

  // The block this case acts on, and the state it is in, asserted: the week has committed it, nobody
  // pinned it, and it holds a legible share of one task's own estimate.
  const skipped = placed[0]!;
  const minutes = blockMinutes(skipped.interval);
  expect(skipped.pinned).toBe(false);
  expect(minutes).toBeLessThanOrEqual(EACH_MINUTES);
  expect(minutes).toBeGreaterThan(0);

  await api.put(`/api/v1/blocks/${skipped.id}/outcome`, {
    isoWeek: week,
    state: "skipped",
    actualInterval: null,
    actualMinutes: null,
  });

  const after = await weekView(api, week);
  const raised = theOneGap(after.verdict);

  // THE OBSERVATION, IN TWO FIGURES. The work stops counting toward the task, so the gap rises by
  // exactly the minutes the block held; and the span stays committed, so the capacity the gap names
  // does not move. A verdict that returned the span to capacity would report a SMALLER gap, which is
  // the reading that makes not doing the work an improvement.
  expect(raised.minutes).toBe(before.minutes + minutes);
  expect(capacityItMeasured(raised)).toBe(capacityItMeasured(before));
  expect(after.verdict!.discretionaryMinutes).toBe(solved.verdict!.discretionaryMinutes);

  // And the work is owed again by name: the task the block held is back in what the deadline reports.
  expect(raised.against).toContain(skipped.title);

  // And the block is still where it was: an outcome says what happened, and it moves nothing.
  const held = after.live!.blocks.find((block) => block.id === skipped.id);
  expect(held?.interval).toEqual(skipped.interval);
});
