/* The refused tradeoff: a concession is bounded to the state it is about, not withdrawn as a feature.
 *
 * A new user's weeks are MATERIALIZED AND UNSOLVED: the horizon maintainer has written each week a
 * plan, and every block in it was placed by its source, because no solve has ever run. Such a week
 * still carries a verdict, and the verdict still enumerates tradeoffs, because the enumeration reads
 * the gap the fixture built into the frame rather than anything the solver chose. So the offer an
 * eager caller quotes is real -- and granting it there would be wrong twice over: the candidate
 * would fill empty space rather than displace a choice of the solver's, so the authority rule would
 * auto-apply it and the concession would become the plan of record with nothing recorded as
 * conceded. The product refuses such a request with 409 before any solve is asked for.
 *
 * THE REFUSAL IS ASSERTED AGAINST THE PRE-FIX BEHAVIOUR IT REPLACED. Before the guard existed the
 * same request answered 202 with an operation to follow, and that operation succeeded: it solved the
 * week, bound content into the empty slots, and produced a proposal to approve. Every assertion this
 * case makes about the refusal therefore bites on that tree -- the status differs, the statement does
 * not exist, and the revision count moves by the revision the auto-applied candidate wrote.
 *
 * THE SECOND HALF IS THE BOUND, and it is what keeps the first half from reading as a withdrawal.
 * The same week, once solved, offers the same kind again, and the request made then answers with a
 * proposal that approves. The rule is about the state the week is in, not about the request's route.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { ApiClient, Problem } from "../src/api/client.ts";
import type { Tradeoff, Verdict, WeekRevisions } from "../src/api/schemas.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { awaitLivePlan, awaitProposal, solveAndSettle, weekView } from "../src/harness/week.ts";

usingFixture("elastic_sleep");

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

/** The origins whose time a solve chose, which is the set the refusal is derived from. */
const SOLVER_PLACED: readonly string[] = ["task", "habit"];

/** One page of the week's revision history, which is what "nothing was written" is counted over. */
const revisionsOf = async (client: ApiClient, isoWeek: string): Promise<WeekRevisions> =>
  client.get<WeekRevisions>(`/api/v1/weeks/${isoWeek}/revisions`);

test("a tradeoff on a materialized, unsolved week answers 409 and changes nothing; solved, the same week offers and accepts one", async ({
  api,
}) => {
  const week = planWeek();

  // THE STATE UNDER TEST, said through the plan rather than through absence: the week holds a live
  // plan, and nothing in it is a placement a solve chose.
  const fresh = await awaitLivePlan(api, week);
  const placed = fresh.live!.blocks.filter((block) => SOLVER_PLACED.includes(block.origin));
  expect(placed, "the fixture left this week already solved").toEqual([]);

  const shortfallBefore = shortfallMinutes(fresh.verdict);
  expect(shortfallBefore, "the unsolved week quotes no gap to concede against").toBeGreaterThan(0);
  const revisionsBefore = (await revisionsOf(api, week)).revisions.length;

  // Requested honestly: the kind and target are ones the verdict really enumerates, so the refusal
  // cannot be mistaken for the not-offered rejection a fabricated target would have earned anyway.
  const offered = quoted(fresh.verdict, KIND);

  const refusal = await api.attempt<Problem>("POST", `/api/v1/weeks/${week}/tradeoffs`, {
    kind: KIND,
    targetId: offered.targetId,
  });
  expect(refusal.status).toBe(409);
  expect(
    refusal.body.detail ?? "",
    "the refusal does not name the solve the caller is missing",
  ).toContain("no solve to concede against");
  expect(refusal.body.detail ?? "", "the refusal does not say what was not changed").toContain(
    "Nothing was changed",
  );

  // NOTHING MOVED: the gap reads the same and the history holds the same rows. On the pre-fix tree
  // both readings differ, along with the status and the statement above.
  const afterRefusal = await weekView(api, week);
  expect(shortfallMinutes(afterRefusal.verdict)).toBe(shortfallBefore);
  expect((await revisionsOf(api, week)).revisions.length).toBe(revisionsBefore);
  expect(afterRefusal.proposal).toBeNull();

  // THE BOUND: the same week, solved. It now holds blocks a solve placed, offers the same kind, and
  // the identical request produces a proposal that approves.
  await solveAndSettle(api, week);
  const solved = await weekView(api, week);
  expect(
    solved.live!.blocks.filter((block) => SOLVER_PLACED.includes(block.origin)).length,
    "solving placed nothing to concede against",
  ).toBeGreaterThan(0);
  const nowOffered = quoted(solved.verdict, KIND);

  await api.post(`/api/v1/weeks/${week}/tradeoffs`, {
    kind: KIND,
    targetId: nowOffered.targetId,
  });
  const proposal = await awaitProposal(api, week);
  expect(proposal.candidateAdjustment).not.toBeNull();
  expect(proposal.candidateAdjustment!.kind).toBe(KIND);

  const approved = await api.post<{ adjustment: { kind: string } | null }>(
    `/api/v1/weeks/${week}/approve`,
    undefined,
    { idempotencyKey: `refused-tradeoff-${week}` },
  );
  expect(approved.adjustment, "the approval recorded no concession").not.toBeNull();
  expect(approved.adjustment!.kind).toBe(KIND);

  const held = await weekView(api, week);
  expect(held.adjustments.map((each) => each.kind)).toContain(KIND);
});
