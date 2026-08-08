/* S30: approving during a solve supersedes rather than adopting. S35: verdict transitions are recorded
 * exactly once, reads write nothing, and the ratio is a number.
 *
 * `elastic_sleep`, because both need a week whose verdict can be MOVED: S30 needs a pending proposal
 * to approve, and S35 needs the feasibility reading to flip on demand. A concession is what flips it,
 * and deleting the concession flips it back, which is how the two episodes S35 counts are produced
 * without waiting for a clock.
 *
 * S30 IS DRIVEN WITHOUT A RACE. Its wording ("approve the pending proposal before the solve finishes")
 * reads as a timing window, and it is not one: an approval bumps the input version, and a solve
 * claimed against an older version fails its conditional write whenever it runs. So the sequence is
 * ordered rather than timed, and the observation is the same one.
 */

import { test, expect, usingFixture } from "./harness.ts";
import { verdictEvents, tickHorizon, type VerdictEventRow } from "../src/harness/compose.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import {
  awaitProposal,
  awaitTerminal,
  solveAndSettle,
  solveNow,
  until,
  weekView,
} from "../src/harness/week.ts";

usingFixture("elastic_sleep");
test.describe.configure({ mode: "serial" });

const rowsFor = async (isoWeek: string): Promise<readonly VerdictEventRow[]> =>
  (await verdictEvents()).rows.filter((row) => row.isoWeek === isoWeek);

test("S30 an approval is the plan of record, and no solve stamped before it is allowed to succeed", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);

  const solved = await weekView(api, week);
  const offered = solved.verdict!.tradeoffs.find((each) => each.kind === "drop_item");
  expect(offered, "the week offers no tradeoff to propose").toBeDefined();
  await api.post(`/api/v1/weeks/${week}/tradeoffs`, {
    kind: offered!.kind,
    targetId: offered!.targetId,
  });
  const proposal = await awaitProposal(api, week);

  // A solve outstanding at the moment of the approval.
  const outstanding = await solveNow(api, week);

  const approved = await api.post<{ revisionId: string; inputVersion: number }>(
    `/api/v1/weeks/${week}/approve`,
    undefined,
    { idempotencyKey: `s30-approve-${week}` },
  );
  expect(approved.inputVersion).toBeGreaterThan(proposal.inputVersion);

  const settled = await awaitTerminal(api, outstanding.id, 40_000);

  // THE INVARIANT, STATED OVER THE VERSION RATHER THAN OVER A TIMING WINDOW. `input_version` is
  // stamped when a solve LOADS its inputs, so a solve that loaded AFTER the approval reads the
  // approved plan and succeeding is correct. What must never happen is the outstanding solve
  // succeeding while stamped BEFORE the approval, because its candidate was computed against a plan
  // the user has since replaced. Which of the two this run produced depends on when the worker
  // claimed it, so both readings are stated and only one of them is an error.
  //
  // The narrower interleaving, where the solve is already RUNNING when the approval lands, is not
  // reachable from outside the worker: it is covered where the claim can be controlled, in
  // `packages/syncr-api/tests/test_approval_during_a_solve.py`.
  if (settled.inputVersion != null && settled.inputVersion < approved.inputVersion) {
    expect(
      settled.status,
      `the solve was stamped at version ${settled.inputVersion}, before the approval reached ` +
        `${approved.inputVersion}, and still reports ${settled.status}`,
    ).not.toBe("succeeded");
  } else {
    expect(settled.inputVersion).toBeGreaterThanOrEqual(approved.inputVersion);
  }

  // The approved revision is the plan of record, and nothing proposes undoing it.
  const after = await weekView(api, week);
  expect(after.adjustments.map((each) => each.kind)).toContain(offered!.kind);
  const proposesUndoing = (after.proposal?.added ?? []).some(
    (change) => change.binding.entityId === offered!.targetId,
  );
  expect(proposesUndoing).toBe(false);
});

test("S35 a read appends no verdict event, and a burst that changes no verdict appends none either", async ({
  api,
}) => {
  const week = planWeek();
  const before = await rowsFor(week);

  // Two reads, because a write only the FIRST read would make would be invisible to one.
  await weekView(api, week);
  await weekView(api, week);
  await api.get(`/api/v1/weeks/${week}/verdict`);
  expect((await rowsFor(week)).length).toBe(before.length);

  // A tick with nothing changed appends none.
  await tickHorizon();
  expect((await rowsFor(week)).length).toBe(before.length);
});

