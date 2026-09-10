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
import {
  verdictEvents,
  tickHorizon,
  resetDatabase,
  bootstrapAccount,
  type VerdictEventRow,
} from "../src/harness/compose.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { signIn } from "../src/api/client.ts";
import { BASE_URL, E2E_EMAIL, E2E_PASSWORD } from "../src/config.ts";
import { WEDNESDAY, dateIn, utcMidnightOn } from "../src/api/weeks.ts";
import {
  declareAreas,
  declareOneDayShape,
  declareRoutine,
  declareSettings,
  declareTask,
} from "../src/seed/declarations.ts";
import {
  awaitLivePlan,
  awaitProposal,
  awaitTerminal,
  operationsFor,
  solveAndSettle,
  solveNow,
  until,
  weekView,
} from "../src/harness/week.ts";

usingFixture("elastic_sleep");
test.describe.configure({ mode: "serial" });

const rowsFor = async (isoWeek: string): Promise<readonly VerdictEventRow[]> =>
  (await verdictEvents()).rows.filter((row) => row.isoWeek === isoWeek);

type EpisodeSpan = {
  readonly opening: VerdictEventRow;
  readonly closing: VerdictEventRow | null;
};

const episodeSpans = (rows: readonly VerdictEventRow[]): readonly EpisodeSpan[] => {
  const spans: EpisodeSpan[] = [];
  let opening: VerdictEventRow | null = null;

  for (const row of rows) {
    if (!row.feasible && opening === null) {
      opening = row;
      continue;
    }
    if (row.feasible && opening !== null) {
      spans.push({ opening, closing: row });
      opening = null;
    }
  }

  if (opening !== null) spans.push({ opening, closing: null });
  return spans;
};

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

  // The week is infeasible and has been since the materialization solve first recorded it, so an
  // episode is already open and it was NOT discovered during a weekly session.
  const opened = await rowsFor(week);
  expect(opened.length, "no verdict transition has been recorded for this week").toBeGreaterThan(0);
  expect(opened[0]!.feasible).toBe(false);
  expect(opened[0]!.sessionModeActive).toBe(false);
  expect(opened[0]!.surface).toBe("solve");

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

  // The ratio is a number in [0, 1]. The second episode was opened by a withdrawal carrying the
  // session header, so its opening row is flagged: the route resolves the header and the solve's
  // recorder reads the operation's statement.
  const measured = await verdictEvents();
  const ratios = Object.values(measured.caughtEarlyByTenant);
  expect(ratios.length).toBe(1);
  expect(ratios[0]).not.toBeNull();
  expect(ratios[0]!).toBeGreaterThanOrEqual(0);
  expect(ratios[0]!).toBeLessThanOrEqual(1);
  expect(reopened.some((row) => row.sessionModeActive)).toBe(true);
});

/* S35's exactly-0.5 ratio, arranged on a world this case owns rather than inherited. The cases above
 * leave episodes behind whose COUNT depends on which weeks the horizon reached this morning (a week
 * two ahead is materialized on six days of seven and holds an overdue-task episode on each of them),
 * so reading the ratio off their state would assert a figure that moves with the calendar. Instead
 * this case empties the database, provisions its own tenant, and arranges exactly two episodes on
 * one week: a harmless routine-backed plan is materialized BEFORE the oversized task is declared,
 * so the task can only re-solve this tracked week; then a solve carrying no session header opens an
 * unflagged episode, approving the drop-item tradeoff closes it, and withdrawing that concession
 * with the header opens a flagged one. Two episodes, one flagged and one not, is exactly 0.5 through the
 * product's own `caught_early_over`, and nothing else exists to dilute it.
 *
 * The case reddens if either episode's flag moves: each episode's opening row is asserted on its
 * own, and the global ratio is asserted at exactly 0.5. */
