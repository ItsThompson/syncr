/* THE STRIP'S FIGURES, AND THE ONE THAT IS A RATIO RATHER THAN A READING.
 *
 * Two of the three cells are a formatting decision and the third is arithmetic over two figures the server sent.
 * That distinction is the reason this file exists: the ratio must never be recomputed from anything the grid happens
 * to draw, because the strip and the pie review answer the same question and a second arithmetic is how they come to
 * answer it differently. What is asserted here is therefore the ratio of what it is GIVEN, including where the
 * denominator is one the server is still revising. */

import { describe, expect, it } from "vitest";

import { formatCurrency, formatHours, formatShare } from "../readings";

describe("a figure in hours", () => {
  it("reads to one decimal place, which is the precision a week is compared at", () => {
    expect(formatHours(4848)).toBe("80.8h");
    expect(formatHours(3126)).toBe("52.1h");
    expect(formatHours(1104)).toBe("18.4h");
  });

  it("reads a whole hour with its decimal, so three cells in a row align", () => {
    expect(formatHours(120)).toBe("2.0h");
  });

  it("reads zero as zero rather than as an absence", () => {
    expect(formatHours(0)).toBe("0.0h");
  });
});

describe("the share of discretionary time", () => {
  it("is the ratio of the two figures it is given, and nothing derived", () => {
    expect(formatShare(1104, 3126)).toBe("35.3% of discretionary");
  });

  it("is the same ratio whatever the denominator's own definition is under revision", () => {
    /* The two figures come from one server-side arithmetic, so the percentage is internally consistent even where
     * the denominator itself is being corrected. Recomputing it from what the grid draws would make two surfaces
     * disagree about a percentage, which is the failure the server-side computation exists to prevent. */
    expect(formatShare(1104, 6720)).toBe("16.4% of discretionary");
    expect(formatShare(1104, 10080)).toBe("11.0% of discretionary");
  });

  it("says there is none rather than reporting zero percent of nothing", () => {
    expect(formatShare(0, 0)).toBe("no discretionary time");
    expect(formatShare(120, 0)).toBe("no discretionary time");
  });

  it("reads a full week as a hundred percent rather than as an overflow", () => {
    expect(formatShare(3126, 3126)).toBe("100.0% of discretionary");
  });
});

describe("plan currency in the SCHEDULED cell's sub-line", () => {
  it("spells the count out when it is current, because the word would say nothing", () => {
    expect(formatCurrency(91, "current")).toBe("91 blocks");
  });

  it("qualifies the count with the word when it is not", () => {
    expect(formatCurrency(91, "solving")).toBe("91 · solving");
    expect(formatCurrency(91, "stale")).toBe("91 · stale");
  });

  it("never says anything that could be read as motion", () => {
    for (const currency of ["current", "solving", "stale"] as const) {
      expect(formatCurrency(91, currency)).not.toMatch(/\.\.\.|…/);
    }
  });

  it("reads a week with no blocks as none rather than as an empty string", () => {
    expect(formatCurrency(0, "current")).toBe("0 blocks");
  });
});
