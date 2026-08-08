/* S28: identity survives a re-solve. S37: a re-solve does not shrink the work.
 *
 * WHAT THESE ASSERT OVER, AND WHY IT IS NOT THE LIVE PLAN. A re-solve of an already-solved week
 * produces a diff holding moves, and the authority rule holds such a diff WHOLE in the pending slot
 * rather than adopting any of it. So the live plan after a re-solve is byte-identical to the live plan
 * before it: measured at 55 of 55 ids. A case comparing the two compares one document with itself, and
 * the first version of this file did exactly that, which a bite proved by leaving it green.
 *
 * Both cases therefore read the CANDIDATE the second solve produced: through the diff, and through the
 * plan that diff becomes once it is approved.
 *
 * THREE ASSERTIONS, AND WHAT EACH ONE IS FOR:
 *
 * | Assertion | Status |
 * |---|---|
 * | every solver-chosen id in the adopted candidate was held before | **bites**: a bite making a habit's occurrence key clock-dependent across solves turns this case red |
 * | `removed` is empty for a re-solve nobody asked to drop anything | **bites**: the same bite reaches it first, with five removals |
 * | no block id appears in two of the diff's three classes | a structural invariant rather than a behaviour: `ProposalDiff.__post_init__` refuses a change that disagrees with its list, so a bite of the classifier raises inside the solve rather than reddening this. Kept as cheap insurance, and stated so nobody reads it as the biting one |
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Block } from "../src/api/schemas.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { awaitProposal, awaitTerminal, solveAndSettle, weekView } from "../src/harness/week.ts";

usingFixture("reference_week");
test.describe.configure({ mode: "serial" });

/* A frame block, a commitment and a buffer are placed by their source, so their identity surviving is a
 * statement about the materializer. S28 is about the two the solver chose the placement of. */
const CHOSEN_BY_THE_SOLVER: readonly string[] = ["task", "habit"];

const minutesOf = (block: { interval: { start: string; end: string } }): number =>
  (Date.parse(block.interval.end) - Date.parse(block.interval.start)) / 60_000;

const placedMinutes = (blocks: readonly Block[], title: string): number =>
  blocks
    .filter((block) => block.title === title)
    .reduce((total, block) => total + minutesOf(block), 0);

const chosenIds = (blocks: readonly Block[]): ReadonlySet<string> =>
  new Set(blocks.filter((block) => CHOSEN_BY_THE_SOLVER.includes(block.origin)).map((b) => b.id));

/* Which CONTENT the plan already held, by the entity its binding names. The identity claim is about
 * content that existed before the re-solve: a block for a task added between the two solves is a new
 * block with a new id and is not a re-key, so it is excluded by this rather than by a `continue` that
 * would also excuse the regression. */
const chosenEntities = (blocks: readonly Block[]): ReadonlySet<string> =>
  new Set(
    blocks
      .filter((block) => CHOSEN_BY_THE_SOLVER.includes(block.origin))
      .map((block) => block.binding.entityId),
  );

/** Something that changes the solve's inputs and names no placed block. */
const anUnrelatedTask = async (
  api: {
    get: <T>(path: string) => Promise<T>;
    post: <T>(path: string, body: unknown) => Promise<T>;
  },
  title: string,
): Promise<void> => {
  const areas = await api.get<{ areas: readonly { id: string; name: string }[] }>("/api/v1/areas");
  const study = areas.areas.find((area) => area.name === "Study")!;
  await api.post("/api/v1/tasks", {
    title,
    areaId: study.id,
    estimateMinutes: 30,
    minChunkMinutes: 30,
    deadline: null,
    priority: "low",
    splittable: false,
  });
};

