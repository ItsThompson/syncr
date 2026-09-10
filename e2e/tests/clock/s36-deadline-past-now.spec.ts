/* S36's clock half: the clock past a deadline with work remaining.
 *
 * The two no-clock halves of S36 live in `tests/s36-verdict-and-the-clock.spec.ts` and are not
 * touched here. This file drives the third observation, which needs the stack clock moved.
 *
 * THE SEAM IS A TRANSITION: a deadline inside the horizon's capacity becomes the same deadline
 * behind `now`. The case seeds the fixture at the real clock, where the deadline sits beyond the
 * plan week and inside the horizon the maintainer plans. It then shifts the stack clock past that
 * deadline and asserts the whole remaining estimate is reported as the shortfall, as a figure:
 * there is no capacity before a deadline that has already passed, so the gap is the remaining
 * estimate exactly, and the gap's own honoring states the capacity it was measured against as 0m.
 *
 * WHY A DEADLINE SEEDED IN THE PAST IS NOT THIS CASE. A deadline behind `now` was never inside the
 * horizon's capacity: the horizon starts at `now` and extends forward, so a deadline that is
 * already behind `now` when it is declared has never had capacity to measure against. Nothing is
 * observed about the transition because there is no transition: the deadline was always past. This
 * case observes the transition itself, which is why the deadline is seeded in the future and the
 * clock is moved past it rather than the other way round. A fixture that declared a deadline
 * behind `now` would test the probe's arithmetic on a past demand, which the unit suite already
 * does (`test_a_deadline_at_or_before_now_holds_no_capacity_at_all`); what only a clock-moving
 * case can observe is the same deadline, the same week, and the same remaining work read once
 * inside the horizon's capacity and once behind `now`.
 *
 * THE REMAINING ESTIMATE IS READ OFF THE PLAN, NOT RESTATED FROM THE FIXTURE. The fixture owes
 * more than a week can hold, so the solve fills the plan week's whole span with task blocks and
 * still leaves work owed: 10,200 declared against a span of 10,080. What the clock then passes is
 * a deadline with work remaining, and the remaining estimate is the demand less the minutes the
 * plan committed, summed from the live plan's own blocks before the shift. Asserting the gap
 * equals that figure is asserting the capacity term contributed nothing, because the gap is the
 * remaining estimate less the capacity still available before the deadline. The before figure is
 * asserted against the fixture's arithmetic too: netting subtracts the placed minutes from both
 * the demand and the capacity, so the pre-shift gap is the demand less the span whether or not
 * the solve has landed.
 */

import { expect, test, usingFixture } from "../harness.ts";
import type { Shortfall, Verdict } from "../../src/api/schemas.ts";
import { signIn } from "../../src/api/client.ts";
import {
  dateIn,
  instantAt,
  isoWeekShift,
  MONDAY,
  utcMidnightOn,
  type IsoWeekId,
} from "../../src/api/weeks.ts";
import { BASE_URL, E2E_EMAIL, E2E_PASSWORD, HOME_ZONE } from "../../src/config.ts";
import { setStackClock, stackInstant } from "../../src/harness/clock.ts";
import { planWeek } from "../../src/harness/subject-weeks.ts";
import { awaitLivePlan, weekView } from "../../src/harness/week.ts";
import { DEADLINE_TASKS, DEMAND_MINUTES } from "../../src/seed/fixtures/owes-more-than-a-week.ts";

// Each clock scenario leaves the shared stack at its own instant. Reset before fixture loading so
// the fixture's real-clock horizon and its deadline are the state this transition observes.
test.beforeAll(async () => {
  await setStackClock("PT0S");
});
usingFixture("owes_more_than_a_week");

const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;

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

/** The one deadline_capacity shortfall this fixture carries, refusing anything but one, so a
 * second kind cannot hide behind it.
 *
 * WHICH TASKS IT NAMES IS STATE, NOT A CONSTANT. The solve places work until the week is full, and
 * a task whose placements cover its own estimate owes nothing and leaves the demand, so the gap
 * may name a proper subset of the fixture's two tasks. Each named task is asserted to be one of
 * them, and the list is asserted non-empty. */
const theDeadlineGap = (verdict: Verdict | null): Shortfall => {
  const gaps = verdict?.shortfalls ?? [];
  const deadlineGaps = gaps.filter((gap) => gap.kind === "deadline_capacity");
  expect(deadlineGaps, "the verdict holds no deadline_capacity shortfall").toHaveLength(1);
  expect(deadlineGaps[0]!.against.length).toBeGreaterThan(0);
  for (const named of deadlineGaps[0]!.against) expect(DEADLINE_TASKS).toContain(named);
  return deadlineGaps[0]!;
};

