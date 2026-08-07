/* THE WEEK BEFORE AND THE WEEK AFTER, ACROSS THE BOUNDARIES THAT ARE THE WHOLE REASON THIS MODULE EXISTS.
 *
 * `[` and `]` rest entirely on `weekAway`, and an ISO year is not a calendar year: incrementing the number and reusing
 * the year is wrong at both ends of a year, for up to three days each side. So the cases here are the boundaries
 * rather than a sample of the middle:
 *
 *   2026 has 53 weeks, because 1 January 2026 is a Thursday, so `2026-W53` runs into January 2027
 *   2020 has 53 weeks, so `2020-W01` is preceded by `2019-W52` and `2021-W01` is preceded by `2020-W53`
 *   2019 has 52, so the same step one year earlier lands on a different number
 *
 * Every expectation is a date a reader can check on a calendar, which is why `mondayOf` is asserted beside the step:
 * a step that was right about the number and wrong about the Monday would still be wrong about the week. */

import { describe, expect, it } from "vitest";

import { mondayOf, weekAway } from "../weeks";

describe("mondayOf", () => {
  it.each([
    ["2026-W07", "2026-02-09"],
    ["2026-W01", "2025-12-29"],
    ["2026-W53", "2026-12-28"],
    ["2020-W01", "2019-12-30"],
    ["2019-W01", "2018-12-31"],
    ["2021-W01", "2021-01-04"],
  ])("%s begins on %s", (isoWeek, monday) => {
    expect(mondayOf(isoWeek)).toBe(monday);
  });

  it.each(["", "2026", "2026-W", "2026-W1", "26-W07", "2026-W00", "2026-W54", "next week"])(
    "answers null for %o, which names no week",
    (text) => {
      expect(mondayOf(text)).toBeNull();
    },
  );
});

describe("weekAway", () => {
  it.each([
    ["2026-W07", 1, "2026-W08"],
    ["2026-W07", -1, "2026-W06"],
    ["2026-W07", 0, "2026-W07"],
  ])("steps %s by %i to %s inside one year", (from, steps, to) => {
    expect(weekAway(from, steps)).toBe(to);
  });

  /* THE BOUNDARY CASES, which are what the arithmetic is for. A 53-week year is the one a naive implementation gets
   * wrong in both directions. */
  it.each([
    ["2026-W53", 1, "2027-W01"],
    ["2027-W01", -1, "2026-W53"],
    ["2026-W52", 1, "2026-W53"],
    ["2020-W01", -1, "2019-W52"],
    ["2019-W52", 1, "2020-W01"],
    ["2021-W01", -1, "2020-W53"],
    ["2020-W53", 1, "2021-W01"],
  ])("steps %s by %i to %s across a year", (from, steps, to) => {
    expect(weekAway(from, steps)).toBe(to);
  });

  it("steps several weeks at once, so a caller is not obliged to loop", () => {
    expect(weekAway("2026-W07", 4)).toBe("2026-W11");
    expect(weekAway("2026-W07", -8)).toBe("2025-W51");
  });

  /* A CALLER HOLDING A WEEK THIS CANNOT READ GETS ITS OWN WEEK BACK, not a guess. `[` on a malformed URL parameter
   * must leave the reader where they are rather than navigating to a week nothing computed. */
  it("hands back what it was given when the text names no week", () => {
    expect(weekAway("2026-W54", 1)).toBe("2026-W54");
    expect(weekAway("", -1)).toBe("");
  });

  it("is its own inverse over a year boundary, which a wrong year would not be", () => {
    for (const isoWeek of ["2026-W53", "2027-W01", "2020-W01", "2019-W52", "2020-W53"]) {
      expect(weekAway(weekAway(isoWeek, 1), -1)).toBe(isoWeek);
    }
  });
});
