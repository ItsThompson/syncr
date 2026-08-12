/* How much of a window a grid gets, which is the one input the zoom range needs and this screen cannot measure.
 *
 * THE RANGE AND THE CLAMP ARE THE GRID'S OWN. `ui/domain/week-grid/zoom.ts` holds `zoomCap`, `zoomLevels` and
 * `clampVisibleHours`, and the Week screen draws from them. This file adds nothing to that arithmetic and must not
 * restate it: a second copy would let the Settings screen offer a level the grid then clamps, silently, which is
 * exactly what offering a level as unavailable with a stated reason exists to prevent.
 *
 * WHAT THIS SCREEN LACKS IS THE HEIGHT. The Week screen measures its own grid; Settings has no grid to measure, so
 * it computes the height a grid would get from the window and the chrome above and below one. That is the whole of
 * this module.
 *
 * THE ALLOWANCE IS DERIVED FROM `--grid-h`, NOT SUMMED FROM PARTS, and the difference matters. Five bands were
 * measured in Chrome at 1440x900 and they sum to 264px, which would leave a 636px grid. `--grid-h` says the grid
 * that window really gets is 626px, and `week-grid/metrics.ts` mirrors that token and asserts the mirror. So the
 * part-sum is 10px short of the real chrome: it names five bands and the shell has more. The token is the
 * authority, because it is the figure the grid's own arithmetic uses, and taking the difference at the reference
 * window is what makes the two incapable of drifting.
 *
 * THE FIGURE IS AN ESTIMATE AND THE HINT SAYS SO. The Week grid measures its own element; this screen subtracts a
 * constant from a window. The two agree at the reference window because the constant IS the difference there, and
 * they part as soon as the real chrome does. A reader cannot see that grid from here, so the hint names which of
 * the two figures they have been handed rather than leaving them to meet the disagreement on the other screen.
 *
 * `__tests__/geometry.test.ts` asserts `gridHeightFor(REFERENCE_WINDOW_HEIGHT_PX) === GRID_H_PX`, which refuses
 * any way of arriving at the height other than that subtraction. It is an identity rather than a measurement, so it
 * does not move when either constant does: what holds the calibration is the case beside it that states the window
 * as a figure of its own and crosses this screen's answer against the grid's own. */

import { GRID_H_PX, ZOOM_MAX_HOURS } from "../../ui/domain/week-grid/metrics";
import { MODAL_DURATION_MINUTES, zoomCap } from "../../ui/domain/week-grid/zoom";

/**
 * The window `--grid-h` is stated against: the 13 inch reference display, 1440x900.
 *
 * The one window where the grid's own height is written down, which is what lets the chrome be read off as the
 * difference rather than guessed at.
 */
export const REFERENCE_WINDOW_HEIGHT_PX = 900;

/**
 * What a window loses to chrome before a grid is drawn in it: the top bar, the page band, the padding, the
 * summary strip and the day headers.
 *
 * Derived rather than chosen, and it is the LARGER reading than the five bands measured directly, which is the
 * safe direction: overstating the chrome understates the grid, which offers one zoom level fewer than the display
 * could carry. Understating it would offer a level at which the modal block loses its title, which is what the
 * cap exists to prevent. That comparison is against bands measured at the reference window, and the direction is
 * not guaranteed at another one: the chrome is not a constant, which is why the hint calls the figure an estimate.
 */
export const WEEK_CHROME_ALLOWANCE_PX = REFERENCE_WINDOW_HEIGHT_PX - GRID_H_PX;

/** The grid height a window of this height leaves, never below zero. */
export function gridHeightFor(viewportHeightPx: number): number {
  return Math.max(0, viewportHeightPx - WEEK_CHROME_ALLOWANCE_PX);
}

/**
 * Where the figure in the sentences below came from, carried by both of them.
 *
 * On the capped sentence alone the whole-range sentence would go on offering the reader a cap as though this
 * screen had measured the grid it belongs to.
 */
const ESTIMATED_FROM_THE_WINDOW =
  "This screen is not rendering that grid, so the figure is estimated from this window. The Week " +
  "screen measures its own grid and may allow a different level.";

/**
 * Why the range stops where it does, naming the cap so it reads as a range rather than as a missing feature.
 *
 * The per-level words are `zoomLevels`' own `unavailableReason`, which a reader sees only with the list open. This
 * is the field's hint, which they see without opening it, so it states the cap, the policy and where the figure
 * came from rather than repeating one level's sentence. Both take the protected duration from the same constant.
 */
export function capStatement(gridHeightPx: number): string {
  const cap = zoomCap(gridHeightPx);
  if (cap >= ZOOM_MAX_HOURS) {
    return (
      `This display carries the whole range, up to ${ZOOM_MAX_HOURS} hours at once. ` +
      ESTIMATED_FROM_THE_WINDOW
    );
  }
  return (
    `Past ${cap} hours a ${MODAL_DURATION_MINUTES}-minute block is too short to hold its title on this ` +
    "display, and that is the most common block length by a wide margin. Those levels are listed as " +
    `unavailable rather than removed, so the range reads as a range. ${ESTIMATED_FROM_THE_WINDOW}`
  );
}
