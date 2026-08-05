/* THE SWEEP, THE COLUMNS, AND THE TWO THINGS THAT MUST NOT BE TRUE OF THEM.
 *
 * No origin is special-cased, and layout does not depend on paint order. Both are asserted directly rather than
 * inferred: the sweep is handed spans, so the first is checked by giving the frame's own span the widest interval in
 * a cluster and requiring it to take a column like anything else, and the second by shuffling the input and
 * requiring the answer per block to be identical.
 *
 * The boundaries are the ticket's: an abutting pair, a zero-length span, a span crossing midnight, and a depth past
 * the even-split floor. */

import { describe, expect, it } from "vitest";

import { OVERLAP_MAX_SPLIT } from "../metrics";
import { placeOverlaps } from "../overlap";
import type { OffsetSpan } from "../types";

const span = (startMin: number, endMin: number): OffsetSpan => ({ startMin, endMin });

/** How wide a placement is as a fraction of the column, which is what an even split has to divide evenly. */
const widthOf = (placement: { left: number; right: number }): number =>
  1 - placement.left - placement.right;

describe("a block with nothing overlapping it", () => {
  it("takes the whole column and is not a split", () => {
    const [only] = placeOverlaps([span(540, 600)]);

    expect(only).toEqual({
      left: 0,
      right: 0,
      indentSteps: 0,
      layer: 0,
      overlapCount: null,
      isSplit: false,
    });
  });

  it("is what an ABUTTING pair each gets, because the spans are half-open", () => {
    const placements = placeOverlaps([span(540, 600), span(600, 660)]);

    for (const placement of placements) expect(widthOf(placement)).toBe(1);
    expect(placements.map((placement) => placement.isSplit)).toEqual([false, false]);
  });

  it("is what a sequential run inside one cluster gets, because a finished column is reusable", () => {
    /* Three blocks in one transitive cluster but only two columns: the third begins after the first has ended, so it
     * takes the leftmost column whose last block has finished rather than a third column of its own. */
    const placements = placeOverlaps([span(0, 60), span(30, 120), span(60, 90)]);

    expect(placements.map(widthOf)).toEqual([0.5, 0.5, 0.5]);
    expect(placements[2].left).toBe(0);
  });

  /* THE RUNNING MAXIMUM END IS COMPARED WITH `>=` BECAUSE THE SPANS ARE HALF-OPEN, and the difference shows one block
   * BACK rather than at the boundary itself. A block ending exactly where a pair begins shares no minute with either,
   * so it keeps the whole column; comparing with `>` holds the cluster open, deals the pair its two columns, and hands
   * the earlier block a HALF column for an overlap it is not in. */
  it("keeps the whole column for a block that ends exactly where a pair begins", () => {
    const [before, first, second] = placeOverlaps([span(0, 60), span(60, 120), span(60, 120)]);

    expect(widthOf(before)).toBe(1);
    expect(before.isSplit).toBe(false);
    expect(widthOf(first)).toBe(0.5);
    expect(widthOf(second)).toBe(0.5);
  });
});

describe("an even split", () => {
  it("divides the column evenly at depth 2 and 3", () => {
    for (const depth of [2, 3]) {
      const spans = Array.from({ length: depth }, () => span(600, 660));
      const placements = placeOverlaps(spans);

      for (const placement of placements) expect(widthOf(placement)).toBeCloseTo(1 / depth, 10);
      expect(placements.map((placement) => placement.left)).toEqual(
        Array.from({ length: depth }, (_, index) => index / depth),
      );
    }
  });

  it("leaves the leftmost block meeting the column edge and splits every other one", () => {
    const placements = placeOverlaps([span(600, 660), span(600, 660), span(600, 660)]);

    expect(placements.map((placement) => placement.isSplit)).toEqual([false, true, true]);
  });

  it("needs no stacking, because the shares are disjoint", () => {
    const placements = placeOverlaps([span(600, 660), span(600, 660)]);

    for (const placement of placements) expect(placement.layer).toBe(0);
    expect(placements[0].left + widthOf(placements[0])).toBeCloseTo(placements[1].left, 10);
  });

  it("stops at depth three, which is where an even share leaves nothing to write in", () => {
    const atFloor = placeOverlaps(Array.from({ length: OVERLAP_MAX_SPLIT }, () => span(600, 660)));
    const pastFloor = placeOverlaps(
      Array.from({ length: OVERLAP_MAX_SPLIT + 1 }, () => span(600, 660)),
    );

    expect(atFloor.every((placement) => placement.indentSteps === 0)).toBe(true);
    expect(pastFloor.some((placement) => placement.indentSteps > 0)).toBe(true);
  });
});

