/* A scenario drives the first solve of a week already lived.
 *
 * SR-DEPLOY-01 proved at the api tier that a solve of the current week reaches `succeeded`, that the
 * slots ahead of the clock bind, and that the past guard is not loosened. This case is the browser
 * tier of the same observation: it solves the current week on the `reference_week` fixture through the
 * product's own solve route and reads the result through the rendered grid, so the fix is observed
 * through the product rather than only at the api.
 *
 * WHY THE CURRENT WEEK AND NOT THE PLAN WEEK. The plan week is entirely in the future, so a solve of
 * it never draws `past_disagreement` and the tolerance the seed used to carry was never about it. The
 * current week holds days already lived, which is exactly the state that refusal was named for: a
 * candidate that restates a started solver-placed block on a day the week has already reached.
 * SR-DEPLOY-01's fix leaves a slot the clock has reached unbound, as its own `EmptySlotReason`
 * (`elapsed`) rather than `not_solved`, so the candidate no longer restates the past and the solve
 * succeeds.
 *
 * WHAT "THE SLOTS BIND" MEANS HERE, and why it is not "every slot ahead holds content": the
 * reference week's Fitness slot is S17's deliberate unfillable case (sixty minutes declared against a
 * forty-five-minute habit), so a solved week still holds empty slots ahead of the clock. The honest
 * reading is threefold: the solve placed content of its own choosing (blocks of origin `task` or
 * `habit`), every empty slot carries a reason a solve computed rather than `not_solved` (the
 * rendering for a week nobody solved), and a slot the clock has already reached carries `elapsed` --
 * the one wording that says the day has passed, which is the escalated decision input 1570 answered.
 *
 * THE CLOCK IS THE REAL ONE, so the `elapsed` half is bounded by how far into the week today is:
 * before the first slot of Monday nothing has been reached and the half passes vacuously, which is
 * the same bound S13 states for itself. The `not_solved` half is unconditional.
 *
 * THE PRE-FIX TREE. Before SR-DEPLOY-01's `elapsed` reason (worktree `e30e3acf`), the solve of the
 * current week was refused permanently with `past_disagreement`: the horizon runner's own
 * materialization of the week never produced a plan, so the wait below times out and the case bites
 * before its solve is even asked for.
 */

import { test, expect, usingFixture } from "./harness.ts";
import { currentWeek } from "../src/harness/subject-weeks.ts";
import { awaitLivePlan, awaitTerminal, solveNow, weekView } from "../src/harness/week.ts";

usingFixture("reference_week");

/* The origins a solve chooses, which is the set "the slots bind" is read from. A frame block or an
 * anchor is placed by the fixture or the feed, not by the solver, so neither counts. */
const SOLVER_PLACED: readonly string[] = ["task", "habit"];

test("a scenario drives the first solve of a week already lived and its slots bind", async ({
  api,
  page,
}) => {
  const week = currentWeek();

  // THE MATERIALIZED PLAN, as the horizon runner's own cadence leaves it: the runner asks for a solve
  // and the worker answers on its own cadence, so the wait is a poll rather than a read. On the
  // pre-fix tree the current week never acquires a plan and this wait is where the case goes red.
  await awaitLivePlan(api, week);

  // SOLVE THE CURRENT WEEK through the product's own route. This is the half the defect lived in: a
  // candidate for a week whose days have been lived used to restate the past and be refused.
  const started = await solveNow(api, week);
  const settled = await awaitTerminal(api, started.id);
  expect(settled.status, `solving ${week} ended ${settled.status}`).toBe("succeeded");

  // THE SLOTS BIND, read through the served plan. The solve placed content of its own choosing...
  const after = await weekView(api, week);
  expect(after.live, `${week} holds no plan after the solve`).not.toBeNull();
  const placed = after.live!.blocks.filter((block) => SOLVER_PLACED.includes(block.origin));
  expect(placed.length, "solving placed no solver-placed block, so no slot bound").toBeGreaterThan(
    0,
  );

  // ...every empty slot carries a reason a solve computed rather than `not_solved`...
  const now = Date.now();
  for (const slot of after.live!.emptySlots) {
    expect(
      slot.reason,
      `a solved week left a slot at ${slot.interval.start} reading not_solved`,
    ).not.toBe("not_solved");
    // ...and a slot the clock has already reached carries `elapsed`, the reason that says the day
    // has passed rather than an answer about the backlog.
    if (Date.parse(slot.interval.start) < now) {
      expect(slot.reason, `a slot the week had lived through reads ${slot.reason}`).toBe("elapsed");
    }
  }

  // THROUGH THE PRODUCT: the rendered grid shows the blocks the solver chose, which is what a user
  // sees rather than what the api reports to a test. The `data-origin` attribute is what the block
  // component paints, so a solver-placed block is a block the product drew with `task` or `habit`.
  await page.goto(`/week?week=${week}`);
  await page.waitForFunction("document.querySelectorAll('body *').length > 5");
  expect(page.url(), "the week route redirected to sign-in").not.toContain("/sign-in");

  // The visible wait is what the SPA's own fetch is waited for: the shell renders before the week's
  // blocks arrive, so counting without it races the load.
  const drawn = page.locator('[data-origin="task"], [data-origin="habit"]');
  await expect(
    drawn.first(),
    "the rendered grid drew no solver-placed block, so the fix is not observed through the product",
  ).toBeVisible();
  expect(await drawn.count()).toBeGreaterThan(0);
});
