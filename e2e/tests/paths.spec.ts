/* The three whole-product paths section 20 names, each driven end to end.
 *
 * | Path | What it crosses |
 * |---|---|
 * | pin to projection | the grid's pin, the debounce, the solve, the authority rule, the pending slot, the approval, and the projection pass |
 * | conflict resolution | a real fetch of a real feed over a real socket, ingest, detection at the solve's commit path, and the answer |
 * | confirm and backfill | the ledger, three days of recordings, the confirmation, and what a backfilled day counts as |
 *
 * The projection END of the first path is where this suite stops short of the phone, and the reason is
 * a product decision rather than a gap in the harness: `GOOGLE_PROJECTION_WRITES` is false in every
 * environment, because the destructive reconciliation has never run from an armed deployment over a
 * horizon of real plan blocks. It has met the real Google API from the marked live suite against a
 * development calendar, which is a different quantity of writes against a calendar nobody reads.
 * So the path is driven until the projection operation reports its outcome, and S3 is the manual
 * scenario that observes an event on a device.
 */

import { test, expect, usingFixture } from "./harness.ts";
import { dateShift } from "../src/api/weeks.ts";
import { ICS_PROVIDER } from "../src/config.ts";
import { currentWeek, planWeek } from "../src/harness/subject-weeks.ts";
import {
  awaitProposal,
  awaitTerminal,
  solveAndSettle,
  until,
  weekView,
} from "../src/harness/week.ts";

usingFixture("reference_week");
test.describe.configure({ mode: "serial" });

test("the pin-to-projection path: a pin becomes a proposal, an approval becomes the plan of record, and a projection is attempted", async ({
  api,
}) => {
  const week = planWeek();
  await solveAndSettle(api, week);

  const solved = await weekView(api, week);
  const movable = solved.live!.blocks.find(
    (block) => (block.origin === "task" || block.origin === "habit") && !block.pinned,
  );
  expect(movable, "the solved week placed nothing a pin could move").toBeDefined();

  const moveTo = new Date(Date.parse(movable!.interval.start) + 90 * 60_000).toISOString();
  const pinned = await api.post<{ pin: { supersededPlacement: { start: string } } }>(
    `/api/v1/weeks/${week}/pins`,
    { blockId: movable!.id, start: moveTo },
  );
  // The counterfactual is recorded at the moment of the pin: where the solver had put it. Compared as
  // instants rather than as strings: the api omits a zero millisecond field and `toISOString` writes
  // one, so two spellings of one instant are not one string.
  expect(Date.parse(pinned.pin.supersededPlacement.start)).toBe(
    Date.parse(movable!.interval.start),
  );

  const proposal = await awaitProposal(api, week);
  const moved = proposal.proposal.moved.map((change) => change.blockId);
  expect(moved).toContain(movable!.id);

  const approved = await api.post<{
    revisionId: string;
    projection: { id: string };
    inputVersion: number;
    solvedAgainstVersion: number;
  }>(`/api/v1/weeks/${week}/approve`, undefined, { idempotencyKey: `path-approve-${week}` });

  // Approval bumps the input version past the one the solve was computed against, which is what makes
  // a concurrent solve fail its conditional write rather than adopt a stale plan.
  expect(approved.inputVersion).toBeGreaterThan(approved.solvedAgainstVersion);

  const after = await weekView(api, week);
  expect(after.proposal).toBeNull();
  const held = after.live!.blocks.find((block) => block.id === movable!.id);
  expect(held, "the approved plan no longer holds the pinned block").toBeDefined();
  expect(Date.parse(held!.interval.start)).toBe(Date.parse(moveTo));
  expect(held!.pinned).toBe(true);

  // The projection the approval enqueued reaches a terminal state and is not a failure.
  const projected = await awaitTerminal(api, approved.projection.id);
  expect(projected.kind).toBe("projection");
  expect(projected.status).toBe("succeeded");
});

