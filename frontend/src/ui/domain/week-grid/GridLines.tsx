/* THE GRID LINES ACROSS ONE CANVAS.
 *
 * THE QUARTER HOUR IS DRAWN AT REST, because the snap is fifteen minutes and the grid should show where a block
 * can land. Only the hour carries cobalt weight and the three quarters are faint; during a drag the quarters step
 * up to hour weight, which `grid.css` keys on the grid's own attribute so one change re-weights the whole week.
 *
 * The lines are computed from the extent rather than from the day, so every column draws them at the same offsets
 * and an hour label in the axis lands on the line it names. */

import { lineOffsets } from "./geometry";
import { GRID_MAJOR_MINUTES, GRID_MINOR_MINUTES } from "./metrics";
import type { Extent } from "./types";
import "./grid.css";

export interface GridLinesProps {
  readonly extent: Extent;
  readonly pxPerMin: number;
}

const PLACES = 3;

export function GridLines({ extent, pxPerMin }: GridLinesProps) {
  return (
    <>
      {lineOffsets(extent, GRID_MINOR_MINUTES).map((minute) => {
        const isHour = minute % GRID_MAJOR_MINUTES === 0;
        return (
          <div
            aria-hidden="true"
            className={
              isHour
                ? "week-grid__line week-grid__line--hour"
                : "week-grid__line week-grid__line--quarter"
            }
            key={minute}
            style={{ top: `${((minute - extent.startMin) * pxPerMin).toFixed(PLACES)}px` }}
          />
        );
      })}
    </>
  );
}