test("S28 a re-solve keeps every block's identity, and reports a move in exactly one class", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);
  const before = await weekView(api, week);
  const held = chosenIds(before.live!.blocks);
  const contentHeld = chosenEntities(before.live!.blocks);
  expect(
    held.size,
    "the solved week holds nothing the solver chose the placement of",
  ).toBeGreaterThan(0);

  await anUnrelatedTask(api, "An unrelated errand");
  await solveAndSettle(api, week);

  // THE DIFF THE RE-SOLVE PRODUCED. The authority rule holds a diff carrying moves whole, so this is
  // the only place the second solve's answer is visible before it is approved.
  const proposal = await awaitProposal(api, week);
  const diff = proposal.proposal;
  expect(
    diff.moved.length + diff.added.length,
    "the re-solve proposed nothing, so there is no identity claim to make",
  ).toBeGreaterThan(0);

  // ONE CLASS PER BLOCK. Two changes naming one block would leave the reader to decide which the plan
  // is proposing, and a classifier that stopped pairing on identity would put a move in `removed` and
  // in `added` at once.
  const classes = new Map<string, string[]>();
  const note = (name: string, ids: readonly { blockId: string; title: string }[]): void => {
    for (const change of ids) {
      classes.set(change.blockId, [
        ...(classes.get(change.blockId) ?? []),
        `${name}:${change.title}`,
      ]);
    }
  };
  note("moved", diff.moved);
  note("added", diff.added);
  note("removed", diff.removed);
  for (const [blockId, named] of classes) {
    expect(named.length, `block ${blockId} appears in ${named.join(" and ")}`).toBe(1);
  }

  // Nothing the previous plan held is proposed for removal by a re-solve nobody asked to drop anything.
  expect(
    diff.removed.map((change) => change.title),
    "a re-solve proposed dropping work nobody asked it to drop",
  ).toEqual([]);

  // IDENTITY SURVIVED, asserted over the document the second solve produced rather than over the one it
  // did not change: approve the diff, and every block the solver chose the placement of must carry an
  // id the previous plan already held. A re-keyed occurrence lands here as an id nobody held.
  const approved = await api.post<{ projection: { id: string } }>(
    `/api/v1/weeks/${week}/approve`,
    undefined,
    { idempotencyKey: `s28-approve-${week}` },
  );
  await awaitTerminal(api, approved.projection.id);
  const adopted = await weekView(api, week);
  const carried = adopted.live!.blocks.filter(
    (block) =>
      CHOSEN_BY_THE_SOLVER.includes(block.origin) && contentHeld.has(block.binding.entityId),
  );
  expect(carried.length).toBeGreaterThan(0);
  for (const block of carried) {
    expect(
      held.has(block.id),
      `${block.title} at ${block.interval.start} carries id ${block.id.slice(0, 12)}, which the ` +
        "previous plan did not hold, so the same content was re-keyed by the re-solve",
    ).toBe(true);
  }
});

test("S37 the plan a re-solve produces places the same total minutes the previous one placed", async ({
  api,
}) => {
  const week = planWeek();
  const title = "F&F Past Papers";

  await solveAndSettle(api, week);
  const before = await weekView(api, week);
  const placedBefore = placedMinutes(before.live!.blocks, title);
  expect(placedBefore, `${title} was never placed, so there is nothing to shrink`).toBeGreaterThan(
    0,
  );

  // A second unrelated change, so this case's re-solve produces its own candidate rather than reading
  // the one the previous case approved.
  await anUnrelatedTask(api, "A second unrelated errand");
  await solveAndSettle(api, week);

  const proposed = await weekView(api, week);
  expect(
    proposed.proposal,
    "the re-solve produced no candidate, so there is no second document to measure",
  ).not.toBeNull();
  expect(
    proposed.proposal!.removed.filter((change) => change.title === title),
    "the re-solve offered to drop work that is not done",
  ).toEqual([]);

  // The candidate becomes the plan of record, and THAT is the document the figure is read off.
  const approved = await api.post<{ projection: { id: string } }>(
    `/api/v1/weeks/${week}/approve`,
    undefined,
    { idempotencyKey: `s37-approve-${week}` },
  );
  await awaitTerminal(api, approved.projection.id);
  const adopted = await weekView(api, week);
  expect(placedMinutes(adopted.live!.blocks, title)).toBe(placedBefore);
});
