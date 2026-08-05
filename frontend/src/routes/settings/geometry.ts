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
 * `__tests__/geometry.test.ts` asserts `gridHeightFor(REFERENCE_WINDOW_HEIGHT_PX) === GRID_H_PX`, so a change to
 * either side reddens rather than quietly moving the cap by one level. */

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
 * cap exists to prevent.
 */
export const WEEK_CHROME_ALLOWANCE_PX = REFERENCE_WINDOW_HEIGHT_PX - GRID_H_PX;

/** The grid height a window of this height leaves, never below zero. */
export function gridHeightFor(viewportHeightPx: number): number {
  return Math.max(0, viewportHeightPx - WEEK_CHROME_ALLOWANCE_PX);
}

/**
 * Why the range stops where it does, naming the cap so it reads as a range rather than as a missing feature.
 *
 * The per-level words are `zoomLevels`' own `unavailableReason`, which a reader sees only with the list open. This
 * is the field's hint, which they see without opening it, so it states the cap and the policy rather than
 * repeating one level's sentence. Both take the protected duration from the same constant.
 */
export function capStatement(gridHeightPx: number): string {
  const cap = zoomCap(gridHeightPx);
  if (cap >= ZOOM_MAX_HOURS) {
    return `This display carries the whole range, up to ${ZOOM_MAX_HOURS} hours at once.`;
  }
  return (
    `Past ${cap} hours a ${MODAL_DURATION_MINUTES}-minute block is too short to hold its title on this ` +
    "display, and that is the most common block length by a wide margin. Those levels are listed as " +
    "unavailable rather than removed, so the range reads as a range."
  );
}