test("the conflict-resolution path, and S12 the raise: a commitment arriving over the network raises a conflict, and resolving it records the answer", async ({
  api,
}) => {
  const week = planWeek();
  const before = await weekView(api, week);
  const known = new Set(before.conflicts.map((conflict) => conflict.id));

  // A feed that did not exist a moment ago, fetched over a real socket from the mocked provider. Its
  // Thursday 07:00 event lands on the `Wake Up` routine every week.
  const source = await api.post<{ id: string }>("/api/v1/calendar-sources", {
    provider: "ics",
    displayName: "A reading group that arrived late",
    externalId: `${ICS_PROVIDER}/late-arrival.ics`,
  });
  // A sync is an operation rather than a request that returns the count: the fetch happens on the
  // worker. So the count is read off the source once the operation has finished.
  const sync = await api.post<{ id: string }>(`/api/v1/calendar-sources/${source.id}/sync`);
  const synced = await awaitTerminal(api, sync.id);
  expect(synced.status).toBe("succeeded");
  const sources = await api.get<{
    sources: readonly { id: string; anchorCount: number; syncState: { eventsRead: number } }[];
  }>("/api/v1/calendar-sources");
  const arrived = sources.sources.find((each) => each.id === source.id)!;
  expect(arrived.syncState.eventsRead, "the mocked provider served nothing").toBeGreaterThan(0);
  expect(arrived.anchorCount).toBeGreaterThan(0);

  // Detection runs on the commit path of a solve, so the collision surfaces once the week is solved
  // against the commitment that now exists.
  await solveAndSettle(api, week);
  const raised = await until(
    `${week} to raise a conflict for the late arrival`,
    () => weekView(api, week),
    (seen) => seen.conflicts.some((conflict) => !known.has(conflict.id)),
  );
  const fresh = raised.conflicts.find((conflict) => !known.has(conflict.id))!;
  expect(fresh.resolution).toBeNull();
  expect(fresh.resolvedAt).toBeNull();
  expect(fresh.overlap.start).not.toBe(fresh.overlap.end);

  // No `anchorTypeId`: a kept-both answer changes no commitment type, and naming one is refused
  // rather than ignored.
  const resolved = await api.post<{ conflict: { resolution: string; resolvedAt: string | null } }>(
    `/api/v1/conflicts/${fresh.id}/resolve`,
    { resolution: "kept-both" },
    { idempotencyKey: `path-resolve-${fresh.id}` },
  );
  expect(resolved.conflict.resolution).toBe("kept-both");
  expect(resolved.conflict.resolvedAt).not.toBeNull();

  const answered = await weekView(api, week);
  const same = answered.conflicts.find((conflict) => conflict.id === fresh.id)!;
  expect(same.resolution).toBe("kept-both");
  expect(same.resolvedAt).not.toBeNull();
});

test("S13 the confirm-and-backfill path: unconfirmed days are excluded, and backfilling brings them in", async ({
  api,
}) => {
  const week = currentWeek();
  const view = await weekView(api, week);
  expect(view.live, "the current week holds no plan").not.toBeNull();

  // The days already lived. The plan covers the whole week, so which of them exist is a fact about
  // today rather than about the fixture, and a run early on a Monday has none: that is stated rather
  // than worked around, because manufacturing a past is what would make this scenario a lie.
  const today = view.zoneByDate ? Object.keys(view.zoneByDate).sort() : [];
  const lived = today.filter((date) => Date.parse(`${date}T23:59:59Z`) < Date.now());
  test.skip(lived.length < 2, "fewer than two days of this week have been lived");

  const before = await api.get<{ unconfirmedDays: number }>(`/api/v1/days/${lived[0]!}`);
  expect(before.unconfirmedDays).toBeGreaterThan(0);

  const backfilled = await api.post<{
    confirmedDays: number;
    blocksRecorded: number;
    unconfirmedDays: number;
  }>(
    "/api/v1/days/confirm-range",
    { from: lived[0]!, to: lived[lived.length - 1]! },
    { idempotencyKey: `path-backfill-${week}` },
  );
  expect(backfilled.confirmedDays).toBeGreaterThan(0);
  expect(backfilled.blocksRecorded).toBeGreaterThan(0);
  // Backfilling is what brings those days in: the outstanding count falls by what the call settled.
  expect(backfilled.unconfirmedDays).toBeLessThan(before.unconfirmedDays);

  const after = await api.get<{ confirmedAt: string | null; unconfirmedDays: number }>(
    `/api/v1/days/${lived[0]!}`,
  );
  expect(after.confirmedAt).not.toBeNull();
  expect(after.unconfirmedDays).toBeLessThan(before.unconfirmedDays);

  // A day nobody has answered for is not counted as confirmed, whatever the range said. The route answers
  // 200 today, with the day's blocks in `ahead` and `confirmedAt` null, which is what is asserted. A 404 or
  // a 422 is tolerated as an alternative rather than expected: those are the answers a route that refuses
  // to describe an unreached day would give, and either is defensible. What must never happen is a day
  // being reported as settled when nothing settled it.
  const tomorrow = dateShift(lived[lived.length - 1]!, 1);
  const unlived = await api.attempt<{ confirmedAt: string | null }>(
    "GET",
    `/api/v1/days/${tomorrow}`,
  );
  expect(
    [200, 404, 422].includes(unlived.status),
    `reading an unlived day answered ${unlived.status}`,
  ).toBe(true);
  if (unlived.status === 200) expect(unlived.body.confirmedAt).toBeNull();
});