/* Recreating two containers takes longer than the default ceiling allows; the shift itself is
 * what costs, and every wait here polls the state it is about rather than sleeping. */
test.setTimeout(240_000);

test("S36 the clock past a deadline with work remaining reports the whole remaining estimate as the shortfall", async ({
  api,
}) => {
  const week = planWeek();

  // The deadline: UTC midnight on the Monday that ends the plan week. The fixture places it here so
  // it is at or after both subject weeks' last instant, which is what makes it inside the horizon's
  // capacity at the real clock.
  const deadlineInstant = utcMidnightOn(dateIn(isoWeekShift(week, 1), MONDAY));
  const deadlineMs = Date.parse(deadlineInstant);

  // Wait for the plan week to materialize and its solve to settle, so the state the figures below
  // are exact in is stable: the plan holds the blocks the solve placed, and no proposal awaits
  // assent (a fill-only candidate is applied, leaving the slot empty), so every later read computes
  // a fresh probe against the clock the api holds at read time.
  const before = await awaitLivePlan(api, week);

  // THE STATE THE FIGURES ARE EXACT IN. The solve placed task work into the week, and the demand
  // still owed at the deadline is the fixture's demand less those minutes. Both are figures read
  // off the plan rather than restated, so a solve that placed a different share still asserts
  // exactly.
  const placed = before.live!.blocks.reduce((sum, block) => sum + blockMinutes(block.interval), 0);
  expect(placed, "the solve placed no task work, so nothing is committed").toBeGreaterThan(0);
  const remainingEstimate = DEMAND_MINUTES - placed;
  expect(
    remainingEstimate,
    "no work remains before the deadline, so the clock cannot pass work that is owed",
  ).toBeGreaterThan(0);

  // THE FIGURE BEFORE THE TRANSITION. Netting subtracts the placed minutes from the demand and
  // from the capacity alike, so the pre-shift gap is the demand less the plan week's whole span,
  // and the capacity the gap names still holds the unplaced remainder of that span.
  const beforeGap = theDeadlineGap(before.verdict);
  expect(beforeGap.minutes).toBe(DEMAND_MINUTES - spanMinutes(week));
  expect(capacityItMeasured(beforeGap)).toBe(spanMinutes(week) - placed);
  expect(Date.parse(beforeGap.deadline!)).toBe(deadlineMs);

  // Shift the stack clock past the deadline. The offset is computed from the real clock so it is
  // always enough whatever weekday the suite runs on: the deadline is at least eight days out and
  // at most fourteen, and one extra day clears the midnight boundary.
  const nowMs = Date.now();
  const shiftDays = Math.ceil((deadlineMs - nowMs) / DAY_MS) + 1;
  await setStackClock(`P${shiftDays}D`);

  // Confirm the shift reached the running api: its reported instant is past the deadline. This is
  // a guard that the shift took, so the shortfall assertion below fails for the right reason if it
  // did not.
  await expect
    .poll(async () => (await stackInstant("api")).getTime() > deadlineMs, { timeout: 120_000 })
    .toBe(true);

  // SIGN IN AGAIN, because the shift outlives the session it was made under. A session's idle
  // window is fourteen days and the shift is up to fifteen, so the credential the fixture signed
  // in with is idle too long at the shifted clock and the api answers 401 for it. A fresh sign-in
  // mints a session whose idle window starts at the shifted instant, which is the credential the
  // shifted stack accepts.
  const shifted = await signIn(BASE_URL, E2E_EMAIL, E2E_PASSWORD);

  // THE OBSERVATION, IN THREE FIGURES. The deadline is behind `now`, so the capacity before it is
  // zero: the gap's own honoring states the capacity it was measured against as 0m, and the whole
  // remaining estimate is the shortfall, exactly. The denominator keeps the whole week's span
  // behind `now` as it does ahead of it, which is the rule the no-clock half asserts on the week
  // the clock has reached.
  const after = await weekView(shifted, week);
  expect(after.live, "the plan week lost its plan after the clock shift").not.toBeNull();
  const afterGap = theDeadlineGap(after.verdict);
  expect(capacityItMeasured(afterGap)).toBe(0);
  expect(afterGap.minutes).toBe(remainingEstimate);
  expect(Date.parse(afterGap.deadline!)).toBe(deadlineMs);
  expect(after.verdict!.discretionaryMinutes).toBe(spanMinutes(week));
});
