/* KEYBOARD TRAVERSAL, INCLUDING THE ONE CASE THE POINTER CANNOT SERVE.
 *
 * EVERY BLOCK IS REACHABLE AT EVERY TIER, and the tier is what these cases vary: a fifteen-minute block at the
 * twelve-hour default is 13px tall on the reference display, which the tier ladder draws as a sliver with no title at
 * all. `j` and `k` do not read a height, so the assertion is that the traversal lands on it exactly as it lands on a
 * ninety-minute block beside it.
 *
 * IN TIME ORDER, NOT DOCUMENT ORDER. Every fixture here holds its blocks in an order the payload might send them in
 * and never in the order they are traversed, so a traversal that walked the array would fail. */

import { describe, expect, it } from "vitest";

import { firstBlock, stepColumn, stepInColumn, surviving } from "../selection";
import type { GridBlock, WeekDay } from "../../../ui/domain";

const ZONE = "Europe/London";

function block(id: string, startMin: number, minutes: number): GridBlock {
  return {
    id,
    title: id,
    span: { startMin, endMin: startMin + minutes },
    origin: "task",
    pigment: "01",
    areaName: "Career",
    isPinned: false,
  };
}

function day(date: string, blocks: readonly GridBlock[]): WeekDay {
  return {
    date,
    zone: ZONE,
    startMs: Date.parse(`${date}T00:00:00Z`),
    minutes: 1440,
    blocks,
    bands: [],
  };
}

/* Monday holds three blocks and the payload order is deliberately not the time order: the sliver arrives first, the
 * ninety-minute block last. Tuesday holds one, at a time between two of Monday's. Wednesday holds none. */
const SLIVER = block("sliver", 330, 15);
const MIDDAY = block("midday", 720, 30);
const EVENING = block("evening", 1140, 90);
const TUESDAY_ONE = block("tuesday", 800, 60);

const DAYS: WeekDay[] = [
  day("2026-02-09", [MIDDAY, SLIVER, EVENING]),
  day("2026-02-10", [TUESDAY_ONE]),
  day("2026-02-11", []),
  day("2026-02-12", [block("thursday", 300, 30)]),
];

describe("j and k, in the current column, in time order", () => {
  it("starts at the first block of the week when nothing is selected", () => {
    expect(firstBlock(DAYS)?.blockId).toBe("sliver");
    expect(stepInColumn(DAYS, null, 1)?.blockId).toBe("sliver");
  });

  it("reaches a sliver-tier block exactly as it reaches any other", () => {
    const first = stepInColumn(DAYS, null, 1);

    expect(first).toEqual({ date: "2026-02-09", blockId: "sliver" });
    expect(stepInColumn(DAYS, first, 1)?.blockId).toBe("midday");
  });

  it("walks down the column in time order and stops at the last", () => {
    let at = firstBlock(DAYS);
    const walked = [at?.blockId];
    for (let step = 0; step < 4; step += 1) {
      at = stepInColumn(DAYS, at, 1);
      walked.push(at?.blockId);
    }

    expect(walked).toEqual(["sliver", "midday", "evening", "evening", "evening"]);
  });

  it("walks back up and stops at the first, holding the selection rather than clearing it", () => {
    const evening = { date: "2026-02-09", blockId: "evening" };

    expect(stepInColumn(DAYS, evening, -1)?.blockId).toBe("midday");
    expect(stepInColumn(DAYS, { date: "2026-02-09", blockId: "sliver" }, -1)?.blockId).toBe(
      "sliver",
    );
  });
});

describe("h and l, between columns, preserving the nearest block in time", () => {
  it("lands on the nearest start rather than on the same index", () => {
    /* Monday's midday block starts at 720. Tuesday holds one block at 800, which is the nearest thing it has. */
    const next = stepColumn(DAYS, { date: "2026-02-09", blockId: "midday" }, 1);

    expect(next).toEqual({ date: "2026-02-10", blockId: "tuesday" });
  });

  it("skips a column with no blocks rather than selecting nothing", () => {
    const next = stepColumn(DAYS, { date: "2026-02-10", blockId: "tuesday" }, 1);

    expect(next).toEqual({ date: "2026-02-12", blockId: "thursday" });
  });

  it("holds the selection at the first and last columns", () => {
    expect(stepColumn(DAYS, { date: "2026-02-09", blockId: "midday" }, -1)?.date).toBe(
      "2026-02-09",
    );
    expect(stepColumn(DAYS, { date: "2026-02-12", blockId: "thursday" }, 1)?.date).toBe(
      "2026-02-12",
    );
  });

  it("selects the first block of the week from nothing, as the column keys do", () => {
    expect(stepColumn(DAYS, null, 1)?.blockId).toBe("sliver");
  });
});

describe("what a redraw leaves standing", () => {
  it("keeps a selection the week still holds", () => {
    const held = { date: "2026-02-09", blockId: "midday" };

    expect(surviving(DAYS, held)).toEqual(held);
  });

  /* A SOLVE LANDING CAN REMOVE THE SELECTED BLOCK. Holding an identifier the week no longer contains would leave the
   * keys acting on nothing and the detail panel describing a placement that no longer exists. */
  it("clears a selection whose block the solve removed", () => {
    expect(surviving(DAYS, { date: "2026-02-09", blockId: "gone" })).toBeNull();
  });

  it("clears a selection whose column the week no longer has", () => {
    expect(surviving(DAYS, { date: "2026-03-09", blockId: "midday" })).toBeNull();
  });
});
