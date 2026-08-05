/* THE LADDER'S FOUR RUNGS AND THE LINE COUNT, ASSERTED AT THE FLOORS RATHER THAN IN THE MIDDLE OF EACH TIER.
 *
 * A floor is where a ladder is wrong: one pixel either side of 19 is the difference between a title and no title, so
 * every tier is checked at its own floor and one pixel below it. The line count is asserted against the arithmetic
 * the design record states rather than against a table of expected numbers, and then at the two heights where the
 * arithmetic and the tier disagree: a block at exactly the label floor has 18.8px of content and would compute one
 * line by rounding rather than by rule, and the compact tier is one line by definition rather than by division. */

import { describe, expect, it } from "vitest";

import {
  AREA_RULE_PX,
  BLOCK_H_COMPACT_PX,
  BLOCK_H_LABEL_PX,
  BLOCK_H_SLIVER_PX,
  BLOCK_PAD_T_PX,
  BOTTOM_RULE_PX,
  LINE_HEIGHT_PX,
} from "../metrics";
import { tierDrawsTitle, tierFor, titleLineCount } from "../tiers";

describe("the tier a height lands in", () => {
  it.each([
    [BLOCK_H_LABEL_PX, "label"],
    [BLOCK_H_LABEL_PX - 0.01, "compact"],
    [BLOCK_H_COMPACT_PX, "compact"],
    [BLOCK_H_COMPACT_PX - 0.01, "sliver"],
    [BLOCK_H_SLIVER_PX, "sliver"],
    [BLOCK_H_SLIVER_PX - 0.01, "hairline"],
    [0, "hairline"],
  ])("puts %spx in the %s tier", (heightPx, tier) => {
    expect(tierFor(heightPx)).toBe(tier);
  });

  it("has no gap and no ceiling: every height lands in exactly one rung", () => {
    for (let heightPx = 0; heightPx <= 200; heightPx += 0.5) {
      expect(["label", "compact", "sliver", "hairline"]).toContain(tierFor(heightPx));
    }
  });

  it("draws a title at the two upper tiers and at neither of the lower two", () => {
    expect(tierDrawsTitle("label")).toBe(true);
    expect(tierDrawsTitle("compact")).toBe(true);
    expect(tierDrawsTitle("sliver")).toBe(false);
    expect(tierDrawsTitle("hairline")).toBe(false);
  });
});

describe("the line count a wrapping title is clamped to", () => {
  const chromePx = AREA_RULE_PX + BLOCK_PAD_T_PX + BOTTOM_RULE_PX;

  it("is the design record's own arithmetic, at every height the label tier reaches", () => {
    for (let heightPx = BLOCK_H_LABEL_PX; heightPx <= 200; heightPx += 0.25) {
      expect(titleLineCount(heightPx)).toBe(
        Math.max(1, Math.floor((heightPx - chromePx) / LINE_HEIGHT_PX)),
      );
    }
  });

  it("is one at exactly the label floor, where the arithmetic alone would say none", () => {
    expect(Math.floor((BLOCK_H_LABEL_PX - chromePx) / LINE_HEIGHT_PX)).toBe(1);
    expect(titleLineCount(BLOCK_H_LABEL_PX)).toBe(1);
  });

  it("is one at the compact tier by definition rather than by division", () => {
    expect(titleLineCount(BLOCK_H_COMPACT_PX)).toBe(1);
    expect(titleLineCount(BLOCK_H_LABEL_PX - 0.01)).toBe(1);
  });

  it("is zero below the compact tier, where there is no title to count", () => {
    expect(titleLineCount(BLOCK_H_SLIVER_PX)).toBe(0);
    expect(titleLineCount(1)).toBe(0);
  });

  it("grows by one line for each further --lh-block-px of height, and never by half a line", () => {
    const twoLines = chromePx + 2 * LINE_HEIGHT_PX;

    expect(titleLineCount(twoLines - 0.01)).toBe(1);
    expect(titleLineCount(twoLines)).toBe(2);
    expect(titleLineCount(twoLines + LINE_HEIGHT_PX)).toBe(3);
  });

  /* The measured ledger's own case: the four titles that became ambiguous under end-ellipsis run 60 to 150 minutes,
   * so they are 52 to 130px tall at the twelve-hour default on the reference display. What the ledger's argument
   * needs is that those heights hold more than one line, because a second line is where the tail survives. */
  it("holds more than one line at the heights the real ambiguous titles occupy", () => {
    const pxPerMin = 626 / (12 * 60);

    for (const durationMinutes of [60, 90, 120, 150]) {
      expect(titleLineCount(durationMinutes * pxPerMin)).toBeGreaterThan(1);
    }
  });
});
