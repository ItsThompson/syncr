/* THE SIX HATCHES, WHICH AREA HOLDS WHICH, AND THE ONE PLACE THAT ANSWER IS DRAWN IN SVG.
 *
 * Hatch is the redundancy that keeps colour from being the only encoding of a category. It is ALWAYS ON and it
 * is not an accessibility toggle: roughly one man in twelve cannot separate twelve categorical hues, and three
 * of the ramp's pigments sit on the sealed signal hues by construction, so a bare fill says nothing reliable.
 * Each hatch is drawn in a lighter step of the wedge's own ink, so it reads as texture rather than as a second
 * colour.
 *
 * HATCH HAS EXACTLY THREE USES IN THE PRODUCT and this family owns the first: Area redundancy on a chart fill,
 * an external anchor's fill in --rule, and a forbidden window in --rule. There is no fourth, which is why
 * `Unallocated` takes a flat fill: it holds no Area, so there is no Area identity for a texture to be
 * redundant about.
 *
 * WHY THE GEOMETRY IS STATED HERE AT ALL. The six textures are declared once, in `tokens/color.css`, as CSS
 * gradients. A stacked segment and a legend chip read those tokens directly and restate nothing. An SVG
 * `<pattern>` cannot: its tile size and its rotation are ATTRIBUTES, and an attribute cannot hold a `var()`.
 * So the pie's patterns need the same angles, pitches and line widths as numbers, and `__tests__/hatch.test.ts`
 * DERIVES them from the token declarations and fails on a disagreement. The token layer stays the authority and
 * this file stays a checked derivation of it, which is the only shape available across that boundary. */

import type { ChartPigment } from "./series";
import { UNALLOCATED } from "./series";
import type { AreaPigment } from "../marks/pigment";

/**
 * The six patterns, named as `docs/design/specimen.html` names them.
 *
 * Six is the honest ceiling: past that they stop separating at wedge scale, so a pattern repeats only between
 * hues that are far apart.
 */
export const HATCH_NAMES = ["fwd", "back", "vert", "horz", "cross", "dot"] as const;

export type HatchName = (typeof HATCH_NAMES)[number];

/** Stripes, at one or two angles. `angles` are CSS gradient degrees, as the token declares them. */
export interface HatchStripes {
  readonly kind: "stripes";
  readonly angles: readonly number[];
  readonly lineWidth: number;
  /** Distance between one line and the next, which is the pattern tile's side. */
  readonly pitch: number;
}

/** A dot grid, which is the one pattern that is not a stripe and the one that needs a tile size token. */
export interface HatchDots {
  readonly kind: "dots";
  readonly radius: number;
  readonly pitch: number;
}

export type HatchGeometry = HatchStripes | HatchDots;

export const HATCH_GEOMETRY: Readonly<Record<HatchName, HatchGeometry>> = {
  fwd: { kind: "stripes", angles: [45], lineWidth: 1, pitch: 5 },
  back: { kind: "stripes", angles: [135], lineWidth: 1, pitch: 5 },
  vert: { kind: "stripes", angles: [90], lineWidth: 1, pitch: 5 },
  horz: { kind: "stripes", angles: [0], lineWidth: 1, pitch: 5 },
  cross: { kind: "stripes", angles: [45, 135], lineWidth: 1, pitch: 6 },
  dot: { kind: "dots", radius: 0.9, pitch: 5 },
};

/**
 * Which pattern each step of the ramp holds.
 *
 * Ported from `docs/design/specimen.html`, which ported it from `scratch/block-states.html`: the sheets and the
 * kit must not disagree about which Area holds which hatch, and `__tests__/hatch.test.ts` reads the sheet and
 * asserts they do not. Adjacent pigments never share one, which is what protects the ramp's four tightest hue
 * pairs.
 */
export const AREA_HATCHES: Readonly<Record<AreaPigment, HatchName>> = {
  "01": "fwd",
  "02": "vert",
  "03": "dot",
  "04": "cross",
  "05": "back",
  "06": "fwd",
  "07": "horz",
  "08": "vert",
  "09": "dot",
  "10": "cross",
  "11": "horz",
  "12": "back",
};

/**
 * The hatch a category takes, or null for the vacancy, which takes none.
 *
 * NO TWO CATEGORIES ON A CHART HOLD ONE STEP. The deal skips the steps already held, a declaration past twelve
 * is refused, and a re-pick onto a held step is refused too, so the pair cannot repeat: every fill is
 * redundant about a step no other Area carries. The Area's NAME stays required regardless, because ink has
 * never been the whole of what identifies anything, which is why every wedge is labelled and every legend row
 * names its Area.
 */
export function hatchFor(pigment: ChartPigment): HatchName | null {
  return pigment === UNALLOCATED ? null : AREA_HATCHES[pigment];
}

/**
 * The `patternTransform` rotation, in degrees, that turns a tile of vertical lines into a CSS gradient's stripes.
 *
 * A `repeating-linear-gradient(Adeg, ...)` points its axis A degrees clockwise from up and lays its stripes
 * across that axis, so the stripes run in direction `(cos A, sin A)` in screen coordinates. An SVG tile holding
 * a vertical line, direction `(0, 1)`, rotated by R lands in direction `(-sin R, cos R)`. The two are the same
 * line when R = A + 90, and a line is undirected so the answer is only meaningful modulo 180. `hatch.test.ts`
 * derives both directions from first principles and asserts they are parallel, which is a check on this
 * arithmetic rather than a restatement of it.
 */
export function patternRotation(angle: number): number {
  return (angle + 90) % 180;
}

/**
 * The pigments a set of categories draws, each once, in the order they first appear.
 *
 * A pie declares one pattern per pigment rather than one per wedge, because a pattern belongs to a step of the
 * ramp rather than to a wedge: every wedge holding that step draws the identical tile. No two Areas hold one
 * step any more, so one declaration per drawn step is exact, and minting a second identical pattern would
 * state nothing.
 */
export function distinctPigments(pigments: readonly ChartPigment[]): ChartPigment[] {
  return [...new Set(pigments)];
}
