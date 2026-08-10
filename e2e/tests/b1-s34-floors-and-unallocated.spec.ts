/* The Blocker 1 observation, and S34.
 *
 * Both are about a figure that is right or wrong rather than present or absent, which is the class of
 * failure this product cannot detect any other way: neither throws, and both render plausibly.
 *
 * WHY THIS FILE USES `tight_capacity` AND NOT `reference_week`. The first version of these cases ran on
 * `reference_week`, whose plan week holds 5565 minutes of discretionary time against 480 minutes of
 * declared floor: roomy by a factor of eleven. Both fit under either netting rule, so a bite reverting the
 * probe's floor reservation to the pre-B1 immovable-only rule left both cases GREEN, and the at-risk loop
 * iterated zero times because no task was at risk. The case bounded nothing. `tight_capacity` is the week
 * B1 is actually about: 1470 discretionary minutes against 960 of floor, met by unpinned solver-placed
 * blocks, and less left free once solved than those floors reserve, so a reservation that netted nothing
 * would be 960 against that remainder and would report a shortfall on a week that is fully scheduled.
 * The fixture states that arithmetic and the first case here asserts it.
 *
 * WHICH VERDICT THE AT-RISK COLUMN IS CROSSED AGAINST. The backlog is not week-scoped: the marking reads
 * the CURRENT week's verdict, through `served_verdicts.CurrentWeekVerdict`, which is the same rule the
 * Week screen serves. So crossing it against the plan week's shortfalls, as the first version did, pairs
 * two different weeks and can only be vacuously true.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Verdict } from "../src/api/schemas.ts";
import { currentWeek, planWeek } from "../src/harness/subject-weeks.ts";
import { solveAndSettle, weekView } from "../src/harness/week.ts";
import {
  CAREER_FLOOR_MINUTES,
  DEADLINE_TASK,
  DISCRETIONARY_MINUTES,
  FITNESS_FLOOR_MINUTES,
  PRE_DEADLINE_MINUTES,
  PRE_DEADLINE_SHORTFALL_MINUTES,
} from "../src/seed/fixtures/tight-capacity.ts";

usingFixture("tight_capacity");

/* NOT serial, deliberately, even though the cases share a week. Serial mode would stop after the first
 * failure, and for a file whose whole purpose is to be shown to fail, one bite has to be able to report on
 * every case it reaches.
 *
 * Each case therefore establishes the state it needs, or ASSERTS that state where establishing it is
 * impossible. Three of them solve, and the at-risk case needs no solve. The first case is the one
 * exception and it says so in place: it measures the week the SEED leaves, which nothing can restore once
 * another case has solved, so it asserts that the week is unsolved and fails there rather than quietly
 * reporting a different week's figures. */

/* Every figure a floor reservation can move. Compared as one value, so a case asserting "unchanged"
 * cannot pass by looking at the one field that happened not to move.
 *
 * THE CONCESSIONS ARE NOT IN HERE, and the reason is a difference between two surfaces rather than a
 * field that does not matter. A week's read answers the offers beside the verdict; the pin route answers
 * a bare probe verdict and enumerates none, so a comparison over all four fields reports that difference
 * as though the pin had caused it. `withOffers` is what compares two readings from the same surface. */
const comparable = (verdict: Verdict | null): string =>
  JSON.stringify({
    capacityIsSufficient: verdict?.capacityIsSufficient,
    discretionaryMinutes: verdict?.discretionaryMinutes,
    shortfalls: verdict?.shortfalls,
  });

/** The same figures plus the concessions offered against them, for two readings of the week's own read. */
const withOffers = (verdict: Verdict | null): string =>
  JSON.stringify({ verdict: comparable(verdict), tradeoffs: verdict?.tradeoffs });

const FLOOR_KINDS: readonly string[] = ["floors_exceed_capacity", "area_floor_unreachable"];

/** `5h`, `1h20m`, `45m`, `0m`: the one rendering the domain gives a duration wherever it names one. */
const renderedMinutes = (rendered: string): number => {
  const parts = /^(?:(\d+)h)?(?:(\d+)m)?$/.exec(rendered);
  if (!parts || (parts[1] === undefined && parts[2] === undefined)) {
    throw new Error(`${rendered} is not a duration this product renders`);
  }
  return Number(parts[1] ?? 0) * 60 + Number(parts[2] ?? 0);
};

