/* A scenario drives the first solve of a week already lived.
 *
 * SR-DEPLOY-01 proved at the api tier that a solve of the current week succeeds and the past guard
 * stays honest. This case is the browser tier: it solves the current week on the `reference_week`
 * fixture and reads the result through the product's own rendered grid, so the fix is observed
 * through the product rather than only at the api.
 *
 * WHY THE CURRENT WEEK AND NOT THE PLAN WEEK. The plan week is entirely in the future, so a solve
 * of it never draws `past_disagreement` and the tolerance the seed used to carry was never about it.
 * The current week holds days already lived, which is exactly the state the refusal was named for:
 * a candidate that restates a started solver-placed block on a day the week has already reached.
 * SR-DEPLOY-01's fix leaves a slot on a lived day unbound (its own `EmptySlotReason`, `elapsed`),
 * so the candidate no longer restates the past and the solve succeeds.
 *
 * WHAT "THE SLOTS BIND" MEANS THROUGH THE PRODUCT. After the solve, the week holds blocks the
 * solver placed (origin `task` or `habit`) and empty slots on lived days carry `elapsed` rather
 * than `not_solved`. The browser half reads the rendered grid: a block drawn with
 * `data-origin="task"` or `data-origin="habit"` is a slot the solver bound, and it is what the
 * product shows a user rather than what the api reports to a test.
 *
 * THE PRE-FIX TREE. Before SR-DEPLOY-01's `elapsed` reason (worktree `e30e3acf`), the solve of the
 * current week was refused permanently with `past_disagreement`, so the operation never reached
 * `succeeded` and the grid held no solver-placed blocks. This case bites on that tree: the
 * `awaitTerminal` throws on `failed`, and the browser assertion finds nothing to count.
 */

import { test, expect, usingFixture } from "./harness.ts";
import { currentWeek } from "../src/harness/subject-weeks.ts";
import { awaitTerminal, solveNow, weekView } from "../src/harness/week.ts";

usingFixture("reference_week");

/* The origins a solve chooses, which is the set "the slots bind" is read from. A frame block or an
 * anchor is placed by the fixture or the feed, not by the solver, so neither counts. */
const SOLVER_PLACED: readonly string[] = ["task", "habit"];

test("a scenario drives the first solve of a week already lived and its slots bind", async ({
  api,
  page,
}) => {
  const week = currentWeek();

  // THE WEEK IS MATERIALIZED AND UNSOLVED: the horizon maintainer wrote a plan, and every block in
  // it was placed by its source because no solve has ever run. A solve has not run, so every Area
  // slot reads `not_solved`.
  const before = await weekView(api, week);
  expect(before.live, `${week} holds no plan`).not.toBeNull();
  const placedBefore = before.live!.blocks.filter((block) => SOLVER_PLACED.includes(block.origin));
  expect(placedBefore, "the fixture left this week already solved").toEqual([]);
  expect(before.live!.emptySlots.length).toBeGreaterThan(0);
  for (const slot of before.live!.emptySlots) {
    expect(slot.reason).toBe("not_solved");
  }

  // SOLVE THE CURRENT WEEK. On the pre-fix tree this is refused permanently with
  // `past_disagreement`; here it reaches `succeeded`.
  const started = await solveNow(api, week);
  const settled = await awaitTerminal(api, started.id);
  expect(settled.status, `solving ${week} ended ${settled.status}`).toBe("succeeded");

  // THE SLOTS BIND: the week now holds blocks the solver placed. A slot on a day already lived is
  // left unbound with `elapsed`, which is its own reason rather than `not_solved`, so the solve
  // succeeded without restating the past.
  const after = await weekView(api, week);
  expect(after.live, `${week} holds no plan after the solve`).not.toBeNull();
  const placedAfter = after.live!.blocks.filter((block) => SOLVER_PLACED.includes(block.origin));
  expect(
    placedAfter.length,
    "solving placed no solver-placed blocks, so no slot bound",
  ).toBeGreaterThan(0);

  // THE PAST GUARD IS NOT LOOSENED: a slot on a lived day carries `elapsed`, not `not_solved`, so
  // the success cannot be read as the solver filling time the week has already reached.
  const notSolvedSlots = after.live!.emptySlots.filter((slot) => slot.reason === "not_solved");
  expect(notSolvedSlots, "a lived-day slot reads not_solved rather than elapsed").toEqual([]);

  // THROUGH THE PRODUCT: the rendered grid shows the solver-placed blocks a user sees, not just the
  // api response a test reads. The `data-origin` attribute is what the block component paints, so a
  // block the solver placed is a block the product drew with `task` or `habit`.
  await page.goto(`/week?week=${week}`);
  await page.waitForFunction("document.querySelectorAll('body *').length > 5");
  expect(page.url(), "the week route redirected to sign-in").not.toContain("/sign-in");

  const browserPlaced = await page
    .locator("[data-origin]")
    .evaluateAll((elements) =>
      elements
        .map((element) => element.getAttribute("data-origin"))
        .filter((origin): origin is string => origin !== null && SOLVER_PLACED.includes(origin)),
    );
  expect(
    browserPlaced.length,
    "the rendered grid drew no solver-placed block, so the fix is not observed through the product",
  ).toBeGreaterThan(0);
});
