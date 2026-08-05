/* THE ZOOM RANGE, AND THE CLAMP THE MODAL BLOCK PUTS ON IT.
 *
 * The user picks anywhere from 6 to 24 visible hours. The upper end is clamped per display so a THIRTY-MINUTE
 * block always keeps its title:
 *
 *   cap = floor( (grid height * 30) / (--block-h-label * 60) ), clamped to 6..24
 *
 * THE CLAMP IS COMPUTED FROM THE MODAL DURATION, NOT THE SHORTEST ONE. Thirty minutes is the most common block
 * length by a wide margin. Clamping to keep a fifteen-minute block labelled would cost half the range to
 * protect the blocks that are read from position anyway: those are the circadian frame, and their slivering at
 * the twelve-hour default on anything under a 27 inch display is accepted.
 *
 * A LEVEL PAST THE CAP IS OFFERED AS UNAVAILABLE WITH A STATED REASON, not hidden. Hiding it leaves the reader
 * wondering where the range went; saying why leaves them understanding the range they have. */

import { BLOCK_H_LABEL_PX, ZOOM_MAX_HOURS, ZOOM_MIN_HOURS } from "./metrics";

const MINUTES_IN_HOUR = 60;

/** The block length the clamp protects. The modal duration by a wide margin. */
export const MODAL_DURATION_MINUTES = 30;

/**
 * The deepest zoom this display offers, in visible hours.
 *
 * A grid so short that even six hours cannot hold a labelled thirty-minute block still reports six: the range
 * has to offer something, and below the floor the honest answer is the floor rather than an empty range.
 */
export function zoomCap(gridHeightPx: number): number {
  const cap = Math.floor(
    (gridHeightPx * MODAL_DURATION_MINUTES) / (BLOCK_H_LABEL_PX * MINUTES_IN_HOUR),
  );
  return Math.min(ZOOM_MAX_HOURS, Math.max(ZOOM_MIN_HOURS, cap));
}

/** One offerable zoom level: how many hours it shows, and why it cannot be picked when it cannot. */
export interface ZoomLevel {
  readonly hours: number;
  readonly isAvailable: boolean;
  /** Null when the level is available. Otherwise what the control says instead of going quiet. */
  readonly unavailableReason: string | null;
}

/**
 * Every level in the range, each carrying whether this display can offer it.
 *
 * The whole 6..24 range is returned at every display size, because the count of levels is what tells the reader
 * how deep the range goes, and a range that shortens on a small screen reads as a missing feature.
 */
export function zoomLevels(gridHeightPx: number): ZoomLevel[] {
  const cap = zoomCap(gridHeightPx);
  const levels: ZoomLevel[] = [];
  for (let hours = ZOOM_MIN_HOURS; hours <= ZOOM_MAX_HOURS; hours += 1) {
    const isAvailable = hours <= cap;
    levels.push({
      hours,
      isAvailable,
      unavailableReason: isAvailable
        ? null
        : `${hours}h would draw a ${MODAL_DURATION_MINUTES}-minute block too short for its title on this display`,
    });
  }
  return levels;
}

/** The visible-hours setting brought inside the range this display offers. */
export function clampVisibleHours(visibleHours: number, gridHeightPx: number): number {
  return Math.min(zoomCap(gridHeightPx), Math.max(ZOOM_MIN_HOURS, Math.round(visibleHours)));
}
