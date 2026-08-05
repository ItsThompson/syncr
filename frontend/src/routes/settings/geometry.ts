/* The grid geometry this screen sets, and the range it may set it within.
 *
 * VISIBLE HOURS IS CLAMPED BY THE DISPLAY, NOT ONLY BY THE STORED BOUNDS. The api accepts 6 to 24, and section
 * 15 caps the deep end per display so that a thirty-minute block, which is the modal duration by a wide margin,
 * always keeps its title: `cap = floor((grid height * 30) / (--block-h-label * 60))`, clamped to the same 6 to
 * 24. A zoom level at which the most common block in the system is unreadable is not a useful level.
 *
 * A LEVEL PAST THE CAP IS OFFERED AS UNAVAILABLE RATHER THAN HIDDEN, which is section 15's own rule: a range
 * that silently shortens leaves a reader wondering where the rest went, and one that states the reason teaches
 * them what the cap is for. The option keeps its number and gains the word.
 *
 * THIS SCREEN HAS NO GRID TO MEASURE, so the height the cap is computed from is the viewport's less one named
 * allowance for the chrome above and below a grid. The allowance is measured rather than reasoned: see the
 * constant. Being one number in one place is what makes the cap here and the cap on the Week screen the same
 * arithmetic over a different input rather than two rules.
 *
 * THE CONSTANTS ARE THE GRID'S OWN. `ui/domain/week-grid/metrics.ts` mirrors them from the tokens that draw
 * them and asserts the mirror, so reading them here rather than restating them is what keeps one definition of
 * what a label tier costs. */

import {
  BLOCK_H_LABEL_PX,
  ZOOM_MAX_HOURS,
  ZOOM_MIN_HOURS,
} from "../../ui/domain/week-grid/metrics";

/** The duration the cap protects: the modal block length, thirty minutes. */
const MODAL_BLOCK_MINUTES = 30;
const MINUTES_IN_HOUR = 60;

/* WHAT THE WEEK SCREEN'S CHROME COSTS, above and below the grid, part by part.
 *
 * Every figure is measured in Chrome at a 1440x900 viewport against the shell as it stands, or read from the token
 * that sets it. A sum by parts rather than one number, so a reader can check each one and see which changed when a
 * band's height does.
 *
 * The sum is checkable against section 15's own table: a 900px window leaves a 636px grid, which caps at 16 hours,
 * and 16 is what section 15 records for the 13 inch reference display. `__tests__/geometry.test.ts` asserts that. */

/** The top bar: `--h-control` for the notice slot, `py-2` either side, and its bottom hairline. */
const TOP_BAR_PX = 26 + 8 + 8 + 1;
/** The page band: the serif title at `--fs-title` and `--lh-tight`, `py-2.75` either side, and its hairline. */
const PAGE_BAND_PX = 40 + 11 + 11 + 1;
/** The main region's own `py-5`, and the route band's body `py-3.25`. */
const ROUTE_PADDING_PX = 20 + 20 + 13 + 13;
/** `--strip-h`: the summary and verdict strip, pinned above the grid at a reserved height. */
const STRIP_PX = 64;
/** `--day-header-h`: the seven day headers above the columns. */
const DAY_HEADER_PX = 28;

/**
 * What the window loses to chrome before a grid is drawn in it.
 *
 * It is deliberately the LARGER reading. Overstating it understates the cap, which offers one zoom level fewer than
 * the display could carry; understating it would offer a level at which the modal block loses its title, which is
 * the thing the cap exists to prevent.
 */
export const WEEK_CHROME_ALLOWANCE_PX =
  TOP_BAR_PX + PAGE_BAND_PX + ROUTE_PADDING_PX + STRIP_PX + DAY_HEADER_PX;

/**
 * The deepest zoom a grid of this height can carry with a thirty-minute block still labelled.
 *
 * Clamped to the stored range at both ends, so a display too short to carry six hours still offers six: the
 * shallow end is a stored bound rather than a legibility one, and a range with nothing in it is not a range.
 */
export function zoomCapHours(gridHeightPx: number): number {
  const cap = Math.floor(
    (gridHeightPx * MODAL_BLOCK_MINUTES) / (BLOCK_H_LABEL_PX * MINUTES_IN_HOUR),
  );
  return Math.min(ZOOM_MAX_HOURS, Math.max(ZOOM_MIN_HOURS, cap));
}

/** The grid height a window of this height leaves, never below zero. */
export function gridHeightFor(viewportHeightPx: number): number {
  return Math.max(0, viewportHeightPx - WEEK_CHROME_ALLOWANCE_PX);
}

/** One selectable zoom level: the hours, and whether this display can draw them. */
export interface ZoomLevel {
  readonly hours: number;
  readonly isAvailable: boolean;
}

/** Every level in the stored range, in order, each marked available or not for a grid of this height. */
export function zoomLevels(gridHeightPx: number): readonly ZoomLevel[] {
  const cap = zoomCapHours(gridHeightPx);
  const levels: ZoomLevel[] = [];
  for (let hours = ZOOM_MIN_HOURS; hours <= ZOOM_MAX_HOURS; hours += 1) {
    levels.push({ hours, isAvailable: hours <= cap });
  }
  return levels;
}

/** Why the levels past the cap are not offered, naming the cap so the range is understandable. */
export function capStatement(gridHeightPx: number): string {
  const cap = zoomCapHours(gridHeightPx);
  if (cap >= ZOOM_MAX_HOURS) {
    return `This display carries the whole range, up to ${ZOOM_MAX_HOURS} hours at once.`;
  }
  return (
    `Past ${cap} hours a thirty-minute block is too short to hold its title on this display, and thirty ` +
    "minutes is the most common block length by a wide margin. Those levels are listed as unavailable " +
    "rather than removed, so the range reads as a range."
  );
}

export { ZOOM_MAX_HOURS, ZOOM_MIN_HOURS };
