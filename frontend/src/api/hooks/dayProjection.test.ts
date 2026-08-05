/* What the day will say once a write lands.
 *
 * The two figures are the point of these tests. A projection that only replaced a row would leave the
 * header stating a presumed count the rows no longer support, and a header that disagreed with its own
 * rows is worse than one that waited for the response. */

import { describe, expect, it } from "vitest";

import {
  BLOCK_GYM,
  BLOCK_LEETCODE,
  buildDay,
  buildEmptyDay,
  buildGymRow,
  buildOutcome,
  buildRow,
} from "../../routes/today/__tests__/fixtures";
import {
  outcomesOf,
  stateOf,
  unansweredBlockIds,
  withConfirmedDay,
  withRecordedOutcome,
  withRestoredOutcomes,
} from "./dayProjection";

const AT = "2026-02-09T20:41:00.000Z";

describe("stateOf", () => {
  it("reads an absent outcome as presumed, which is what a block holds with no user action", () => {
    expect(stateOf(buildRow())).toBe("presumed");
  });

  it("reads a recorded outcome's own state", () => {
    expect(stateOf(buildRow({ outcome: buildOutcome({ state: "moved" }) }))).toBe("moved");
  });
});

describe("withRecordedOutcome", () => {
  it("replaces the named row's outcome and leaves every other row alone", () => {
    const projected = withRecordedOutcome(buildDay(), BLOCK_GYM, { state: "skipped" });

    expect(projected.behind[1].outcome?.state).toBe("skipped");
    expect(projected.behind[0].outcome).toBeNull();
    expect(projected.ahead.map((row) => row.outcome)).toEqual([null, null]);
  });

  it("carries the figure the state names, and nulls the one it does not", () => {
    const projected = withRecordedOutcome(buildDay(), BLOCK_LEETCODE, {
      state: "partial",
      actualMinutes: 145,
    });

    expect(projected.ahead[0].outcome).toMatchObject({
      state: "partial",
      actualMinutes: 145,
      actualInterval: null,
    });
  });

  it("records the block's own start as the instant it occurred at", () => {
    const projected = withRecordedOutcome(buildDay(), BLOCK_LEETCODE, { state: "skipped" });

    expect(projected.ahead[0].outcome?.occurredAt).toBe("2026-02-09T13:30:00+00:00");
  });

  it("drops the presumed count by one, because that row is no longer presumed", () => {
    const projected = withRecordedOutcome(buildDay(), BLOCK_GYM, { state: "skipped" });

    expect(projected.presumedCount).toBe(3);
    expect(projected.blockCount).toBe(4);
  });

  it("does not drop the count twice when the row already carried an outcome", () => {
    const day = buildDay({
      behind: [buildGymRow({ outcome: buildOutcome() })],
      ahead: [],
      blockCount: 1,
      presumedCount: 0,
    });

    const projected = withRecordedOutcome(day, BLOCK_GYM, { state: "moved" });

    expect(projected.presumedCount).toBe(0);
  });

  /* Recording does not confirm a day, and correcting a state does not move the instant it was
     settled at: both are the service's own rules, and a projection that moved either would show a
     reader a day that had become confirmed by their pressing skip. */
  it("keeps the day's settled instant, because recording does not confirm", () => {
    const day = buildDay({
      behind: [buildGymRow({ outcome: buildOutcome({ confirmedAt: AT }) })],
      ahead: [],
      blockCount: 1,
      presumedCount: 0,
      confirmedAt: AT,
    });

    const projected = withRecordedOutcome(day, BLOCK_GYM, { state: "completed" });

    expect(projected.confirmedAt).toBe(AT);
    expect(projected.behind[0].outcome?.confirmedAt).toBe(AT);
  });

  it("changes nothing for a block the day does not hold", () => {
    const day = buildDay();

    expect(withRecordedOutcome(day, "e5".repeat(32), { state: "skipped" })).toEqual(day);
  });

  /* A block a later re-solve added after the day was confirmed carries no instant, and the day is then not
     settled: a block nobody has answered for is a block nobody has answered for. Recording an exception on
     one of its neighbours must not make the day read as settled. */
  it("leaves the day unconfirmed while any row carries no instant", () => {
    const day = buildDay({
      behind: [buildGymRow({ outcome: buildOutcome({ confirmedAt: AT }) }), buildRow()],
      ahead: [],
      blockCount: 2,
      presumedCount: 1,
    });

    const projected = withRecordedOutcome(day, BLOCK_GYM, { state: "skipped" });

    expect(projected.confirmedAt).toBeNull();
    expect(projected.behind[0].outcome?.confirmedAt).toBe(AT);
  });
});

