/* Which past days one backfill settles.
 *
 * The window is the one the api counts over and bounds a range by, so the assertion is the width and the
 * end: 28 days, ending the day before the one on screen. Today is confirmed by its own control. */

import { describe, expect, it } from "vitest";

import { UNCONFIRMED_LOOKBACK_DAYS, backfillRange } from "../backfill";
import { DATE } from "./fixtures";

const MS_IN_DAY = 24 * 60 * 60 * 1000;

describe("backfillRange", () => {
  it("covers the days the count of unconfirmed days is taken over", () => {
    const range = backfillRange(DATE);

    expect(range).toEqual({ from: "2026-01-12", to: "2026-02-08" });
    const days = (Date.parse(range.to) - Date.parse(range.from)) / MS_IN_DAY + 1;
    expect(days).toBe(UNCONFIRMED_LOOKBACK_DAYS);
  });

  it("ends the day before the one on screen, because today is confirmed by its own control", () => {
    expect(backfillRange("2026-03-01").to).toBe("2026-02-28");
  });

  it("crosses a year boundary through the calendar rather than by subtracting from a number", () => {
    expect(backfillRange("2026-01-05")).toEqual({ from: "2025-12-08", to: "2026-01-04" });
  });
});
