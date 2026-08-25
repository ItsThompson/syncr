/* S25: progress does not manufacture a shortfall.
 *
 * THE OBSERVATION IS ARITHMETIC, NOT A PANEL. A week that owes more before its deadline than it
 * can hold reports one `deadline_capacity` gap whose two sides both net every placement: the
 * demand side nets the deadline task's own placed minutes, and the capacity side subtracts every
 * placed minute from the free time in front of the deadline. Pinning is the mutation a user
 * performs most, so the defect class this scenario exists to catch is a pin moving one side of
 * that comparison without moving the other: counted progress shrinking the demand, or counted
 * progress being charged to the capacity too.
 *
 * WHY `tight_capacity`. The gap has to be movable by a pin in BOTH directions, which takes a week
 * where a single mutation reaches the comparison. On a roomy week a pin moves nothing because
 * there is nothing to move: every figure fits either way and the cases pass vacuously, which is
 * exactly what the first version of the floor observations did on `reference_week` before they
 * moved here. This week owes 510 minutes against the 420 in front of its Wednesday deadline, so
 * it reports one 90-minute gap before anything is solved, and the gap survives the solve because
 * what the week cannot hold before that instant is capacity rather than a placement.
 *
 * THE SEQUENCE, AND WHY IT HAS FOUR PINS RATHER THAN THREE. The window in front of the deadline
 * is full after the solve, so an unrelated pin has nowhere to land until counted work moves out
 * of it. Moving that work out is itself a pin, and the arithmetic says it must not move the gap:
 * the minutes leave the demand side and the capacity side together. So the case pins the Tuesday
 * chunk out of the window first, asserts the gap stayed put, and only then pins unrelated work
 * INTO the freed two hours, asserting the gap grows by exactly what lands there.
 *
 * WHY THE FIGURES ARE MEASURED RATHER THAN ASSUMED. A pin holds the interval the document it
 * resolves against carries, and while a re-solve's proposal is pending that document is the
 * candidate rather than the plan of record, so the duration a pin lands with is read back rather
 * than assumed from it. Every checkpoint therefore asserts an equality the arithmetic forces
 * whichever duration the pin carried: the gap against the fixture's own constants, and each
 * growth against the minutes the read-back shows landed in the window.
 *
 * WHY THE CASE DOES NOT ADOPT AS IT GOES. The re-solve a pin schedules wants to rearrange
 * everything else, and adopting its candidate would let the solver pour counted work straight
 * back into whatever room the case just freed. So nothing is adopted mid-sequence: what the week
 * effectively holds is read from the served document WITH the pins of the same read laid over it,
 * which is exactly the set the probe's arithmetic runs on, and the gap figures are identical
 * whichever branch of the week's read serves them.
 *
 * WHAT THE THIRD PIN READS. A block's reason clauses carry the Area floor twice over two
 * different placement sets: `floorMinutes` nets immovable placements only, which is the figure
 * the solver works to, and `of - placed` nets every placement, which is the probe's reservation.
 * Pinning a Fitness block makes its minutes immovable, so the first figure falls by exactly the
 * pinned minutes while the second stays at zero. Both are asserted over the adopted plan, because
 * the pair moving together is the whole distinction between progress that is counted and progress
 * that is manufactured: the clauses refresh on adoption, so the case adopts once, after its last
 * pin, and reads them there.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { ApiClient } from "../src/api/client.ts";
import type { Operation, Verdict, WeekView } from "../src/api/schemas.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { awaitTerminal, pendingProposal, solveNow, until, weekView } from "../src/harness/week.ts";
import {
  DEADLINE_TASK,
  DISCRETIONARY_MINUTES,
  FITNESS_FLOOR_MINUTES,
  PRE_DEADLINE_SHORTFALL_MINUTES,
} from "../src/seed/fixtures/tight-capacity.ts";

usingFixture("tight_capacity");

/* How much unrelated work the case pins into the window: the two hours the evacuation frees. */
const TWO_HOURS_MINUTES = 120;

const MINUTE_MS = 60_000;

type Span = { readonly start: number; readonly end: number };

/** Minutes per day. */
const spanMinutes = (span: { readonly start: string; readonly end: string }): number =>
  (Date.parse(span.end) - Date.parse(span.start)) / MINUTE_MS;

