/* The three days at each end of a year where the calendar year and the ISO year disagree.
 *
 * Asserted against real dates rather than a formula, because a formula in a test is the implementation
 * written twice: every expectation here is what `date.isocalendar()` answers in the api that will refuse
 * a week the block does not belong to. */

import { describe, expect, it } from "vitest";

import { isoWeekOf } from "../isoWeek";

describe("isoWeekOf", () => {
  it("names the week of an ordinary date, as the api spells one", () => {
    expect(isoWeekOf("2026-02-09")).toBe("2026-W07");
    expect(isoWeekOf("2026-08-05")).toBe("2026-W32");
  });

  it("pads a single-digit week, so a week identifier is one length", () => {
    expect(isoWeekOf("2026-01-01")).toBe("2026-W01");
  });

  /* The case a derivation reading the calendar year off the date gets wrong. */
  it("puts the first days of January in the previous ISO year where they belong", () => {
    expect(isoWeekOf("2027-01-01")).toBe("2026-W53");
    expect(isoWeekOf("2021-01-01")).toBe("2020-W53");
  });

  it("puts the last days of December in the next ISO year where they belong", () => {
    expect(isoWeekOf("2019-12-30")).toBe("2020-W01");
  });

  it("counts a 53-week year to its 53rd week", () => {
    expect(isoWeekOf("2026-12-31")).toBe("2026-W53");
    expect(isoWeekOf("2016-01-03")).toBe("2015-W53");
    expect(isoWeekOf("2020-12-28")).toBe("2020-W53");
  });

  it("answers null for text that names no date, so nothing is recorded against a guess", () => {
    expect(isoWeekOf("")).toBeNull();
    expect(isoWeekOf("2026-02-30")).toBeNull();
    expect(isoWeekOf("2026-2-9")).toBeNull();
    expect(isoWeekOf("tomorrow")).toBeNull();
  });
});
