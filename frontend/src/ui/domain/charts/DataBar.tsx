/* A RANKED MAGNITUDE: one fill at a percentage width.
 *
 * WHY THIS IS NOT DRAWN WITH BLOCK CHARACTERS, AND WHY `MaturityMeter` IS. The two look similar and answer
 * different questions, so a later contributor should not unify them. A meter is bounded 0 to 100%: its scale has
 * a known end, so a segmented run reads as a fraction OF something and the segmented look is the aesthetic. A
 * ranked bar carries an arbitrary magnitude with no such end, and block characters offer roughly fourteen steps
 * at this size: a range above 20:1 between the leader and the tail would collapse every non-leading row to a
 * one-cell stub. So this is a rectangle whose width is a percentage of the leader, which is not a chart at all
 * and needs no library.
 *
 * IT IS COBALT, NOT AREA INK. A magnitude is not an identity. */

import "./charts.css";

const PERCENT = 100;
const PLACES = 2;

export interface DataBarProps {
  readonly value: number;
  /** The magnitude this row is ranked against, which is the largest value in the set. */
  readonly max: number;
  /**
   * What the bar says, for a reader who cannot see it: `3.5h, 58% of the leader`.
   *
   * Required, because a bar is the only representation of its own figure in some rows and an unlabelled graphic
   * is nothing at all to a screen reader. The `Plate`'s empty alt text is the opposite case, and deliberately:
   * a plate carries no information and this carries all of the row's.
   */
  readonly label: string;
}

export function DataBar({ value, max, label }: DataBarProps) {
  /* A non-positive maximum leaves nothing to rank against, and a bar of no width is the honest answer rather
   * than a division by zero. A value past the maximum fills the bar rather than overflowing its track. */
  const filled = max <= 0 ? 0 : Math.min(Math.max(value / max, 0), 1) * PERCENT;

  return (
    <span className="ranked-bar" role="img" aria-label={label}>
      <span className="ranked-bar__fill" style={{ width: `${filled.toFixed(PLACES)}%` }} />
    </span>
  );
}
