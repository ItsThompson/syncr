/* The month grid's labels, which are what a screen reader reads.
 *
 * `dayLabel` is here rather than in the component because it is the cell's accessible name, and the tests that
 * find a day by that name have to use the same formatter: a test with its own copy would pass while a reader
 * heard something else. */

import { describe, expect, it } from "vitest";

import { dayLabel } from "./month";

describe("dayLabel", () => {
  it("reads as a date a person would say, weekday first", () => {
    expect(dayLabel("2025-02-19")).toBe("Wednesday, 19 February 2025");
  });

  it("names the weekday, because choosing a deadline is a question about which day it lands on", () => {
    expect(dayLabel("2025-02-14")).toContain("Friday");
  });

  it("hands back what it was given when that is not a date, rather than inventing one", () => {
    expect(dayLabel("not-a-date")).toBe("not-a-date");
  });
});
