/* A BOUNDED METER, DRAWN WITH BLOCK CHARACTERS.
 *
 * BLOCK CHARACTERS ARE CORRECT HERE BECAUSE THE SCALE IS BOUNDED. Unlock progress runs 0 to 100% and has a known
 * end, so a segmented run reads as a fraction of something. `DataBar` is the unbounded case and is deliberately a
 * different form: the reason the two differ is stated there, so a later contributor does not unify them.
 *
 * IT IS NOT A PROGRESS BAR AND IT DOES NOT ADVANCE WHILE YOU WATCH IT. Motion is zero: the run moves when a
 * confirmed day is added, which is a discrete redraw of a number.
 *
 * THE CELL IS THE KIT'S GLYPH TABLE'S, not a codepoint written here. Every glyph in the product is declared once
 * in `ui/primitives/glyphs.css` and a component names a slot, which is what keeps two components from drawing two
 * different blocks.
 *
 * `role="meter"` IS THE SEMANTIC, and the cells are decorative. A run of fourteen identical characters says
 * nothing to a screen reader, so the value, the bound and the label carry the reading instead. */

import "../../primitives/glyphs.css";
import "./charts.css";

/**
 * Cells in the run. Fourteen is what fits the Learned screen's meter column at --fs-data.
 *
 * Not a prop: how a bounded scale is drawn is a design decision, and a caller choosing twenty would put two
 * meters with two resolutions on one screen.
 */
const CELLS = 14;

export interface MaturityMeterProps {
  /** How much has been collected: confirmed samples, so far. */
  readonly value: number;
  /** How much the parameter needs before it influences the solver. */
  readonly bound: number;
  /** Which parameter's progress this is, which is the meter's accessible name. */
  readonly label: string;
}

export function MaturityMeter({ value, bound, label }: MaturityMeterProps) {
  /* A bound of zero or less binds nothing, so there is nothing left to collect and the run is complete. Every
   * threshold in the product is a documented positive count, so this is a caller's error rather than a state:
   * what it must not be is a division by zero drawing an empty run for a parameter that is ready. */
  const reached = bound <= 0 ? 1 : Math.min(Math.max(value / bound, 0), 1);
  const full = Math.round(reached * CELLS);

  return (
    <span
      className="meter"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={bound}
      aria-valuenow={Math.min(value, bound)}
    >
      {Array.from({ length: CELLS }, (_, cell) => (
        <span
          key={cell}
          className={
            cell < full
              ? "glyph glyph--meter-cell meter__cell"
              : "glyph glyph--meter-cell meter__cell meter__cell--empty"
          }
          aria-hidden="true"
        />
      ))}
    </span>
  );
}
