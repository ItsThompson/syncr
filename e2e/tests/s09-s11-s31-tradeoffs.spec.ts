/* S9, S11 and S31: what a tradeoff is, what it closes, and what it displaces.
 *
 * One fixture, because all three need a week whose verdict offers a concession, and `elastic_sleep`
 * is the fixture that has one: a task far larger than the capacity before its deadline, so the
 * verdict names a shortfall and enumerates the tradeoffs that would close it.
 *
 * S9 IS ONE TEST RATHER THAN FIVE, because it is one sequence: what the request does, what approving
 * does, and what the next solve and the next week do are observations at successive points of the same
 * act. Split into separate cases they would each have to rebuild the state the previous one left,
 * which is how a case ends up asserting something about a state the product cannot be in.
 *
 * S11 is driven WITHOUT A RACE, and that is worth stating because the obvious reading of it ("pin,
 * then pin again before the first solve lands") is a race a suite cannot win: the solve of a
 * forty-block week takes a fraction of the worker's five-second tick. The coordinator gives the same
 * mechanism a deterministic trigger: a tradeoff request supersedes any PENDING operation and creates
 * a new one carrying the candidate. So the supersession S11 observes is produced by the product's own
 * rule rather than by winning a timing window, and S31 is the other half of the same act.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Tradeoff, Verdict } from "../src/api/schemas.ts";
import { isoWeekShift } from "../src/api/weeks.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import {
  awaitProposal,
  awaitTerminal,
  operationsFor,
  pendingProposal,
  solveAndSettle,
  until,
  weekView,
} from "../src/harness/week.ts";

usingFixture("elastic_sleep");
test.describe.configure({ mode: "serial" });

const KIND = "drop_item";

const shortfallMinutes = (verdict: Verdict | null): number =>
  (verdict?.shortfalls ?? []).reduce((total, shortfall) => total + shortfall.minutes, 0);

const quoted = (verdict: Verdict | null, kind: string): Tradeoff => {
  const offered = (verdict?.tradeoffs ?? []).find((tradeoff) => tradeoff.kind === kind);
  if (!offered) {
    throw new Error(
      `the verdict offered no ${kind}. It offered: ${JSON.stringify(verdict?.tradeoffs)}`,
    );
  }
  return offered;
};

test("S9 a tradeoff is a proposal, an approved one closes the gap it quoted, and it does not carry into the next week", async ({
  api,
}) => {
  const week = planWeek();
  // SOLVED FIRST, and that is not incidental. A tradeoff's candidate is compared against the live
  // plan, and on a week the maintainer has only materialized every placement is a FILL, so the
  // candidate auto-applies and there is nothing left to assent to. The state S9 is about is a week
  // whose plan the solver has already chosen.
  await solveAndSettle(api, week);

  const before = await weekView(api, week);
  expect(before.verdict!.tradeoffs.length, "the solved week offers no tradeoff").toBeGreaterThan(0);
  expect(before.adjustments).toEqual([]);
  const offered = quoted(before.verdict, KIND);
  const quotedMinutes = offered.deltaMinutes;
  expect(quotedMinutes, "the tradeoff quoted no delta to close").not.toBeNull();
  const shortfallBefore = shortfallMinutes(before.verdict);
  expect(shortfallBefore).toBeGreaterThan(0);
  const blocksBefore = before.live!.blocks.length;

  await api.post(`/api/v1/weeks/${week}/tradeoffs`, { kind: KIND, targetId: offered.targetId });

  // Nothing mutated directly: the live plan is untouched and no adjustment is persisted.
  const requested = await weekView(api, week);
  expect(requested.live!.blocks.length).toBe(blocksBefore);
  expect(requested.adjustments).toEqual([]);

  const proposal = await awaitProposal(api, week);
  expect(proposal.candidateAdjustment).not.toBeNull();
  expect(proposal.candidateAdjustment!.kind).toBe(KIND);
  expect(proposal.candidateAdjustment!.targetId).toBe(offered.targetId);

  // Leaving it alone changes nothing, which is the other half of "tradeoffs are proposals".
  const left = await weekView(api, week);
  expect(left.adjustments).toEqual([]);
  expect(left.live!.blocks.length).toBe(blocksBefore);

  const approved = await api.post<{ adjustment: { kind: string } | null }>(
    `/api/v1/weeks/${week}/approve`,
    undefined,
    { idempotencyKey: `s09-approve-${week}` },
  );
  expect(approved.adjustment, "the approval recorded no concession").not.toBeNull();
  expect(approved.adjustment!.kind).toBe(KIND);

  const after = await weekView(api, week);
  expect(after.adjustments.map((each) => each.kind)).toContain(KIND);
  expect(after.proposal).toBeNull();

  // THE OBSERVATION THIS SCENARIO EXISTS FOR: the gap the panel quoted has closed by at least the
  // figure it quoted. A concession that silences a panel without moving the arithmetic behind it is
  // the failure this asserts against.
  expect(shortfallBefore - shortfallMinutes(after.verdict)).toBeGreaterThanOrEqual(quotedMinutes!);

  // The next solve honours it without re-approval.
  await solveAndSettle(api, week);
  const resolved = await weekView(api, week);
  expect(resolved.adjustments.map((each) => each.kind)).toContain(KIND);

  // The following week does not inherit it.
  const following = await weekView(api, isoWeekShift(week, 1));
  expect(following.adjustments).toEqual([]);
});

test("S31 a tradeoff gets its own operation, and S11 the one it displaces names its successor and is no failure", async ({
  api,
}) => {
  const week = isoWeekShift(planWeek(), 1);
  await solveAndSettle(api, week);
  const solved = await weekView(api, week);
  expect(solved.verdict!.tradeoffs.length, "the following week offers no tradeoff").toBeGreaterThan(0);

  const movable = solved.live!.blocks.filter(
    (block) => (block.origin === "task" || block.origin === "habit") && !block.pinned,
  );
  expect(movable.length).toBeGreaterThan(0);
  const block = movable[0]!;

  // A pin, debounced, so a solve is PENDING when the tradeoff arrives.
  const pinned = await api.post<{ operation: { id: string } }>(`/api/v1/weeks/${week}/pins`, {
    blockId: block.id,
    start: new Date(Date.parse(block.interval.start) + 15 * 60_000).toISOString(),
  });
  const pinsSolve = pinned.operation.id;

  const offered = quoted(solved.verdict, KIND);
  // The route answers the operation itself, not a wrapper: a tradeoff request IS the scheduling of a
  // solve that carries the candidate.
  const tradeoff = await api.post<{ id: string }>(`/api/v1/weeks/${week}/tradeoffs`, {
    kind: KIND,
    targetId: offered.targetId,
  });

  // S31: its own operation, not the pin's.
  expect(tradeoff.id).not.toBe(pinsSolve);

  // S11: the pin's operation reports superseded, names its successor, and carries no error.
  const displaced = await until(
    `operation ${pinsSolve} to leave pending`,
    () =>
      api.get<{ status: string; supersededBy: string | null; error: unknown }>(
        `/api/v1/operations/${pinsSolve}`,
      ),
    (seen) => seen.status !== "pending",
  );
  expect(displaced.status).toBe("superseded");
  expect(displaced.supersededBy).toBe(tradeoff.id);
  expect(displaced.error).toBeNull();

  // Nothing surfaces as a failure, and the successor carries the candidate through.
  const settled = await awaitTerminal(api, tradeoff.id);
  expect(settled.status).toBe("succeeded");
  expect((await operationsFor(api, week)).filter((each) => each.status === "failed")).toEqual([]);

  const proposal = await pendingProposal(api, week);
  expect(proposal?.candidateAdjustment?.kind).toBe(KIND);
});
