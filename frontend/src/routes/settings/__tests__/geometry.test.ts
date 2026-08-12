/* The grid height this screen supplies to the grid's own zoom range, and why it agrees with `--grid-h`.
 *
 * THE CAP'S OWN ARITHMETIC IS NOT TESTED HERE. It is `ui/domain/week-grid/zoom.ts`'s, and `zoom.test.ts` pins it
 * against the three reference displays. A second suite over the same function would be a second place for that
 * claim to be stated, which is the defect this file's own module had before. What the cases below are about is the
 * HEIGHT each screen feeds it.
 *
 * THE PIN IS AN IDENTITY RATHER THAN A MEASUREMENT. The allowance IS the reference window less `--grid-h`, so the
 * first case holds for whatever those two constants say, and what it refuses is a `gridHeightFor` that does
 * anything other than subtract one from the other. The calibration is held by the block below, which states the
 * window as a figure of its own: an assertion that takes the window from this module cannot see the window move.
 * The last block crosses this screen's answer against the grid's own, so the agreement is a comparison rather than
 * a restatement. */

import { describe, expect, it } from "vitest";

import { gridHeightPx } from "../../../ui/domain/week-grid/geometry";
import { DAY_HEADER_H_PX, GRID_H_PX, ZOOM_MIN_HOURS } from "../../../ui/domain/week-grid/metrics";
import { zoomCap } from "../../../ui/domain/week-grid/zoom";
import {
  REFERENCE_WINDOW_HEIGHT_PX,
  WEEK_CHROME_ALLOWANCE_PX,
  capStatement,
  gridHeightFor,
} from "../geometry";

describe("the grid height a window leaves", () => {
  /* THE PIN. `--grid-h` is the height the token states for a 1440x900 display, mirrored by `metrics.ts` and
   * asserted against the token by `metrics.test.ts`. This screen has no grid to measure, so it takes the
   * difference at that window, and this case is what refuses any other way of arriving at the height. */
  it("arrives at --grid-h by subtracting the allowance, and refuses any other route to it", () => {
    expect(gridHeightFor(REFERENCE_WINDOW_HEIGHT_PX)).toBe(GRID_H_PX);
  });

  /* The five, in the order the module's header names them: the top bar, the page band, the page padding, the
   * summary strip and the day header. */
  it("is the larger reading of the chrome than the bands measured directly", () => {
    const measuredBands = 43 + 63 + 66 + 64 + 28;

    expect(WEEK_CHROME_ALLOWANCE_PX).toBeGreaterThanOrEqual(measuredBands);
  });

  it("is the window less the chrome", () => {
    expect(gridHeightFor(1117)).toBe(1117 - WEEK_CHROME_ALLOWANCE_PX);
  });

  it("is never negative, so a tiny window still yields the shallow end rather than a nonsense cap", () => {
    expect(gridHeightFor(100)).toBe(0);
    expect(zoomCap(gridHeightFor(100))).toBe(ZOOM_MIN_HOURS);
  });
});

/* THE TWO ANSWERS, CROSSED AGAINST EACH OTHER RATHER THAN EACH AGAINST ITSELF.
 *
 * Settings answers from a window and the grid answers from an element, so a case that reads this module twice says
 * nothing about the pair. Each helper below takes its answer from the module that ships it, and
 * `gridHeightPx(element - DAY_HEADER_H_PX)` is the expression `WeekGrid.tsx` runs on its own measurement.
 *
 * WHAT THESE CASES DO NOT SHOW IS WHAT THE GRID'S ELEMENT MEASURES, and nothing in this suite can: jsdom is a DOM
 * and not a layout engine, so every height here is one a case supplies. The element fed below is the one `--grid-h`
 * describes, which is also the height the grid falls back on before a layout; whether a rendered grid measures that
 * is a browser question and `week-grid/__tests__/grid.test.tsx` stubs it too.
 *
 * `zoomCap` is `floor(gridPx / 38)` clamped, so sixteen levels need 608px and the reference grid's 626 carries 18px
 * of slack. That is what the pair survives, and it is why 19px of chrome the allowance does not know about is the
 * whole difference between naming 16 and drawing 15. */
const capSettingsNames = (windowHeightPx: number) => zoomCap(gridHeightFor(windowHeightPx));
const capTheGridDraws = (elementHeightPx: number) =>
  zoomCap(gridHeightPx(elementHeightPx - DAY_HEADER_H_PX));

/**
 * The window the display record states `--grid-h` against, as a figure of its own.
 *
 * Not `REFERENCE_WINDOW_HEIGHT_PX`: the allowance is derived from that constant, so a case that took the window
 * from it too would name the same cap whatever the constant said, and the calibration is the thing these cases
 * are for.
 */
const RECORD_WINDOW_PX = 900;

/** The element `--grid-h` describes: that canvas, plus the day header that sits inside the element with it. */
const ELEMENT_GRID_H_DESCRIBES_PX = GRID_H_PX + DAY_HEADER_H_PX;

describe("the cap this screen names and the cap the grid draws", () => {
  it("are both 16: this screen at a 900px window, the grid on the element --grid-h describes", () => {
    expect(capSettingsNames(RECORD_WINDOW_PX)).toBe(16);
    expect(capTheGridDraws(ELEMENT_GRID_H_DESCRIBES_PX)).toBe(16);
  });

  /* A first paint and a headless DOM both report zero, and the grid answers from `--grid-h` until a layout happens.
   * So this is the calibration itself: the allowance is what makes a 900px window name the height the grid falls
   * back on. */
  it("agree while nothing has been measured, because the estimate is calibrated on --grid-h", () => {
    expect(capTheGridDraws(0)).toBe(capSettingsNames(RECORD_WINDOW_PX));
  });

  it("part at 19px of chrome the allowance does not carry, and hold at 18", () => {
    expect(capTheGridDraws(ELEMENT_GRID_H_DESCRIBES_PX - 18)).toBe(16);
    expect(capTheGridDraws(ELEMENT_GRID_H_DESCRIBES_PX - 19)).toBe(15);
    expect(capSettingsNames(RECORD_WINDOW_PX)).toBe(16);
  });
});

describe("the reason the range stops where it does", () => {
  it("names the cap and the block length it protects", () => {
    const statement = capStatement(626);

    expect(statement).toContain("Past 16 hours a 30-minute block");
  });

  /* THE WHOLE SENTENCE BY EQUALITY, because this branch is the one no rendered case reaches: the range is whole
   * only past a 1186px window, and the screen's own suite runs at jsdom's. A `toContain` here would admit the
   * branch quietly dropping the clause that says where its figure came from. */
  it("says the range is whole where nothing is capped, and still says the figure is an estimate", () => {
    expect(capStatement(1136)).toBe(
      "This display carries the whole range, up to 24 hours at once. This screen is not rendering " +
        "that grid, so the figure is estimated from this window. The Week screen measures its own " +
        "grid and may allow a different level.",
    );
  });
});