/** Each block's identifier paired with where it effectively sits: its own interval, overridden by
 * its pin's where one stands. While a re-solve's proposal pends, the served document can lag the
 * arithmetic, but the pins of the same read never do, so every geometry question below is asked
 * of the two together rather than of either. */
const effectiveBlocks = (
  view: WeekView,
): readonly {
  readonly id: string;
  readonly span: { readonly start: string; readonly end: string };
}[] => {
  const pinIntervalByBlock = new Map((view.pins ?? []).map((pin) => [pin.blockId, pin.interval]));
  return (view.live?.blocks ?? []).map((block) => ({
    id: block.id,
    span: pinIntervalByBlock.get(block.id) ?? block.interval,
  }));
};

/** Whether the week holds a pin for this block, read from the pins rather than from the served
 * document's flag, which only advances with an adoption. */
const holdsPin = (view: WeekView, blockId: string): boolean =>
  (view.pins ?? []).some((pin) => pin.blockId === blockId);

/** One merged timeline, and the minutes it covers: overlapping placements contribute one minute,
 * as the probe counts them. The merge is stated once and the total derives from it. */
const unionSpans = (spans: readonly Span[]): readonly Span[] => {
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const merged: Span[] = [];
  for (const span of sorted) {
    const last = merged.at(-1);
    if (last === undefined || span.start > last.end) merged.push({ ...span });
    else if (span.end > last.end)
      merged.splice(merged.length - 1, 1, { start: last.start, end: span.end });
  }
  return merged;
};

const unionMinutes = (spans: readonly Span[]): number =>
  unionSpans(spans).reduce((total, span) => total + span.end - span.start, 0) / MINUTE_MS;

/** Everything the week effectively occupies, clipped to `[from, to)`, in milliseconds. */
const occupied = (view: WeekView, from: number, to: number): readonly Span[] =>
  effectiveBlocks(view).flatMap(({ span }) => {
    const start = Math.max(Date.parse(span.start), from);
    const end = Math.min(Date.parse(span.end), to);
    return start < end ? [{ start, end }] : [];
  });

/** The free stretches left inside `[from, to)` once everything the week holds is subtracted. */
const freeStretches = (view: WeekView, from: number, to: number): readonly Span[] => {
  const busy = unionSpans(occupied(view, from, to));
  const gaps: Span[] = [];
  let cursor = from;
  for (const span of busy) {
    if (span.start > cursor) gaps.push({ start: cursor, end: span.start });
    cursor = Math.max(cursor, span.end);
  }
  if (cursor < to) gaps.push({ start: cursor, end: to });
  return gaps;
};

/**
 * The gap the week reports, demanded to be exactly one deadline shortfall naming the one task.
 * The whole set is compared rather than searched, so a floor shortfall appearing mid-sequence
 * fails here instead of hiding behind the figure being looked for.
 */
const expectDeadlineGap = (view: WeekView, minutes: number, at: string): number => {
  const gaps = view.verdict!.shortfalls;
  expect(
    gaps.map((gap) => gap.kind),
    `${at}: the shortfall set changed`,
  ).toEqual(["deadline_capacity"]);
  expect(gaps[0]!.against, `${at}: the shortfall names other work`).toEqual([DEADLINE_TASK]);
  expect(gaps[0]!.minutes, `${at}: the gap moved`).toBe(minutes);
  return gaps[0]!.minutes;
};

/** Pin one block, wait out the re-solve it schedules, and answer the verdict the pin itself gave.
 *
 * Deliberately no adoption here: the candidate that re-solve leaves usually rearranges the rest
 * of the week, and adopting it would let counted work pour straight back into whatever room the
 * sequence just freed. The next read serves the candidate's stored verdict while it pends, and
 * that figure is the same number the probe computes over live-plus-pins, so the checkpoints hold
 * across both branches of the week's read. */
const pinAndSettle = async (
  api: ApiClient,
  week: string,
  blockId: string,
  start: string,
): Promise<Verdict> => {
  const reply = await api.post<{ verdict: Verdict; operation: Operation }>(
    `/api/v1/weeks/${week}/pins`,
    { blockId, start },
  );
  await awaitTerminal(api, reply.operation.id);
  return reply.verdict;
};