test("S35 every row is a transition, and the ratio the product reads is the episode ratio", async ({
  api,
}) => {
  const week = planWeek();

  // The week is infeasible and has been since the maintainer first probed it, so an episode is already
  // open and it was NOT discovered during a weekly session.
  const opened = await rowsFor(week);
  expect(opened.length, "no verdict transition has been recorded for this week").toBeGreaterThan(0);
  expect(opened[0]!.feasible).toBe(false);
  expect(opened[0]!.sessionModeActive).toBe(false);
  expect(opened[0]!.surface).toBe("maintainer");

  // Close it: the week holds an approved concession from the previous case, and the approval that
  // persisted it is the act that recorded the feasible transition.
  const held = await weekView(api, week);
  expect(held.adjustments.length).toBeGreaterThan(0);
  const closed = await until(
    `${week} to record a feasible transition`,
    () => rowsFor(week),
    (rows) => rows.some((row) => row.feasible),
  );
  expect(closed.at(-1)!.feasible).toBe(true);

  // Open a second episode: withdrawing the concession puts the shortfall back.
  const adjustment = held.adjustments[0]!;
  await api.del(`/api/v1/weeks/${week}/adjustments/${adjustment.id}`, { sessionMode: true });
  const reopened = await until(
    `${week} to record a second infeasible transition`,
    () => rowsFor(week),
    (rows) => !rows.at(-1)!.feasible,
  );

  // Recorded exactly once each. Two consecutive rows may report the same READING, because a probe
  // transition followed by a solver confirmation of it writes two deliberately: the second is a
  // change of provenance, which is a stronger claim about the same reading. What must never appear is
  // two consecutive rows agreeing on both, which is an identical recomputation being recorded twice.
  for (let index = 1; index < reopened.length; index += 1) {
    const previous = reopened[index - 1]!;
    const current = reopened[index]!;
    expect(
      current.feasible === previous.feasible && current.provenance === previous.provenance,
      `rows ${index - 1} and ${index} agree on both the reading and its provenance, so one of them ` +
        "is an identical recomputation rather than a transition",
    ).toBe(false);
  }

  // TWO EPISODES, COUNTED AS EPISODES RATHER THAN AS ROWS, and that distinction is the whole point of
  // the metric: this week's history holds more infeasible ROWS than episodes, because a probe reading and
  // the solver's confirmation of it are two rows about one discovery.
  expect(reopened.at(-1)!.feasible, "the second episode is not open").toBe(false);
  expect(reopened.filter((row) => !row.feasible).length).toBeGreaterThan(2);

  // What is invariant TODAY, and what a fix must not break: the ratio is a number in [0, 1], and no
  // episode this suite can open carries a session flag. The second clause is the defect, so it is stated
  // as the defect rather than as the correct answer.
  const measured = await verdictEvents();
  const ratios = Object.values(measured.caughtEarlyByTenant);
  expect(ratios.length).toBe(1);
  expect(ratios[0]).not.toBeNull();
  expect(ratios[0]!).toBeGreaterThanOrEqual(0);
  expect(ratios[0]!).toBeLessThanOrEqual(1);
  expect(reopened.some((row) => row.sessionModeActive)).toBe(false);
});

/* S35's stated figure, AS A TRIPWIRE, so its polarity matches S34's rather than opposing it.
 *
 * Spec S35 requires a ratio of exactly 0.5 over one session-caught episode and one that was not. This
 * suite cannot construct the session-caught one: two routes read `X-Syncr-Session-Mode`, the pin and the
 * tradeoff request, and neither is a mutation that flips a roomy week's reading. So the figure is asserted
 * and the case is marked as expected to fail, which means the day ticket 1571 makes it constructible the
 * suite goes red for passing unexpectedly and the marker has to be removed.
 *
 * Written this way deliberately. Asserting the 0 the defect produces would lock the defect in with the
 * opposite polarity from S34, in the same suite, for the same kind of fact: one instrument would
 * celebrate what the other condemns. */
test("S35 the early-catch ratio over one session-caught episode and one that was not is exactly 0.5", async () => {
  test.fail(true, "no route that flips a verdict carries the session header: ticket 1571");
  const measured = await verdictEvents();
  const ratios = Object.values(measured.caughtEarlyByTenant);
  expect(ratios[0]).toBe(0.5);
});
