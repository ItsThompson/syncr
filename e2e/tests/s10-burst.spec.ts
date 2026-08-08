/* S10: a burst costs one solve.
 *
 * Its own file, and not because of length. A bite that breaks the solve pipeline anywhere makes this
 * case hang on its drain, and in a serial file that would take the identity cases down with it: a bite
 * has to be able to turn ONE case red. Measured, on a bite of the authority classifier.
 */

import { test, expect, usingFixture } from "./harness.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { operationsFor, solveAndSettle, until, weekView } from "../src/harness/week.ts";

usingFixture("reference_week");

const BURST = 12;

/* The two origins the solver CHOSE the placement of, which are the only ones a pin can move. */
const CHOSEN_BY_THE_SOLVER: readonly string[] = ["task", "habit"];

const nonTerminal = (status: string): boolean => status === "pending" || status === "running";

test("S10 twelve pins cost one solve, zero live revisions and zero calendar writes", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);

  const solved = await weekView(api, week);
  const movable = solved.live!.blocks.filter(
    (block) => CHOSEN_BY_THE_SOLVER.includes(block.origin) && !block.pinned,
  );
  expect(movable.length, "the solved week placed nothing a pin could move").toBeGreaterThan(0);

  const revisionsBefore = await api.get<{ revisions: readonly unknown[] }>(
    `/api/v1/weeks/${week}/revisions`,
  );
  const projectionsBefore = (await operationsFor(api, week)).filter(
    (each) => each.kind === "projection",
  ).length;

  // The burst. Debounced, not immediate: this is the shape a weekly session produces, and the debounce
  // is the mechanism under test.
  let mostSolvesInFlight = 0;
  for (let pin = 0; pin < BURST; pin += 1) {
    const block = movable[pin % movable.length]!;
    const shifted = new Date(Date.parse(block.interval.start) + (pin + 1) * 15 * 60_000);
    const reply = await api.attempt("POST", `/api/v1/weeks/${week}/pins`, {
      blockId: block.id,
      start: shifted.toISOString(),
    });
    // A pin the week cannot hold is refused, and a refusal is not a burst member: what matters is that
    // every ACCEPTED pin coalesced.
    if (reply.status >= 400) continue;
    const inFlight = (await operationsFor(api, week)).filter(
      (each) => each.kind === "solve" && nonTerminal(each.status),
    ).length;
    mostSolvesInFlight = Math.max(mostSolvesInFlight, inFlight);
    expect(
      inFlight,
      `after ${pin + 1} pins the week held ${inFlight} solves at once`,
    ).toBeLessThanOrEqual(1);
  }
  expect(mostSolvesInFlight, "no solve was ever scheduled by the burst").toBe(1);

  await until(
    "the burst's solve to drain",
    () => operationsFor(api, week),
    (seen) => seen.every((each) => !nonTerminal(each.status)),
  );

  const settled = await operationsFor(api, week);
  const superseded = settled.filter((each) => each.status === "superseded");
  expect(
    superseded.length,
    "a coalesced burst supersedes at most one operation",
  ).toBeLessThanOrEqual(1);

  // Zero live revisions, and zero calendar writes. A diff holding a move is held whole, so nothing
  // auto-applies and nothing is enqueued to project.
  const revisionsAfter = await api.get<{ revisions: readonly unknown[] }>(
    `/api/v1/weeks/${week}/revisions`,
  );
  expect(revisionsAfter.revisions.length).toBe(revisionsBefore.revisions.length);
  const projectionsAfter = settled.filter((each) => each.kind === "projection").length;
  expect(projectionsAfter).toBe(projectionsBefore);
});