/** Adopt the pending proposal if the settled solve left one, and wait until the slot answers empty. */
const adoptSettled = async (
  api: ApiClient,
  week: string,
  idempotencyKey: string,
): Promise<void> => {
  if (!(await pendingProposal(api, week))) return;
  await api.post(`/api/v1/weeks/${week}/approve`, undefined, { idempotencyKey });
  await until(
    `${week}'s pending proposal to clear`,
    () => pendingProposal(api, week),
    (seen) => seen === null,
    10_000,
  );
};

test("S25 progress does not manufacture a shortfall", async ({ api }) => {
  test.setTimeout(240_000);
  const week = planWeek();

  /* THE WEEK THE SEQUENCE DRIVES, SETTLED INTO A STATE IT CAN ACT ON. A solve whose candidate
   * only fills adopts straight away, but the worker may have solved the freshly materialized week
   * first, and a later solve that moves anything leaves its result in the pending slot instead.
   * So the case settles whichever document the last solve left: a proposal is adopted, an
   * unsolved week is solved again, and the loop ends when the live plan holds placed deadline-task
   * work, which is what every pin below resolves against. */
  const holdsDeadlineWork = (view: WeekView): boolean =>
    (view.live?.blocks ?? []).some(
      (block) =>
        block.title === DEADLINE_TASK &&
        Date.parse(block.interval.end) <= Date.parse(view.verdict!.shortfalls[0]!.deadline!),
    );
  let solved = await weekView(api, week);
  for (let attempt = 0; !holdsDeadlineWork(solved); attempt += 1) {
    expect(
      attempt,
      "the week never came to hold placed deadline-task work, so the sequence has nothing to pin",
    ).toBeLessThan(3);
    if (await pendingProposal(api, week)) {
      await adoptSettled(api, week, `s25-settle-${week}-${attempt}`);
    } else {
      /* The worker may have solved this week itself the moment it materialized, and a solve
       * displaced by that one ends `superseded`, which here means only that the other solve's
       * result is what the next read will see. The loop decides from the read, not from the
       * operation, so a superseded attempt is worth exactly as much as an empty one. */
      const started = await solveNow(api, week);
      const settled = await awaitTerminal(api, started.id);
      expect(settled.status, `the setup solve failed outright: ${settled.statement}`).not.toBe(
        "failed",
      );
    }
    solved = await weekView(api, week);
  }
  expect(solved.verdict!.discretionaryMinutes).toBe(DISCRETIONARY_MINUTES);
  expectDeadlineGap(solved, PRE_DEADLINE_SHORTFALL_MINUTES, "after the solve");
  const deadline = solved.verdict!.shortfalls[0]!.deadline!;

  /* The window's lower bound is where the week's own content starts, so the Sunday-side frame
   * edge never enters any measurement below. Everything is a difference between readings taken
   * over the same window, so the bound itself carries no arithmetic. */
  const windowStart = Math.min(
    ...(solved.live?.blocks ?? [])
      .filter((block) => block.origin !== "frame")
      .map((block) => Date.parse(block.interval.start)),
  );
  const windowEnd = Date.parse(deadline);

  /* THE FITNESS FIGURE, STATED RATHER THAN READ AS A BASELINE. Whether the week's first solve
   * assembled on an empty week or after the maintainer had already filled it decides what the
   * initial clauses carry, so no baseline is read here. What is deterministic is the assembly the
   * step's own re-solve runs on: no Fitness minute is immovable in it except the pin this step is
   * about to make, so the solver's remaining floor work must be the declared floor less exactly
   * the pinned minutes, whichever route the week took to here. */
  const areas = await api.get<{
    areas: readonly { id: string; name: string }[];
  }>("/api/v1/areas");
  const fitnessAreaId = areas.areas.find((area) => area.name === "Fitness")!.id;
  const floorClauseOf = (view: WeekView, areaId: string) => {
    const clauses = (view.live?.blocks ?? []).flatMap((block) =>
      block.areaId === areaId
        ? block.reason.clauses.filter((clause) => clause.kind === "floor")
        : [],
    );
    expect(
      clauses.length,
      "the week holds no Fitness block carrying a floor clause, so the remaining-floor figure is " +
        "not readable",
    ).toBeGreaterThan(0);
    const figures = new Set(clauses.map((clause) => JSON.stringify(clause)));
    expect(
      figures.size,
      `the Fitness blocks disagree about the floor: ${JSON.stringify([...figures])}`,
    ).toBe(1);
    return clauses[0]!;
  };

  /* STEP 1: pin two hours of the deadline task, where the solve put it. Both sides of the
   * comparison are net of the task's own placements, so the gap may not move: not in the pin's
   * own answer, and not once the re-solve has settled. */
  const counted = solved
    .live!.blocks.filter(
      (block) =>
        block.title === DEADLINE_TASK &&
        !holdsPin(solved, block.id) &&
        Date.parse(block.interval.end) <= windowEnd,
    )
    .find((block) => spanMinutes(block.interval) === TWO_HOURS_MINUTES);
  expect(
    counted,
    "the solved week holds no two-hour chunk of the deadline task before the deadline, so the " +
      "fixture no longer is the week this case describes",
  ).toBeDefined();
  const step1 = await pinAndSettle(api, week, counted!.id, counted!.interval.start);
  expect(step1.shortfalls.map((gap) => gap.minutes)).toEqual([PRE_DEADLINE_SHORTFALL_MINUTES]);
  expectDeadlineGap(await weekView(api, week), PRE_DEADLINE_SHORTFALL_MINUTES, "after step 1");

  /* THE EVACUATION: the counted two-hour Tuesday chunk moves out of the window to make exactly
   * the room step 2 needs. It lands on whatever effectively sits past the deadline, because
   * overlap is not what is under test here; what is under test is that counted work leaving the
   * window leaves the gap where it was. */
  const afterStep1 = await weekView(api, week);
  const evicted = afterStep1.live!.blocks.find(
    (block) =>
      block.title === DEADLINE_TASK &&
      !holdsPin(afterStep1, block.id) &&
      Date.parse(block.interval.end) <= windowEnd &&
      spanMinutes(block.interval) === TWO_HOURS_MINUTES,
  );
  expect(
    evicted,
    "the window holds no unpinned two-hour deadline-task chunk left to move out of it",
  ).toBeDefined();
  const elsewhere = effectiveBlocks(afterStep1).find(
    ({ id, span }) =>
      afterStep1.live!.blocks.find((block) => block.id === id)?.origin !== "frame" &&
      Date.parse(span.start) >= windowEnd,
  );
  expect(
    elsewhere,
    "the week holds no content past the deadline to land the evacuee on",
  ).toBeDefined();
  await pinAndSettle(api, week, evicted!.id, elsewhere!.span.start);
  expectDeadlineGap(
    await weekView(api, week),
    PRE_DEADLINE_SHORTFALL_MINUTES,
    "after evacuating counted work from the window",
  );

  /* STEP 2: pin unrelated work into the freed window. Each pin's growth is asserted against what
   * the read-back shows it committed, and the loop runs until exactly the freed two hours has
   * landed: one pin when it lands whole, two when the first chunk leaves a rest too small for
   * another full chunk, which the rest of the window then caps. */
  let unrelated = 0;
  let gap = PRE_DEADLINE_SHORTFALL_MINUTES;
  for (let pin = 1; unrelated < TWO_HOURS_MINUTES; pin += 1) {
    expect(
      pin,
      "the window did not absorb two hours of unrelated work within two pins",
    ).toBeLessThanOrEqual(2);
    const before = await weekView(api, week);
    const stretches = freeStretches(before, windowStart, windowEnd);
    const stretch = stretches.at(-1);
    expect(
      stretch,
      `the window holds no free stretch to pin unrelated work into after ${unrelated} committed minutes`,
    ).toBeDefined();
    const bystander = effectiveBlocks(before)
      .filter(({ id, span }) => {
        const block = before.live!.blocks.find((each) => each.id === id);
        return (
          block !== undefined &&
          block.title !== DEADLINE_TASK &&
          block.areaId !== null &&
          !holdsPin(before, id) &&
          Date.parse(span.start) >= windowEnd
        );
      })
      .at(0);
    expect(bystander, "the week holds no unrelated block left to pin").toBeDefined();

    const committed = unionMinutes(occupied(before, windowStart, windowEnd));
    await pinAndSettle(api, week, bystander!.id, new Date(stretch!.start).toISOString());
    const after = await weekView(api, week);
    const landed = unionMinutes(occupied(after, windowStart, windowEnd)) - committed;

    expect(
      landed,
      `unrelated pin ${pin} committed ${landed} minutes into the window`,
    ).toBeGreaterThan(0);
    unrelated += landed;
    gap += landed;
    expectDeadlineGap(
      after,
      gap,
      `after unrelated pin ${pin}: the gap must have grown by exactly the ${landed} minutes ` +
        "the pin committed, no more and no less",
    );
  }
  expect(
    unrelated,
    "the window absorbed a different amount of unrelated work than the two hours freed",
  ).toBe(TWO_HOURS_MINUTES);
  expect(
    gap,
    "two hours of unrelated work in the window must grow the gap to exactly this figure",
  ).toBe(PRE_DEADLINE_SHORTFALL_MINUTES + TWO_HOURS_MINUTES);

  /* STEP 3: pin a Fitness block where it is. Its minutes become immovable, so the solver's
   * remaining floor work falls by exactly the pinned minutes; netted over every placement the
   * reservation is unchanged, because the same minutes were already committed. The refreshed
   * clauses go live with the adoption, so the case approves the re-solve's proposal first. */
  const beforeStep3 = await weekView(api, week);
  const fitness = effectiveBlocks(beforeStep3)
    .filter(({ id, span }) => {
      const block = beforeStep3.live!.blocks.find((each) => each.id === id);
      return (
        block !== undefined &&
        block.areaId === fitnessAreaId &&
        !holdsPin(beforeStep3, id) &&
        Date.parse(span.start) >= windowEnd
      );
    })
    .map(({ id }) => beforeStep3.live!.blocks.find((block) => block.id === id)!)
    .at(0);
  expect(fitness, "the week holds no unpinned Fitness block past the deadline").toBeDefined();
  await pinAndSettle(api, week, fitness!.id, fitness!.interval.start);

  /* The clauses refresh only when a plan advances, so the case adopts once here: this is its last
   * mutation, and the pinned flag coming back true proves the document served below is the one
   * this re-solve explained. */
  await adoptSettled(api, week, `s25-final-${week}`);
  const withAdoptedPlan = await weekView(api, week);
  const pinnedFitness = withAdoptedPlan.live!.blocks.find((block) => block.id === fitness!.id)!;
  expect(
    pinnedFitness.pinned,
    "the adopted plan does not carry the Fitness pin, so the clause " +
      "figures below would be stale",
  ).toBe(true);

  /* Every minute any pin holds in the Fitness Area is immovable at the assembly the adopted plan
   * was solved on, and the pins never overlap each other here because each one landed either
   * where its block already was or on free time, so their durations sum without merging. */
  const areaByBlock = new Map(
    (withAdoptedPlan.live?.blocks ?? []).map((block) => [block.id, block.areaId]),
  );
  const fitnessPinMinutes = (withAdoptedPlan.pins ?? [])
    .filter((pin) => areaByBlock.get(pin.blockId) === fitnessAreaId)
    .reduce((total, pin) => total + spanMinutes(pin.interval), 0);
  expect(fitnessPinMinutes, "the pins held no Fitness minutes at all").toBeGreaterThan(0);

  const fitnessAfter = floorClauseOf(withAdoptedPlan, fitnessAreaId);
  expect(
    fitnessAfter.floorMinutes,
    `pinning ${fitnessPinMinutes} Fitness minutes must leave the solver exactly that much less ` +
      "floor to place",
  ).toBe(FITNESS_FLOOR_MINUTES - fitnessPinMinutes);
  expect(
    fitnessAfter.of - fitnessAfter.placed,
    "the probe's own reservation moved with the pin, which is progress manufacturing a shortfall",
  ).toBe(0);

  /* And the deadline gap itself is exactly where step 2 left it: the Fitness pin went in where
   * the block already was, behind the deadline, so neither side of that comparison moves. */
  expectDeadlineGap(
    await weekView(api, week),
    PRE_DEADLINE_SHORTFALL_MINUTES + TWO_HOURS_MINUTES,
    "after step 3",
  );
});
