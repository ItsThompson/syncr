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
 * blocks, with only 210 minutes left free, so a reservation that netted nothing would be 960 against 210
 * and would report a shortfall on a week that is fully scheduled.
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

usingFixture("tight_capacity");

/* NOT serial, deliberately, even though the cases share a week. Each is self-sufficient about the state
 * it needs: the first two solve, the third reads a verdict and a backlog that need no solve. Serial mode
 * would stop after the first failure, and for a file whose whole purpose is to be shown to fail, one
 * bite has to be able to report on every case it reaches. */

/* Every figure a floor reservation can move. Compared as one value, so a case asserting "unchanged"
 * cannot pass by looking at the one field that happened not to move. */
const comparable = (verdict: Verdict | null): string =>
  JSON.stringify({
    capacityIsSufficient: verdict?.capacityIsSufficient,
    discretionaryMinutes: verdict?.discretionaryMinutes,
    shortfalls: verdict?.shortfalls,
    tradeoffs: verdict?.tradeoffs,
  });

const FLOOR_KINDS: readonly string[] = ["floors_exceed_capacity", "area_floor_unreachable"];

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

  // THE OBSERVATION: no floor shortfall on a week whose floors are already scheduled.
  const kinds = view.verdict!.shortfalls.map((shortfall) => shortfall.kind);
  for (const kind of FLOOR_KINDS) expect(kinds).not.toContain(kind);
  expect(view.verdict!.capacityIsSufficient).toBe(true);
  expect(view.verdict!.shortfalls).toEqual([]);
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

  // Pinned WHERE IT ALREADY IS, which is also how rejecting a proposed move is implemented. It frees
  // nothing and commits nothing, so nothing the verdict reads may move. Under the pre-B1 rule the pin
  // makes the block immovable, the reservation falls, and the pin IMPROVES the verdict.
  const pinned = await api.post<{ verdict: Verdict }>(`/api/v1/weeks/${week}/pins`, {
    blockId: floored!.id,
    start: floored!.interval.start,
  });

  expect(comparable(pinned.verdict)).toBe(reading);
  const after = await weekView(api, week);
  expect(comparable(after.verdict)).toBe(reading);
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
