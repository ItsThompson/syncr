/* The grid height this screen supplies to the grid's own zoom range, and why it agrees with `--grid-h`.
 *
 * THE CAP AND THE LEVELS ARE NOT TESTED HERE. They are `ui/domain/week-grid/zoom.ts`'s, and `zoom.test.ts` pins
 * them against the three reference displays. A second suite over the same functions would be a second place for
 * that claim to be stated, which is the defect this file's own module had before.
 *
 * WHAT IS TESTED HERE IS THE PIN. The allowance is derived from `--grid-h` at the reference window, so the two
 * cannot drift; the first case is what makes a change to either side redden rather than move the cap by one level
 * on ten window heights in every thirty-eight. */

import { describe, expect, it } from "vitest";

import { GRID_H_PX, ZOOM_MIN_HOURS } from "../../../ui/domain/week-grid/metrics";
import { zoomCap } from "../../../ui/domain/week-grid/zoom";
import {
  REFERENCE_WINDOW_HEIGHT_PX,
  WEEK_CHROME_ALLOWANCE_PX,
  capStatement,
  gridHeightFor,
} from "../geometry";

describe("the grid height a window leaves", () => {
  /* THE PIN. `--grid-h` is the grid a 1440x900 window really gets, mirrored from the token and asserted against it
   * by `metrics.test.ts`. This screen has no grid to measure, so it takes the difference at that window: if either
   * side moves, this reddens. */
  it("equals --grid-h at the window --grid-h is stated against", () => {
    expect(gridHeightFor(REFERENCE_WINDOW_HEIGHT_PX)).toBe(GRID_H_PX);
  });

  it("caps at 16 hours on the 13 inch reference display, which is the recorded figure", () => {
    expect(zoomCap(gridHeightFor(REFERENCE_WINDOW_HEIGHT_PX))).toBe(16);
  });

  /* The five bands measured directly in Chrome sum to 264px. The token says the chrome is 274px, so the part-sum is
   * short: it names five bands and the shell has more. Taking the token means the chrome is OVERSTATED against the
   * measurement, which understates the grid and offers one level fewer, which is the safe direction. */
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

  /* The band the review found: at 916px the two figures disagreed, and this is where a re-divergence would show. */
  it("agrees with the grid on a window height either side of a cap boundary", () => {
    for (const height of [900, 916, 930, 976, 1117]) {
      expect(zoomCap(gridHeightFor(height))).toBe(zoomCap(height - WEEK_CHROME_ALLOWANCE_PX));
    }
  });
});

describe("the reason the range stops where it does", () => {
  it("names the cap and the block length it protects", () => {
    const statement = capStatement(626);

    expect(statement).toContain("16 hours");
    expect(statement).toContain("30-minute block");
  });

  it("says the range is whole where nothing is capped, rather than naming a cap that did not apply", () => {
    expect(capStatement(1136)).toContain("whole range");
  });
});
