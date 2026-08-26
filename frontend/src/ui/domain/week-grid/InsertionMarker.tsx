/* THE INSERTION MARKER: a hairline at the quarter hour under the cursor, and the time it names.
 *
 * IT IS THE WHOLE OF WHAT MOVES DURING A DRAG. The block stays where it is, so this is the only element whose
 * position is state, and dragging redraws one line rather than a week.
 *
 * DASHED, AT THE EMPHASISED WEIGHT, IN --ink-deep, which is what `docs/design/scratch/block-states.html` draws:
 * dashed says provisional, and a solid line at this weight would read as a block's own edge. The reading rides on
 * the marker rather than in the axis gutter, because the axis already names every hour and the reader is looking at
 * the cursor.
 *
 * THE READING IS AN ELEMENT RATHER THAN GENERATED CONTENT. The design record draws it from a `data-at` attribute,
 * which a scratch sheet with no components can do and this kit cannot: an attribute in the markup is a STATE here,
 * and the closed vocabulary is what keeps that set readable. A span carries the same words and is what a test reads.
 *
 * THE WHOLE MARKER IS DECORATIVE. It exists for the pointer, and the keyboard path states the same move in the
 * block's own accessible name, so announcing it would say one thing twice. */

import { formatClock } from "../../primitives";
import "./grid.css";

export interface InsertionMarkerProps {
  readonly topPx: number;
  /** Minutes from the column's own start, which is what the reading is taken from. */
  readonly atMin: number;
}

const PLACES = 3;
const MINUTES_IN_DAY = 24 * 60;

export function InsertionMarker({ topPx, atMin }: InsertionMarkerProps) {
  return (
    <div
      aria-hidden="true"
      className="week-insertion"
      style={{ top: `${topPx.toFixed(PLACES)}px` }}
    >
      <span className="week-insertion__at">{reading(atMin)}</span>
    </div>
  );
}

/**
 * The clock time a minute offset falls at, in the column's own day.
 *
 * A column's offsets may be negative or past 1440, because a span beginning the evening before is a block of the
 * column its start falls in. The reading wraps into the day rather than clamping, so an offset of -60 reads 23:00,
 * which is the time a reader would meet if they looked at their own clock.
 */
function reading(atMin: number): string {
  const wrapped = ((Math.floor(atMin) % MINUTES_IN_DAY) + MINUTES_IN_DAY) % MINUTES_IN_DAY; /* MUTATION M2: snap broken */
  return formatClock(wrapped);
}
