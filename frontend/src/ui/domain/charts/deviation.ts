/* ACTUAL AGAINST TARGET, AS ARITHMETIC. Cobalt only, and direction is side and sign.
 *
 * THE SCALE IS SYMMETRIC ABOUT ZERO AND COMPUTED FROM THE LARGEST ABSOLUTE DEVIATION, so no bar is ever clipped
 * and the two directions stay comparable. A fixed span would clip whichever week went furthest off target,
 * which is precisely the week the chart exists to show. The axis is stated from the same figure the bars are
 * sized by, so the axis and the bars cannot disagree.
 *
 * DIRECTION IS NEVER A HUE. Under target extends one way from the zero rule, over target the other, and the
 * figure carries a `+` or a minus. There is no red-bad, green-good pair in this system: a signal pigment is
 * sealed to status and severity, and being five hours under on Research is neither. */

import type { DeviationRow } from "./series";

/**
 * U+2212 MINUS SIGN, not a hyphen: it sets at the width of the plus, so a column of signed figures aligns.
 *
 * The kit's glyph table makes the same choice for `--glyph-minus`, which the number stepper's decrease control
 * and the indeterminate checkbox draw, and `__tests__/deviation.test.ts` reads that entry out of the table and
 * asserts this is the same codepoint. It is real text rather than
 * generated content because the sign IS the reading here: a decorative glyph would leave a screen reader saying
 * "two hours" for a two-hour shortfall.
 */
export const MINUS_SIGN = "\u2212";

/** Half the track, which is what one direction gets. */
const HALF_TRACK = 50;
const PLACES = 2;

export interface PlottedDeviation {
  readonly row: DeviationRow;
  /** Actual less target. Negative is under target. */
  readonly deviation: number;
  readonly side: "under" | "over" | "on";
  /** Percentage of the whole track the bar occupies, 0 to 50. */
  readonly width: number;
  /** `+`, a minus sign, or nothing at all when the row is exactly on target. */
  readonly sign: string;
}

export interface DeviationPlot {
  readonly plotted: readonly PlottedDeviation[];
  /** The largest absolute deviation, which is what each end of the axis reads. */
  readonly scale: number;
}

export function plotDeviations(rows: readonly DeviationRow[]): DeviationPlot {
  const deviations = rows.map((row) => row.actual - row.target);
  const scale = deviations.reduce((largest, value) => Math.max(largest, Math.abs(value)), 0);

  return {
    scale,
    plotted: rows.map((row, index) => {
      const deviation = deviations[index];
      return {
        row,
        deviation,
        side: deviation < 0 ? "under" : deviation > 0 ? "over" : "on",
        /* Every row on target leaves nothing to scale against, and a bar of no width is the honest answer
         * rather than a division by zero. */
        width:
          scale === 0 ? 0 : Number(((Math.abs(deviation) / scale) * HALF_TRACK).toFixed(PLACES)),
        sign: deviation > 0 ? "+" : deviation < 0 ? MINUS_SIGN : "",
      };
    }),
  };
}
