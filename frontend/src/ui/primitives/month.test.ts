/* The month grid, over the cases a calendar gets wrong.
 *
 * February 2025 is the reference week's month and the one `docs/design/components.html` renders, so the first
 * case is directly comparable with the sheet. The rest are the boundaries: a month starting on Sunday, a leap
 * day, a five-week month against a six-week one, and the year rolling over. */

import { describe, expect, it } from "vitest";

import {
  WEEKDAY_INITIALS,
  WEEKDAY_NAMES,
  daysInMonth,
  formatIsoDate,
  monthGrid,
  monthLabel,
  parseIsoDate,
  shiftDate,
  shiftMonth,
} from "./month";

describe("the weekday header", () => {
  it("starts on Monday, matching the ISO week the product is built on", () => {
    expect(WEEKDAY_INITIALS[0]).toBe("M");
    expect(WEEKDAY_NAMES[0]).toBe("Monday");
    expect(WEEKDAY_NAMES[6]).toBe("Sunday");
  });

  it("carries a full name per column, because two initials repeat", () => {
    expect(WEEKDAY_INITIALS).toHaveLength(WEEKDAY_NAMES.length);
    expect(new Set(WEEKDAY_INITIALS).size).toBeLessThan(WEEKDAY_NAMES.length);
    expect(new Set(WEEKDAY_NAMES).size).toBe(WEEKDAY_NAMES.length);
  });
});

describe("monthGrid", () => {
  it("puts the first of February 2025 under Saturday, which is the day it fell on", () => {
    const weeks = monthGrid({ year: 2025, month: 2 });

    expect(weeks[0][5]).toEqual({ iso: "2025-02-01", dayOfMonth: 1, isOutsideMonth: false });
  });

  it("marks the leading days as outside the month rather than dropping them", () => {
    const weeks = monthGrid({ year: 2025, month: 2 });
    const leading = weeks[0].filter((day) => day.isOutsideMonth);

    expect(leading.map((day) => day.iso)).toEqual([
      "2025-01-27",
      "2025-01-28",
      "2025-01-29",
      "2025-01-30",
      "2025-01-31",
    ]);
  });

  it("draws every week as a full seven days, so no cell is missing", () => {
    for (const month of [1, 2, 3, 6, 9, 12]) {
      for (const week of monthGrid({ year: 2025, month })) expect(week).toHaveLength(7);
    }
  });

  it("holds every day of the month exactly once", () => {
    const days = monthGrid({ year: 2025, month: 2 })
      .flat()
      .filter((day) => !day.isOutsideMonth);

    expect(days).toHaveLength(28);
    expect(new Set(days.map((day) => day.iso)).size).toBe(28);
  });

  it("draws February 2025 in five weeks and March 2025 in six", () => {
    expect(monthGrid({ year: 2025, month: 2 })).toHaveLength(5);
    expect(monthGrid({ year: 2025, month: 3 })).toHaveLength(6);
  });

  it("holds the leap day in February 2024", () => {
    const days = monthGrid({ year: 2024, month: 2 }).flat();

    expect(days.some((day) => day.iso === "2024-02-29" && !day.isOutsideMonth)).toBe(true);
  });

  it("puts a month that begins on Sunday in the last column of its first week", () => {
    const weeks = monthGrid({ year: 2025, month: 6 });

    expect(weeks[0][6].iso).toBe("2025-06-01");
    expect(weeks[0].slice(0, 6).every((day) => day.isOutsideMonth)).toBe(true);
  });
});

describe("daysInMonth", () => {
  it.each([
    [2025, 2, 28],
    [2024, 2, 29],
    [2025, 4, 30],
    [2025, 12, 31],
  ])("counts %i-%i as %i days", (year, month, days) => {
    expect(daysInMonth(year, month)).toBe(days);
  });
});

describe("shiftMonth", () => {
  it.each([
    [{ year: 2025, month: 2 }, 1, { year: 2025, month: 3 }],
    [{ year: 2025, month: 12 }, 1, { year: 2026, month: 1 }],
    [{ year: 2025, month: 1 }, -1, { year: 2024, month: 12 }],
    [{ year: 2025, month: 6 }, -13, { year: 2024, month: 5 }],
  ])("moves %o by %i months", (from, offset, expected) => {
    expect(shiftMonth(from, offset)).toEqual(expected);
  });
});

describe("shiftDate", () => {
  it.each([
    ["2025-02-01", 1, "2025-02-02"],
    ["2025-02-28", 1, "2025-03-01"],
    ["2025-03-01", -1, "2025-02-28"],
    ["2024-02-28", 1, "2024-02-29"],
    ["2025-02-19", 7, "2025-02-26"],
    ["2025-12-31", 1, "2026-01-01"],
  ])("moves %s by %i days to %s", (iso, offset, expected) => {
    expect(shiftDate(iso, offset)).toBe(expected);
  });

  it("refuses a date it cannot read", () => {
    expect(shiftDate("not-a-date", 1)).toBeNull();
  });
});

describe("parseIsoDate", () => {
  it("reads a calendar date without going through an instant", () => {
    expect(parseIsoDate("2025-02-19")).toEqual({ year: 2025, month: 2, day: 19 });
  });

  it.each(["2025-2-19", "2025-13-01", "2025-02-30", "2024-02-30", "", "19/02/2025"])(
    "refuses %s",
    (text) => {
      expect(parseIsoDate(text)).toBeNull();
    },
  );

  it("accepts the leap day in a leap year and refuses it otherwise", () => {
    expect(parseIsoDate("2024-02-29")).not.toBeNull();
    expect(parseIsoDate("2025-02-29")).toBeNull();
  });
});

describe("formatIsoDate", () => {
  it("pads every part, so a string sorts as a date", () => {
    expect(formatIsoDate(2025, 2, 1)).toBe("2025-02-01");
  });
});

describe("monthLabel", () => {
  it("reads as the sheet's own header", () => {
    expect(monthLabel({ year: 2025, month: 2 })).toBe("February 2025");
  });
});
