/* The Blocker 1 scenario, and S34.
 *
 * Both are about a figure that is right or wrong rather than present or absent, which is the class of
 * failure this product cannot detect any other way: neither throws, and both render plausibly.
 *
 * The B1 scenario has no scenario number in section 20 because it is not one of the 37. It is the
 * observation `reviews/spec-review-5.md` B1 requires, and it exists because the probe's floor
 * reservation and its `free` capacity once netted different placement sets: a healthy solved week's
 * floors are met by UNPINNED solver-placed blocks, so a reservation that did not net them reported a
 * `floors_exceed_capacity` gap on the normal state of the product, and pinning an already-placed block
 * IMPROVED the verdict. Both halves are asserted here.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Verdict } from "../src/api/schemas.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { solveAndSettle, weekView } from "../src/harness/week.ts";

usingFixture("reference_week");
test.describe.configure({ mode: "serial" });

const comparable = (verdict: Verdict | null): string =>
  JSON.stringify({
    capacityIsSufficient: verdict?.capacityIsSufficient,
    shortfalls: verdict?.shortfalls,
    discretionaryMinutes: verdict?.discretionaryMinutes,
  });

test("B1 a healthy solved week reports no floor shortfall, and its at-risk column is not inflated", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);
  const view = await weekView(api, week);

  // The week is healthy in exactly the sense B1 names: its floors are met by blocks the solver placed
  // and nobody pinned.
  const areas = await api.get<{ areas: readonly { id: string; name: string; floorHours: number }[] }>(
    "/api/v1/areas",
  );
  const withFloors = areas.areas.filter((area) => Number(area.floorHours) > 0);
  expect(withFloors.length, "no Area declares a floor, so there is nothing to reserve").toBeGreaterThan(0);
  for (const area of withFloors) {
    const placed = view.live!.blocks.filter((block) => block.areaId === area.id);
    expect(placed.length, `${area.name} declares a floor and holds no block`).toBeGreaterThan(0);
    expect(
      placed.some((block) => !block.pinned),
      `${area.name}'s floor is met only by pinned blocks, so this week is not the healthy case`,
    ).toBe(true);
  }

  const kinds = view.verdict!.shortfalls.map((shortfall) => shortfall.kind);
  expect(kinds).not.toContain("floors_exceed_capacity");
  expect(kinds).not.toContain("area_floor_unreachable");

  // The backlog's at-risk marking is pinned to the probe reporting a `deadline_capacity` shortfall
  // naming the task, so an inflated reservation shows up here too.
  const backlog = await api.get<{ tasks: readonly { title: string; atRisk: boolean }[] }>(
    "/api/v1/tasks",
  );
  const atRisk = backlog.tasks.filter((task) => task.atRisk).map((task) => task.title);
  const named = view.verdict!.shortfalls.flatMap((shortfall) => shortfall.against);
  for (const title of atRisk) {
    expect(named, `${title} is marked at risk and no shortfall names it`).toContain(title);
  }
});

test("B1 pinning an already-placed block leaves the verdict unchanged", async ({ api }) => {
  const week = planWeek();
  const before = await weekView(api, week);
  const floored = before.live!.blocks.find(
    (block) => block.areaId !== null && !block.pinned && block.origin !== "frame",
  );
  expect(floored, "the week holds no unpinned block carrying an Area").toBeDefined();

  const reading = comparable(before.verdict);

  // Pinned WHERE IT ALREADY IS, which is also how rejecting a proposed move is implemented. It frees
  // nothing and commits nothing, so the arithmetic behind the verdict must not move.
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

  // Unallocated is what no block covers, so it is the discretionary span less the scheduled minutes
  // that carry an Area, and it is never the whole of it once anything is placed.
  expect(readings.unallocatedMinutes).toBeLessThan(readings.discretionaryMinutes);
  expect(readings.unallocatedMinutes).toBeGreaterThanOrEqual(0);

  // The verdict's own discretionary figure is computed by the probe over the same inputs, so the two
  // surfaces must agree: a week cannot be starving on one screen and fine on another.
  expect(readings.discretionaryMinutes).toBe(view.verdict!.discretionaryMinutes);
});