test("S35 the early-catch ratio over one session-caught episode and one that was not is exactly 0.5", async () => {
  await resetDatabase();
  await bootstrapAccount();
  const client = await signIn(BASE_URL, E2E_EMAIL, E2E_PASSWORD);

  // A world with one Area and a harmless routine: every materialized week is feasible, so no
  // episode exists anywhere yet.
  await declareSettings(client);
  const areas = await declareAreas(client, [{ name: "Career", budgetPercent: 100, floorHours: 0 }]);
  const dayShape = await declareOneDayShape(client, "Everyday");
  await declareRoutine(client, dayShape.templateId, {
    title: "Materialization anchor",
    targetTime: "12:00:00",
    durationMinutes: 30,
  });
  const week = planWeek();
  await solveNow(client, week);
  await until(
    `${week}'s materialization operations to settle`,
    () => operationsFor(client, week),
    (operations) =>
      operations.some((operation) => operation.status === "succeeded") &&
      operations.every((operation) => !["pending", "running"].includes(operation.status)),
  );
  await awaitLivePlan(client, week);

  // The task re-solves tracked weeks only. Materializing this one plan week before declaring demand
  // keeps every other week out of the tenant-wide early-catch denominator.
  await declareTask(client, {
    title: "Ratio driver",
    areaId: areas.Career!,
    estimateMinutes: 5000,
    deadline: utcMidnightOn(dateIn(week, WEDNESDAY)),
    minChunkMinutes: 60,
    priority: "urgent",
  });

  // Episode one: a solve carrying no session header records the first infeasible reading.
  await solveAndSettle(client, week);
  const opened = await until(
    `${week} to record the first infeasible transition`,
    () => rowsFor(week),
    (rows) => rows.length > 0 && !rows.at(-1)!.feasible,
  );
  const firstEpisode = episodeSpans(opened);
  expect(firstEpisode, "the solve did not open exactly one episode").toHaveLength(1);
  expect(
    firstEpisode[0]!.opening.sessionModeActive,
    "episode one was opened without the session header",
  ).toBe(false);

  // Close it: approve the drop-item tradeoff the verdict offers.
  const solved = await weekView(client, week);
  const offered = solved.verdict!.tradeoffs.find((each) => each.kind === "drop_item");
  expect(offered, "the week offers no tradeoff to propose").toBeDefined();
  await client.post(`/api/v1/weeks/${week}/tradeoffs`, {
    kind: offered!.kind,
    targetId: offered!.targetId,
  });
  await awaitProposal(client, week);
  await client.post(`/api/v1/weeks/${week}/approve`, undefined, {
    idempotencyKey: `s35-ratio-approve-${week}`,
  });
  await until(
    `${week} to record a feasible transition`,
    () => rowsFor(week),
    (rows) => rows.some((row) => row.feasible),
  );

  // Episode two: withdraw the concession carrying the session header. The route resolves the
  // header, the operation carries the statement, and the solve's recorder reads it.
  const held = await weekView(client, week);
  expect(held.adjustments.length, "no adjustment to withdraw").toBeGreaterThan(0);
  const beforeWithdrawal = await rowsFor(week);
  await client.del(`/api/v1/weeks/${week}/adjustments/${held.adjustments[0]!.id}`, {
    sessionMode: true,
  });
  const reopened = await until(
    `${week} to record a second infeasible transition`,
    () => rowsFor(week),
    (rows) => rows.length > beforeWithdrawal.length && !rows.at(-1)!.feasible,
  );

  // An episode starts at the first infeasible row and ends at the next feasible row. This mirrors
  // the product's false-to-next-true grouping, so a feasible row before episode one cannot mask an
  // opening-row regression.
  const episodes = episodeSpans(reopened);
  expect(episodes, "the plan week must contain exactly two infeasibility episodes").toHaveLength(2);
  expect(
    episodes.map((episode) => episode.opening.sessionModeActive),
    "the two episode openings must remain unflagged then session-flagged",
  ).toEqual([false, true]);

  // The ratio the product's own `caught_early_over` computes is exactly 0.5.
  const measured = await verdictEvents();
  const ratios = Object.values(measured.caughtEarlyByTenant);
  expect(ratios).toHaveLength(1);
  expect(ratios[0]).toBe(0.5);
});
