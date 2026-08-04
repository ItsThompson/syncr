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

import { cva } from "class-variance-authority";

import "../../primitives/glyphs.css";
import "./charts.css";

/**
 * Cells in the run. Fourteen is what fits the Learned screen's meter column at --fs-data.
 *
 * Not a prop: how a bounded scale is drawn is a design decision, and a caller choosing twenty would put two
 * meters with two resolutions on one screen.
 */
const CELLS = 14;

/* A filled cell and an unfilled one are one variant with two values, which is what a variant map is for: the
 * kit's rule is that a variant is a named design decision, and the class lists stay where the markup scan
 * reads them. */
const cellClass = cva("glyph glyph--meter-cell meter__cell", {
  variants: {
    run: {
      full: "",
      empty: "meter__cell--empty",
    },
  },
});

export interface MaturityMeterProps {
  /** How much has been collected: confirmed samples, so far. */
  readonly value: number;
  /** How much the parameter needs before it influences the solver. */
  readonly bound: number;
  /** Which parameter's progress this is, which is the meter's accessible name. */
  readonly label: string;
}

export function MaturityMeter({ value, bound, label }: MaturityMeterProps) {
  /* ONE CLAMPED PAIR DRIVES BOTH CHANNELS, so the run a reader sees and the range a screen reader hears
   * cannot disagree. They did: passing the raw numbers through drew a complete run for a bound of zero while
   * reporting "0 of 0", and a negative bound or value put `aria-valuemax` and `aria-valuenow` outside
   * `[min, max]`, which ARIA forbids. For a reader on a screen reader the range IS the component, so the two
   * halves disagreeing is the whole component lying to one of its two audiences.
   *
   * A meter needs a bound that binds, and 1 is the smallest range ARIA can express: a non-positive bound is a
   * caller's error, and clamping it is what keeps the range valid rather than degenerate. Every threshold in
   * the product is a documented positive count, so no product path reaches either clamp. */
  const bounded = Math.max(bound, 1);
  const reached = Math.min(Math.max(value, 0), bounded);
  const full = Math.round((reached / bounded) * CELLS);

  return (
    <span
      className="meter"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={bounded}
      aria-valuenow={reached}
    >
      {Array.from({ length: CELLS }, (_, cell) => (
        <span
          key={cell}
          className={cellClass({ run: cell < full ? "full" : "empty" })}
          aria-hidden="true"
        />
      ))}
    </span>
  );
}