describe("outcomesOf and withRestoredOutcomes", () => {
  /* The undo of a refused write. It names rows rather than the day, so a row the write never touched keeps
     whatever it holds now, including a change a peer applied while the refused one was in flight. */
  it("puts back the named row and leaves every other row as it now stands", () => {
    const day = buildDay();
    const before = outcomesOf(day, [BLOCK_GYM]);
    const changed = withRecordedOutcome(
      withRecordedOutcome(day, BLOCK_GYM, { state: "skipped" }),
      BLOCK_LEETCODE,
      { state: "completed" },
    );

    const restored = withRestoredOutcomes(changed, before);

    expect(restored.behind[1].outcome).toBeNull();
    expect(restored.ahead[0].outcome?.state).toBe("completed");
    expect(restored.presumedCount).toBe(3);
  });

  it("restores an outcome a row already carried rather than clearing it", () => {
    const day = buildDay({
      behind: [buildGymRow({ outcome: buildOutcome({ state: "partial", actualMinutes: 20 }) })],
      ahead: [],
      blockCount: 1,
      presumedCount: 0,
    });
    const before = outcomesOf(day, [BLOCK_GYM]);

    const restored = withRestoredOutcomes(
      withRecordedOutcome(day, BLOCK_GYM, { state: "skipped" }),
      before,
    );

    expect(restored.behind[0].outcome).toMatchObject({ state: "partial", actualMinutes: 20 });
  });

  it("names the blocks a confirmation would stamp, which are the ones carrying no instant", () => {
    const day = buildDay({
      behind: [buildGymRow({ outcome: buildOutcome({ confirmedAt: AT }) }), buildRow()],
      ahead: [],
      blockCount: 2,
      presumedCount: 1,
    });

    expect(unansweredBlockIds(day)).toEqual([BLOCK_LEETCODE]);
  });

  it("unstamps only what a confirmation stamped", () => {
    const day = buildDay({
      behind: [buildGymRow({ outcome: buildOutcome({ confirmedAt: AT }) }), buildRow()],
      ahead: [],
      blockCount: 2,
      presumedCount: 1,
    });
    const before = outcomesOf(day, unansweredBlockIds(day));

    const restored = withRestoredOutcomes(
      withConfirmedDay(day, "2026-02-09T21:00:00.000Z"),
      before,
    );

    expect(restored.behind[0].outcome?.confirmedAt).toBe(AT);
    expect(restored.behind[1].outcome).toBeNull();
    expect(restored.confirmedAt).toBeNull();
  });
});

describe("withConfirmedDay", () => {
  it("gives every row with nothing said about it a presumed outcome, answered for at that instant", () => {
    const projected = withConfirmedDay(buildDay(), AT);

    expect(projected.behind.map((row) => row.outcome?.state)).toEqual(["presumed", "presumed"]);
    expect(projected.ahead.map((row) => row.outcome?.confirmedAt)).toEqual([AT, AT]);
    expect(projected.confirmedAt).toBe(AT);
  });

  /* The presumption written down is still a presumption, which is why confirming changes no figure but
     the settled instant. A projection that zeroed the count would show the reader a day whose header
     disagreed with every row of it. */
  it("leaves the presumed count where it was, because a confirmed presumption is still presumed", () => {
    expect(withConfirmedDay(buildDay(), AT).presumedCount).toBe(4);
  });

  it("keeps a recorded exception's state rather than completing it", () => {
    const day = buildDay({ behind: [buildGymRow({ outcome: buildOutcome() })], presumedCount: 3 });

    const projected = withConfirmedDay(day, AT);

    expect(projected.behind[0].outcome).toMatchObject({ state: "skipped", confirmedAt: AT });
  });

  it("keeps the instant a day already settled at, so confirming twice does not move it", () => {
    const earlier = "2026-02-09T19:00:00.000Z";
    const day = buildDay({
      behind: [buildGymRow({ outcome: buildOutcome({ confirmedAt: earlier }) })],
      ahead: [],
      blockCount: 1,
    });

    const projected = withConfirmedDay(day, AT);

    expect(projected.behind[0].outcome?.confirmedAt).toBe(earlier);
    expect(projected.confirmedAt).toBe(earlier);
  });

  /* A day holding no block is never confirmed and is never counted as unconfirmed: there is nothing
     to answer for, and the api stores nothing for it. */
  it("leaves a day with no rows unconfirmed", () => {
    expect(withConfirmedDay(buildEmptyDay(), AT).confirmedAt).toBeNull();
  });

  it("leaves the count of days before this one alone, since confirming today cannot change it", () => {
    expect(withConfirmedDay(buildDay(), AT).unconfirmedDays).toBe(3);
  });
});
