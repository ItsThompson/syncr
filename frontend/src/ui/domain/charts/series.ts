/* WHAT A CHART IS HANDED, and it is never a fetch result.
 *
 * A chart accepts already-computed quantities and already-formatted figures. The arithmetic that turns a plan
 * into an Area's minutes belongs to the screen that read the plan, and how an interval reads depends on a zone
 * the domain knows and a chart does not. What is left for a chart to compute is geometry: a share, an angle, a
 * width, a signed magnitude.
 *
 * UNALLOCATED IS A CATEGORY HERE, NOT AN ABSENCE. Discretionary time that no block covers is shown rather than
 * hidden, so it is a member of a composition and a row in the deviation bars like any Area. It holds no Area,
 * so it holds no step of the ramp: `ChartPigment` is the ramp plus that one vacancy, which is why a chart's
 * category carries a `ChartPigment` and not an `AreaPigment`. */

import type { AreaPigment } from "../marks/pigment";

/**
 * The vacancy: discretionary time covered by no block carrying an Area.
 *
 * Its own quantity, never a negative Area figure. Oversubscription is a separate quantity the screen reports
 * separately, so nothing here ever needs a negative minute count.
 */
export const UNALLOCATED = "unallocated";

/** What a chart paints a category with: a step of the sealed ramp, or the vacancy. */
export type ChartPigment = AreaPigment | typeof UNALLOCATED;

/**
 * One category's quantity, which a wedge or a stacked segment is sized from.
 *
 * `label` is not optional and is not decoration. Colour is never the only encoding of anything, three of the
 * twelve pigments sit on the sealed signal hues by construction, and past twelve Areas the ramp repeats: the
 * name is what identifies a wedge in every one of those cases.
 */
export interface AreaQuantity {
  readonly id: string;
  /** The Area's name, or `Unallocated`. */
  readonly label: string;
  readonly pigment: ChartPigment;
  /** Minutes the category holds. Zero and below draw nothing, and still take a label in the legend. */
  readonly minutes: number;
}

/** One legend row: the chip's ink, the name it is paired with, and the figure the caller formatted. */
export interface AreaLegendEntry {
  readonly id: string;
  readonly label: string;
  readonly pigment: ChartPigment;
  /** As the caller reads it: `18.4h`, `35.3%`. A chart does not know which unit a screen is showing. */
  readonly figure: string;
}

/**
 * One row of the signed deviation chart.
 *
 * NO PIGMENT FIELD, DELIBERATELY. A chart row is a chart context end to end: Area ink encodes identity and
 * cobalt encodes magnitude and direction, so a deviation row carries no Area ink anywhere, including its label
 * cell. A caller that passes one is refused by the typecheck rather than by review.
 */
export interface DeviationRow {
  readonly id: string;
  /** The Area's name, or `Unallocated`. The name is what identifies the row. */
  readonly label: string;
  readonly actual: number;
  readonly target: number;
}

/** Turns a magnitude into the figure a row reads, in whatever unit the screen is showing. */
export type FigureFormat = (magnitude: number) => string;

/** One week's bar: its label and the categories that make up its composition. */
export interface StackedBar {
  readonly id: string;
  /** Which week, as the caller reads it: `W06`, `Mon 10 Feb`. */
  readonly label: string;
  readonly segments: readonly AreaQuantity[];
}
