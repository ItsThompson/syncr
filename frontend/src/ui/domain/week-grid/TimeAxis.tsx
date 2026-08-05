/* THE TIME AXIS. Hour labels, and the now rule's own reading.
 *
 * Sticky at the left edge, so below --bp-compact the columns scroll under it and the reader keeps the one column
 * that says what a row means.
 *
 * THE LABEL IS A WALL TIME AND THE AXIS IS A DURATION, and on a transition day the two disagree by an hour. The
 * axis is one column serving seven, and a local day is 1380, 1440 or 1500 minutes long: an offset of 540 minutes
 * is 09:00 on six of them and 10:00 on the seventh. Naming the offset in the reference day's wall clock is the
 * only reading available to a shared axis, and it is the honest one, because what the axis measures is distance
 * from each column's own start. Past the end of a day the label continues into the next one, which is what makes
 * the Sunday-night frame's tail readable rather than mysterious. */

import { formatClock } from "../../primitives";
import { lineOffsets } from "./geometry";
import { GRID_MAJOR_MINUTES } from "./metrics";
import type { Extent } from "./types";
import "./grid.css";

export interface TimeAxisProps {
  readonly extent: Extent;
  readonly pxPerMin: number;
  readonly canvasHeightPx: number;
  /** Where the current minute falls, or null when now is outside the week on screen. */
  readonly nowMin: number | null;
}

const MINUTES_IN_DAY = 24 * 60;
const PLACES = 3;

export function TimeAxis({ extent, pxPerMin, canvasHeightPx, nowMin }: TimeAxisProps) {
  return (
    <div className="week-grid__axis">
      <div className="week-grid__axis-head" />
      <div
        className="week-grid__axis-canvas"
        style={{ height: `${canvasHeightPx.toFixed(PLACES)}px` }}
      >
        {lineOffsets(extent, GRID_MAJOR_MINUTES).map((minute) => (
          <span
            className="week-grid__hour"
            key={minute}
            style={{ top: `${((minute - extent.startMin) * pxPerMin).toFixed(PLACES)}px` }}
          >
            {formatClock(((minute % MINUTES_IN_DAY) + MINUTES_IN_DAY) % MINUTES_IN_DAY)}
          </span>
        ))}
        {nowMin === null ? null : (
          <span
            className="week-grid__now-time"
            style={{ top: `${((nowMin - extent.startMin) * pxPerMin).toFixed(PLACES)}px` }}
          >
            {formatClock(((nowMin % MINUTES_IN_DAY) + MINUTES_IN_DAY) % MINUTES_IN_DAY)}
          </span>
        )}
      </div>
    </div>
  );
}
