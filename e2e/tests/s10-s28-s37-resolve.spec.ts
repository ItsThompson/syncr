/* S10: a burst costs one solve. S28: identity survives a re-solve. S37: a re-solve does not shrink
 * the work.
 *
 * All three are questions about what a SECOND solve does to a week the first one already answered, so
 * they share a fixture and a first solve. Each names its own scenario number.
 *
 * S10's four observations are each read from a different place, and one of them is read DURING the
 * burst rather than after it: "one solve operation exists at a time" is an invariant the partial
 * unique index enforces, and an assertion made only at the end cannot tell a queue that held one from
 * a queue that held five and drained.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Block } from "../src/api/schemas.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import {
  operationsFor,
  solveAndSettle,
  until,
  weekView,
} from "../src/harness/week.ts";

usingFixture("reference_week");

const BURST = 12;

const nonTerminal = (status: string): boolean => status === "pending" || status === "running";

const placedMinutes = (blocks: readonly Block[], title: string): number =>
  blocks
    .filter((block) => block.title === title)
    .reduce(
      (total, block) =>
        total + (Date.parse(block.interval.end) - Date.parse(block.interval.start)) / 60_000,
      0,
    );

test("S10 twelve pins cost one solve, zero live revisions and zero calendar writes", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);

  const solved = await weekView(api, week);
  const movable = solved.live!.blocks.filter(
    (block) => (block.origin === "task" || block.origin === "habit") && !block.pinned,
  );
  expect(movable.length, "the solved week placed nothing a pin could move").toBeGreaterThan(0);

  const revisionsBefore = await api.get<{ revisions: readonly unknown[] }>(
    `/api/v1/weeks/${week}/revisions`,
  );
  const projectionsBefore = (await operationsFor(api, week)).filter(
    (each) => each.kind === "projection",
  ).length;

  // The burst. Debounced, not immediate: this is the shape a weekly session produces, and the
  // debounce is the mechanism under test.
  let mostSolvesInFlight = 0;
  for (let pin = 0; pin < BURST; pin += 1) {
    const block = movable[pin % movable.length]!;
    const shifted = new Date(Date.parse(block.interval.start) + (pin + 1) * 15 * 60_000);
    const reply = await api.attempt("POST", `/api/v1/weeks/${week}/pins`, {
      blockId: block.id,
      start: shifted.toISOString(),
    });
    // A pin the week cannot hold is refused, and a refusal is not a burst member: what matters is
    // that every ACCEPTED pin coalesced.
    if (reply.status >= 400) continue;
    const inFlight = (await operationsFor(api, week)).filter(
      (each) => each.kind === "solve" && nonTerminal(each.status),
    ).length;
    mostSolvesInFlight = Math.max(mostSolvesInFlight, inFlight);
    expect(inFlight, `after ${pin + 1} pins the week held ${inFlight} solves at once`).toBeLessThanOrEqual(1);
  }
  expect(mostSolvesInFlight, "no solve was ever scheduled by the burst").toBe(1);

  await until(
    "the burst's solve to drain",
    () => operationsFor(api, week),
    (seen) => seen.every((each) => !nonTerminal(each.status)),
  );

  const settled = await operationsFor(api, week);
  const superseded = settled.filter((each) => each.status === "superseded");
  expect(superseded.length, "a coalesced burst supersedes at most one operation").toBeLessThanOrEqual(1);

  // Zero live revisions, and zero calendar writes. A diff holding a move is held whole, so nothing
  // auto-applies and nothing is enqueued to project.
  const revisionsAfter = await api.get<{ revisions: readonly unknown[] }>(
    `/api/v1/weeks/${week}/revisions`,
  );
  expect(revisionsAfter.revisions.length).toBe(revisionsBefore.revisions.length);
  const projectionsAfter = settled.filter((each) => each.kind === "projection").length;
  expect(projectionsAfter).toBe(projectionsBefore);
});

test("S28 a block keeps its identity across an unrelated re-solve", async ({ api }) => {
  const week = planWeek();
  await solveAndSettle(api, week);
  const before = await weekView(api, week);
  const identities = new Map(
    before.live!.blocks.map((block) => [block.id, block.binding] as const),
  );

  // Unrelated: a new task in another Area, which changes the inputs without naming any placed block.
  const areas = await api.get<{ areas: readonly { id: string; name: string }[] }>("/api/v1/areas");
  const study = areas.areas.find((area) => area.name === "Study")!;
  await api.post("/api/v1/tasks", {
    title: "An unrelated errand",
    areaId: study.id,
    estimateMinutes: 30,
    minChunkMinutes: 30,
    deadline: null,
    priority: "low",
    splittable: false,
  });

  await solveAndSettle(api, week);
  const after = await weekView(api, week);

  // Every block that is still in the plan carries the same derived id for the same content, so a
  // moved block is one row rather than a removal and an addition.
  for (const block of after.live!.blocks) {
    const known = identities.get(block.id);
    if (!known) continue;
    expect(block.binding.kind).toBe(known.kind);
    expect(block.binding.entityId).toBe(known.entityId);
    expect(block.binding.occurrenceKey).toBe(known.occurrenceKey);
    expect(block.binding.splitIndex).toBe(known.splitIndex);
  }

  const frameBefore = before.live!.blocks.filter((block) => block.origin === "frame").map((b) => b.id);
  const frameAfter = new Set(after.live!.blocks.filter((block) => block.origin === "frame").map((b) => b.id));
  for (const id of frameBefore) expect(frameAfter.has(id)).toBe(true);
});

test("S37 a re-solve places the same total minutes it placed before", async ({ api }) => {
  const week = planWeek();
  await solveAndSettle(api, week);
  const before = await weekView(api, week);

  const title = "F&F Past Papers";
  const placedBefore = placedMinutes(before.live!.blocks, title);
  expect(placedBefore, `${title} was never placed, so there is nothing to shrink`).toBeGreaterThan(0);

  await solveAndSettle(api, week);
  const after = await weekView(api, week);
  expect(placedMinutes(after.live!.blocks, title)).toBe(placedBefore);

  // And no proposal offers to drop half of it: an unpinned placement is not evidence that the work
  // is done, so the demand the second solve reads is the same demand the first one read.
  expect(after.proposal?.removed.filter((change) => change.title === title) ?? []).toEqual([]);
});