/** What the week said it had left before the deadline, read back out of the gap's honored constraints. */
const capacityItMeasured = (shortfall: Verdict["shortfalls"][number]): number => {
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

/* THE FIXTURE'S OWN PREMISE, and the one case here that measures the week before anything acts on it.
 * Every figure is imported from the fixture rather than restated, so a change to the frame moves the
 * fixture and this case together instead of leaving one of them behind. */
test("the tight-capacity week owes more before its deadline than it can hold, before any pin", async ({
  api,
}) => {
  const week = planWeek();
  const seeded = await weekView(api, week);

  // THE WEEK THIS FIXTURE IS, pinned once against the figure this file's own prose, the fixture's header
  // and `docs/smoke-scenarios.md` each state. Everything below is derived from the declarations, so a
  // frame change moves the fixture and the derivation together and would rot those three copies while
  // reaching nothing that fails. This is the one place that fails instead.
  expect([DISCRETIONARY_MINUTES, CAREER_FLOOR_MINUTES + FITNESS_FLOOR_MINUTES]).toEqual([
    1470, 960,
  ]);

  // THE STATE THE FIGURES BELOW ARE EXACT IN, ASSERTED RATHER THAN ASSUMED: the week as the seed leaves
  // it, materialized and not yet solved, with nothing pinned. A run that reached this case after another
  // one had solved would be measuring a different week, and has to fail here rather than there.
  expect(
    seeded.live!.emptySlots.length,
    "every slot holds content, so this week has already been solved",
  ).toBeGreaterThan(0);
  expect(
    seeded.live!.blocks.filter((block) => block.origin !== "frame"),
    "the week holds placed content, so this week has already been solved",
  ).toEqual([]);
  expect(seeded.verdict!.discretionaryMinutes).toBe(DISCRETIONARY_MINUTES);

  // THE OBSERVATION: one gap, and it is the deadline's. The whole set is compared rather than searched,
  // so a floor shortfall appearing here fails instead of hiding behind the one being looked for.
  const gaps = seeded.verdict!.shortfalls;
  expect(gaps.map((gap) => gap.kind)).toEqual(["deadline_capacity"]);
  expect(gaps[0]!.minutes).toBe(PRE_DEADLINE_SHORTFALL_MINUTES);
  expect(gaps[0]!.against).toEqual([DEADLINE_TASK]);
  expect(seeded.verdict!.capacityIsSufficient).toBe(false);

  // And the gap is that size for the reason the fixture says it is: BOTH sides of the comparison are
  // checked, because a demand against some other capacity that happened to differ by one chunk would
  // satisfy the figure above while meaning something else entirely.
  expect(capacityItMeasured(gaps[0]!)).toBe(PRE_DEADLINE_MINUTES);

  // A solve does not close it. What the week cannot hold before that instant is capacity rather than a
  // placement, so a shortfall a pin can move survives into the solved week the other cases read. It can
  // only have GROWN: both sides of the comparison are net of the deadline task's own placements, so
  // placing that task before its deadline leaves the gap where it was, and placing anything else there
  // takes from the capacity side alone.
  await solveAndSettle(api, week);
  const solved = await weekView(api, week);
  expect(solved.verdict!.shortfalls.map((gap) => gap.kind)).toEqual(["deadline_capacity"]);
  expect(solved.verdict!.shortfalls[0]!.minutes).toBeGreaterThanOrEqual(
    PRE_DEADLINE_SHORTFALL_MINUTES,
  );

  // And what the solve leaves free is less than the floors it met, which is the property the two netting
  // rules are told apart by: the immovable-only rule reserves all 960 against this remainder.
  const placed = solved
    .live!.blocks.filter((block) => block.origin !== "frame")
    .reduce(
      (total, block) =>
        total + (Date.parse(block.interval.end) - Date.parse(block.interval.start)) / 60_000,
      0,
    );
  const areas = await api.get<{ areas: readonly { floorHours: number }[] }>("/api/v1/areas");
  const declaredFloorMinutes = areas.areas.reduce(
    (total, area) => total + Number(area.floorHours) * 60,
    0,
  );
  expect(
    DISCRETIONARY_MINUTES - placed,
    "the solve leaves more free than the floors reserve, so the two netting rules agree here",
  ).toBeLessThan(declaredFloorMinutes);
});

test("B1 a solved week whose floors are met by unpinned blocks reports no floor shortfall", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);
  const view = await weekView(api, week);

  // THE PRECONDITION, ASSERTED RATHER THAN ASSUMED: every Area that declares a floor has that floor met
  // by blocks the solver placed and nobody pinned. That is what a healthy solved week IS, and it is the
  // state under which the pre-B1 rule reported a gap.
  const areas = await api.get<{
    areas: readonly { id: string; name: string; floorHours: number }[];
  }>("/api/v1/areas");
  const floored = areas.areas.filter((area) => Number(area.floorHours) > 0);
  expect(
    floored.length,
    "no Area declares a floor, so there is nothing to reserve",
  ).toBeGreaterThan(0);
  for (const area of floored) {
    const placed = view.live!.blocks.filter((block) => block.areaId === area.id);
    const minutes = placed.reduce(
      (total, block) =>
        total + (Date.parse(block.interval.end) - Date.parse(block.interval.start)) / 60_000,
      0,
    );
    expect(
      minutes,
      `${area.name} declares a floor of ${area.floorHours}h and holds ${minutes} placed minutes`,
    ).toBeGreaterThanOrEqual(Number(area.floorHours) * 60);
    expect(
      placed.every((block) => !block.pinned),
      `${area.name}'s floor is met partly by pinned blocks, so this is not the case B1 is about`,
    ).toBe(true);
  }

  // And the week is tight: the reservation and the free capacity are close enough that the difference
  // between the two netting rules is visible. Without this the case could pass on a roomy week again.
  const declaredFloorMinutes = floored.reduce(
    (total, area) => total + Number(area.floorHours) * 60,
    0,
  );
  expect(
    view.verdict!.discretionaryMinutes,
    "the week is too roomy for a floor reservation to be observable",
  ).toBeLessThan(declaredFloorMinutes * 3);

  // THE OBSERVATION: no floor shortfall on a week whose floors are already scheduled. The deadline gap
  // the fixture carries is the whole of what is left, so the set is compared rather than searched: a
  // floor shortfall cannot appear here without failing, and neither can a fifth kind nobody expected.
  const kinds = view.verdict!.shortfalls.map((shortfall) => shortfall.kind);
  for (const kind of FLOOR_KINDS) expect(kinds).not.toContain(kind);
  expect(kinds).toEqual(["deadline_capacity"]);
});