describe("a stagger at depth four and above", () => {
  const spans = [span(600, 700), span(610, 700), span(620, 700), span(630, 700), span(640, 700)];

  it("indents each block one step further than the one behind it", () => {
    expect(placeOverlaps(spans).map((placement) => placement.indentSteps)).toEqual([0, 1, 2, 3, 4]);
  });

  it("puts the LATER start in front", () => {
    const layers = placeOverlaps(spans).map((placement) => placement.layer);

    expect(layers).toEqual([1, 2, 3, 4, 5]);
    expect(layers.toSorted((left, right) => left - right)).toEqual(layers);
  });

  it("puts the count marker in the frontmost block and in no other", () => {
    const counts = placeOverlaps(spans).map((placement) => placement.overlapCount);

    expect(counts).toEqual([null, null, null, null, 5]);
  });

  it("reaches the column's right edge, so the frontmost block is full width", () => {
    for (const placement of placeOverlaps(spans)) expect(placement.right).toBe(0);
  });
});

/* AN EARLIER DRAFT MADE THE CIRCADIAN FRAME A FULL-WIDTH BACKDROP THAT NEVER SPLIT, and it was wrong twice: a
 * fifteen-minute `Wake Up` is also origin `frame` and a genuine participant, and a full-width frame block painted
 * over whatever it overlapped and clipped that block's title. The sweep is handed spans and cannot tell one origin
 * from another, so the assertion is that the widest span in a cluster is treated exactly like the narrowest. */
describe("no origin is special-cased", () => {
  it("gives the widest span in a cluster a column like anything else", () => {
    const sleep = span(0, 315);
    const wake = span(315, 330);
    const early = span(300, 360);
    const placements = placeOverlaps([sleep, wake, early]);

    expect(widthOf(placements[0])).toBe(0.5);
    expect(placements[0].isSplit).toBe(false);
    expect(placements[1].left).toBe(0);
    expect(placements[2].left).toBe(0.5);
  });

  it("participates in a stagger like anything else at depth four", () => {
    const frame = span(0, 1440);
    const others = [span(60, 120), span(70, 130), span(80, 140)];
    const [framePlacement] = placeOverlaps([frame, ...others]);

    expect(framePlacement.indentSteps).toBe(0);
    expect(framePlacement.overlapCount).toBeNull();
  });
});

describe("layout does not depend on paint order", () => {
  /* SORTED BY START, THEN BY DESCENDING END. Where two blocks begin together the longer one is dealt the leftmost
   * column and the shorter stacks to its right; the reverse leaves a long block sitting right of the short ones it
   * contains, which reads as unrelated rather than as an overlap. It is the one part of the sweep whose answer depends
   * on the tie-break, so it is asserted directly rather than through a cluster's column count. */
  it("gives the LONGER of two blocks starting together the leftmost column", () => {
    const [longer, shorter] = placeOverlaps([span(0, 120), span(0, 60)]);

    expect(longer.left).toBe(0);
    expect(longer.isSplit).toBe(false);
    expect(shorter.left).toBe(0.5);
    expect(shorter.isSplit).toBe(true);
  });

  it("answers the same for each block however the input is ordered", () => {
    const spans = [span(0, 315), span(300, 360), span(310, 340), span(315, 330), span(600, 660)];
    const forwards = placeOverlaps(spans);
    const backwards = placeOverlaps([...spans].toReversed()).toReversed();

    expect(backwards).toEqual(forwards);
  });

  it("gives a cluster's column count from the sweep rather than from the order given", () => {
    const spans = [span(620, 700), span(600, 700), span(610, 700), span(630, 700)];

    expect(
      placeOverlaps(spans)
        .map((placement) => placement.indentSteps)
        .toSorted(),
    ).toEqual([0, 1, 2, 3]);
  });
});

describe("the boundaries", () => {
  it("draws a zero-length span rather than dropping it", () => {
    const placements = placeOverlaps([span(600, 600)]);

    expect(placements).toHaveLength(1);
    expect(widthOf(placements[0])).toBe(1);
  });

  it("keeps two zero-length spans at one instant out of each other's cluster", () => {
    /* Both are empty, so neither covers a minute the other does: one cluster of two would report a depth the reader
     * cannot see, and each stays full width. */
    const placements = placeOverlaps([span(600, 600), span(600, 600)]);

    for (const placement of placements) expect(widthOf(placement)).toBe(1);
  });

  it("clusters a span crossing midnight with what it overlaps on the far side of it", () => {
    const overnight = span(1380, 1860);
    const early = span(1400, 1500);
    const placements = placeOverlaps([overnight, early]);

    expect(placements.map(widthOf)).toEqual([0.5, 0.5]);
  });

  it("places every span it is given, and places each exactly once", () => {
    const spans = Array.from({ length: 30 }, (_, index) => span(index * 5, index * 5 + 90));
    const placements = placeOverlaps(spans);

    expect(placements).toHaveLength(spans.length);
    for (const placement of placements) expect(placement).toBeDefined();
  });

  it("places nothing for an empty week without failing", () => {
    expect(placeOverlaps([])).toEqual([]);
  });
});
