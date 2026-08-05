/* The zoom clamp, against the three displays section 15 tabulates.
 *
 * THE THREE ROWS ARE THE MEASUREMENT, not an example. Section 15 records a 13 inch display at a 626px grid capping
 * at 16 hours, a 16 inch at 836px capping at 22, and a 27 inch at 1136px capping at 24. Asserting the formula
 * against those three is what makes this a claim about the product rather than about arithmetic. */

import { describe, expect, it } from "vitest";

import {
  WEEK_CHROME_ALLOWANCE_PX,
  ZOOM_MAX_HOURS,
  ZOOM_MIN_HOURS,
  capStatement,
  gridHeightFor,
  zoomCapHours,
  zoomLevels,
} from "../geometry";

describe("the zoom cap", () => {
  it("matches the three displays section 15 tabulates", () => {
    expect(zoomCapHours(626)).toBe(16);
    expect(zoomCapHours(836)).toBe(22);
    expect(zoomCapHours(1136)).toBe(24);
  });

  it("never exceeds the stored range, however tall the display", () => {
    expect(zoomCapHours(4000)).toBe(ZOOM_MAX_HOURS);
  });

  it("never falls below the stored range, however short the display", () => {
    expect(zoomCapHours(0)).toBe(ZOOM_MIN_HOURS);
    expect(zoomCapHours(120)).toBe(ZOOM_MIN_HOURS);
  });
});

describe("the grid height a window leaves", () => {
  it("is the window less the chrome above and below a grid", () => {
    expect(gridHeightFor(900)).toBe(900 - WEEK_CHROME_ALLOWANCE_PX);
  });

  it("is never negative, so a tiny window still yields the shallow end rather than a nonsense cap", () => {
    expect(gridHeightFor(100)).toBe(0);
    expect(zoomCapHours(gridHeightFor(100))).toBe(ZOOM_MIN_HOURS);
  });

  /* The 13 inch reference display is the one section 15 measures, and its row is the check on the allowance: a
   * 900px window has to leave a grid that caps where section 15 says a 13 inch display caps, which is 16 hours. */
  it("leaves the 13 inch reference window capping where section 15 says it does", () => {
    expect(gridHeightFor(900)).toBe(636);
    expect(zoomCapHours(gridHeightFor(900))).toBe(16);
  });
});

describe("the levels a select offers", () => {
  it("offers every level in the stored range, in order", () => {
    const levels = zoomLevels(626);

    expect(levels.at(0)?.hours).toBe(ZOOM_MIN_HOURS);
    expect(levels.at(-1)?.hours).toBe(ZOOM_MAX_HOURS);
    expect(levels).toHaveLength(ZOOM_MAX_HOURS - ZOOM_MIN_HOURS + 1);
  });

  /* Section 15's rule: a level past the cap is offered as unavailable rather than hidden, so the reader
   * understands the range rather than wondering where the rest went. */
  it("marks the levels past the cap unavailable rather than dropping them", () => {
    const levels = zoomLevels(626);
    const deepestAvailable = levels.findLast((level) => level.isAvailable);

    expect(deepestAvailable?.hours).toBe(16);
    expect(levels.find((level) => level.hours === 17)?.isAvailable).toBe(false);
    expect(levels.find((level) => level.hours === 24)?.isAvailable).toBe(false);
  });

  it("marks every level available where the display carries the whole range", () => {
    expect(zoomLevels(1136).every((level) => level.isAvailable)).toBe(true);
  });
});

describe("the reason the range stops where it does", () => {
  it("names the cap and the block length it protects", () => {
    const statement = capStatement(626);

    expect(statement).toContain("16 hours");
    expect(statement).toContain("thirty-minute block");
  });

  it("says the range is whole where nothing is capped, rather than naming a cap that did not apply", () => {
    expect(capStatement(1136)).toContain("whole range");
  });
});