test("B1 the at-risk column names only tasks the verdict it reads reports a shortfall for", async ({
  api,
}) => {
  // The marking reads the current week's verdict, so that is the verdict it is crossed against.
  const verdict = await api.get<{ verdict: Verdict }>(`/api/v1/weeks/${currentWeek()}/verdict`);
  const named = new Set(
    verdict.verdict.shortfalls
      .filter((shortfall) => shortfall.kind === "deadline_capacity")
      .flatMap((shortfall) => shortfall.against),
  );

  const backlog = await api.get<{
    header: { atRiskCount: number };
    tasks: readonly { title: string; atRisk: boolean }[];
  }>("/api/v1/tasks");
  const atRisk = backlog.tasks.filter((task) => task.atRisk).map((task) => task.title);

  // Set equality both ways. One direction catches a column inflated past what the verdict found; the
  // other catches a task the verdict named and the column did not mark, which is the same guarantee read
  // from the other end: a task cannot be at risk on one screen and fine on another.
  expect([...atRisk].sort()).toEqual([...named].sort());
  expect(backlog.header.atRiskCount).toBe(atRisk.length);
  expect(
    atRisk.length,
    "no task is at risk, so this comparison has nothing to iterate",
  ).toBeGreaterThan(0);
});

test("B1 pinning an already-placed block leaves the verdict unchanged", async ({ api }) => {
  const week = planWeek();
  await solveAndSettle(api, week);
  const before = await weekView(api, week);
  const floored = before.live!.blocks.find(
    (block) => block.areaId !== null && !block.pinned && block.origin !== "frame",
  );
  expect(floored, "the week holds no unpinned block carrying an Area").toBeDefined();

  const reading = comparable(before.verdict);
  const offered = withOffers(before.verdict);

  // Pinned WHERE IT ALREADY IS, which is also how rejecting a proposed move is implemented. It frees
  // nothing and commits nothing, so nothing the verdict reads may move. Under the pre-B1 rule the pin
  // makes the block immovable, the reservation falls, and the pin IMPROVES the verdict.
  const pinned = await api.post<{ verdict: Verdict }>(`/api/v1/weeks/${week}/pins`, {
    blockId: floored!.id,
    start: floored!.interval.start,
  });

  expect(comparable(pinned.verdict)).toBe(reading);
  const after = await weekView(api, week);
  expect(withOffers(after.verdict)).toBe(offered);
});

/* S34 IS EXPECTED TO FAIL, and it is written as an assertion rather than as a skip so that the day the
 * figure is fixed this case goes red for passing unexpectedly and the marker has to be removed.
 *
 * The strip's `unallocatedMinutes` and `discretionaryMinutes` are both the whole week's span: the
 * denominator is missing the frame, the anchors and the absolutely forbidden windows, so a week that
 * sleeps for 56 hours reports 168 discretionary hours and every one of them unallocated. Tracking
 * ticket: 1310. */
test("S34 Unallocated is honest: it equals the discretionary time no block covers", async ({
  api,
}) => {
  test.fail(true, "the strip's discretionary denominator is not yet supplied: ticket 1310");
  const week = planWeek();
  const view = await weekView(api, week);
  const readings = view.readings!;

  // A week that sleeps cannot have a discretionary span equal to the whole week.
  const wholeWeek = 7 * 24 * 60;
  expect(readings.discretionaryMinutes).toBeLessThan(wholeWeek);

  // Unallocated is what no block covers, so it is less than the discretionary span once anything with an
  // Area is placed, and never negative.
  expect(readings.unallocatedMinutes).toBeLessThan(readings.discretionaryMinutes);
  expect(readings.unallocatedMinutes).toBeGreaterThanOrEqual(0);

  // The verdict's own discretionary figure is computed by the probe over the same inputs, so the two
  // surfaces must agree: a week cannot be starving on one screen and fine on another.
  expect(readings.discretionaryMinutes).toBe(view.verdict!.discretionaryMinutes);
});
