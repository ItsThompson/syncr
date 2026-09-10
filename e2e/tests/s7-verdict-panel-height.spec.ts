/* S7: the verdict panel's height across a sequence of pins.
 *
 * WHY THIS CASE EXISTS ONLY AT THE BROWSER TIER. The panel's height is a CSS correctness rule
 * (`verdict.css`): `--verdict-h` is reserved whatever the rows say, so accumulating shortfall and
 * offer rows never shift the grid under the cursor mid-drag. Nothing static can observe it -- a
 * component suite reads the stylesheet it just wrote -- so the observation is a `boundingBox()`
 * over the rendered screen.
 *
 * WHY `tight_capacity`. A height that never moved because nothing happened would read as a pass, so
 * the sequence has to run on a week whose panel the pins actually change. This week reports a
 * `deadline_capacity` shortfall, and its solved verdict enumerates tradeoff offers. Measured product
 * behaviour the sequence has to account for: a pin answers a bare probe verdict that enumerates no
 * concessions, and the re-solve it schedules leaves a pending proposal about five seconds later
 * whose stored verdict every later read serves, which enumerates none either. So the panel LOSES its
 * offer rows and gains the no-remedy statement at the FIRST pin and keeps them lost while each
 * proposal stands, rather than recovering between pins. The row count therefore changes across the
 * sequence while the height may not, and this case asserts both.
 */

import type { Page } from "@playwright/test";

import { test, expect, usingFixture } from "./harness.ts";
import type { ApiClient } from "../src/api/client.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { awaitProposal, operationsFor, until, weekView } from "../src/harness/week.ts";

usingFixture("tight_capacity");
test.describe.configure({ mode: "serial" });

const PINS = 3;

const PANEL = ".verdict-panel";
const ROW = ".verdict-panel__row";

/** The origins the solver CHOSE the placement of, which are the ones a pin can move. */
const CHOSEN_BY_THE_SOLVER: readonly string[] = ["task", "habit"];

interface PanelReading {
  /** `boundingBox().height` of the whole panel, head and rows together. */
  readonly height: number;
  /** Every row the panel drew: concessions, shortfalls, offers and statements alike. */
  readonly rows: readonly string[];
}

/** Load the week screen fresh and read the panel off it.
 *
 * A FRESH LOAD PER READING, because the reading has to be of the state the pin left rather than of
 * whatever the screen was holding. The wait is for the panel itself: it is drawn only once the
 * screen's read has landed with a verdict, so visibility is what settles the fetch. */
const readPanel = async (page: Page): Promise<PanelReading> => {
  const week = planWeek();
  await page.goto(`/week?week=${week}`);
  const panel = page.locator(PANEL);
  await expect(panel, "the week screen drew no verdict panel").toBeVisible();
  const box = await panel.boundingBox();
  expect(box, "the verdict panel rendered with no box to measure").not.toBeNull();
  return { height: box!.height, rows: await page.locator(ROW).allTextContents() };
};

/** One accepted pin of an unpinned solver-placed block, shifted a quarter hour inside its slot. */
const pinSomething = async (api: ApiClient): Promise<void> => {
  const week = planWeek();
  const view = await weekView(api, week);
  const movable = view.live!.blocks.find(
    (block) => CHOSEN_BY_THE_SOLVER.includes(block.origin) && !block.pinned,
  );
  expect(movable, "the week holds no unpinned block a pin could move").toBeDefined();
  const shifted = new Date(Date.parse(movable!.interval.start) + 15 * 60_000).toISOString();
  const reply = await api.attempt("POST", `/api/v1/weeks/${week}/pins`, {
    blockId: movable!.id,
    start: shifted,
  });
  expect(reply.status, `the pin was refused: ${JSON.stringify(reply.body)}`).toBe(201);
};

/** Solve the week and wait for the placements to exist, rather than for one operation to win.
 *
 * WHY NOT `solveAndSettle`. The seed's maintainer tick can leave a debounced solve due on this
 * week, and when it fires beside the immediate one, whichever lands second supersedes the first:
 * `succeeded` and `superseded` are both outcomes of ONE solved week, and adjudicating which
 * operation carried it makes the case read a scheduling coincidence as a failure. What the panel's
 * readings need is the state, so that is what is waited for: a live plan holding blocks the solver
 * placed, which is the marker `b1-s34-floors-and-unallocated.spec.ts` reads the same way. */
const solveToPlacements = async (api: ApiClient): Promise<void> => {
  const week = planWeek();
  const reply = await api.attempt("POST", `/api/v1/weeks/${week}/solve?immediate=true`);
  expect(reply.status, `the solve was refused: ${JSON.stringify(reply.body)}`).toBeLessThan(400);
  await until(
    `${week} to hold solver-placed blocks`,
    () => weekView(api, week),
    (seen) => seen.live?.blocks.some((block) => block.origin !== "frame") ?? false,
  );
};

test("S7 the verdict panel keeps its height across a sequence of pins while its rows change", async ({
  api,
  page,
}) => {
  const week = planWeek();
  await solveToPlacements(api);

  // THE PRECONDITION THE ROW-COUNT ASSERTION DEPENDS ON: the solved verdict enumerates offers, so
  // the first pin's proposal takes rows away. Without this a fixture that stopped enumerating them
  // would fail the row-count assertion below without saying why.
  const beforeAnyPin = await weekView(api, week);
  expect(
    beforeAnyPin.verdict!.tradeoffs.length,
    "the solved week enumerates no tradeoff offers, so no pin can change the panel's rows",
  ).toBeGreaterThan(0);
  expect(
    beforeAnyPin.verdict!.shortfalls.length,
    "the solved week reports no shortfall, so there is no live infeasibility to hold stable",
  ).toBeGreaterThan(0);

  const readings: PanelReading[] = [await readPanel(page)];

  for (let pin = 1; pin <= PINS; pin += 1) {
    await pinSomething(api);

    // THE STATE EACH READING IS OF: every operation the pin scheduled has settled, and the pending
    // proposal its re-solve left stands. That is the state whose served verdict enumerates no
    // concessions, so the reading below is of one branch on both sides rather than of whichever
    // answer a mid-drain moment happens to serve.
    await until(
      `${week}'s operations to drain after pin ${pin}`,
      () => operationsFor(api, week),
      (seen) => seen.every((each) => !["pending", "running"].includes(each.status)),
    );
    await awaitProposal(api, week);

    readings.push(await readPanel(page));
  }

  // THE OBSERVATION, FIRST HALF: the height never moved, across the reading before any pin and the
  // reading after each of the three. Compared exactly: the height is a declared token, not a
  // measurement of wrapped text, so two readings of one panel differ by nothing at all.
  const [first] = readings;
  // THE FIRST READING IS THE BASELINE, SO IT IS NOT COMPARED TO ITSELF: the loop starts at the
  // reading after the first pin.
  for (let index = 1; index < readings.length; index += 1) {
    expect(
      readings[index]!.height,
      `reading ${index} (after ${index} pins) measured a different panel height from the first`,
    ).toBe(first!.height);
  }

  // THE OBSERVATION, SECOND HALF, AND WHY THE FIRST CANNOT PASS ON NOTHING: the rendered rows DID
  // change across the same sequence, and stayed changed at every reading after a pin. Count is not
  // the contract: one offer can be replaced by one statement. A fixed height held over four readings
  // of an untouched panel satisfies the loop above; it cannot satisfy this content comparison.
  for (let index = 1; index < readings.length; index += 1) {
    expect(
      readings[index]!.rows,
      `reading ${index} (after ${index} pins) still drew the pre-pin rows`,
    ).not.toEqual(first!.rows);
  }
});
