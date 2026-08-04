/* THE PIE'S GEOMETRY, AS ARITHMETIC RATHER THAN AS RENDERING.
 *
 * Every boundary a composition has lives here, where it can be asserted without a DOM: no category, one
 * category, a category holding zero, a category holding a negative, and a thirteenth category that repeats a
 * pigment. A rendering test can then check that the component draws what this returns rather than re-deriving
 * it.
 *
 * ONE USER UNIT IS ONE CSS PIXEL. The svg carries its own width and height in the same units as its viewBox, so
 * the hatch tile stays at the pitch `tokens/color.css` declares. A scaled svg would scale the texture with it,
 * and the six patterns stop separating at wedge scale, which is the whole reason there are six and not twelve.
 *
 * ANGLES START AT TWELVE O'CLOCK AND RUN CLOCKWISE, as the rendered sheets draw them. */

import type { AreaQuantity, ChartPigment } from "./series";

/**
 * The box a labelled pie needs, in CSS pixels.
 *
 * The circle is the 168px the rendered screens draw. The gutter is what a label needs beside it: an Area name at
 * --fs-eyebrow in the mono family runs to roughly 100px, and a label clipped by the svg's own edge would be a
 * label that is not there.
 */
export const PIE = {
  radius: 84,
  /** Room for a label on each side of the circle. */
  labelGutter: 104,
  /** Gap between the arc and the start of its label. */
  labelGap: 7,
  /** Room above and below for a label's own line box at the top and bottom of the circle. */
  verticalPad: 12,
  /**
   * Smallest vertical distance between two labels in the same column.
   *
   * A glyph box at --fs-eyebrow is a little under 12px tall, so 13 leaves a hairline between two rows and is on
   * the system's own odd rhythm. Thirteen labels in one column need 169px, which the box above holds.
   */
  labelPitch: 13,
} as const;

export interface WedgeLabel {
  readonly x: number;
  readonly y: number;
  /** `start` on the right of the circle, `end` on the left, so a label always reads away from the arc. */
  readonly anchor: "start" | "end";
}

export interface Wedge {
  readonly id: string;
  readonly label: string;
  readonly pigment: ChartPigment;
  /** The category's share of the whole, 0 to 1. */
  readonly share: number;
  /** The `d` of the wedge's own path. A single category is a whole circle rather than a degenerate arc. */
  readonly d: string;
  readonly labelAt: WedgeLabel;
}

export interface PieLayout {
  readonly width: number;
  readonly height: number;
  readonly wedges: readonly Wedge[];
  /** The minutes the shares are taken against, which is the sum of what could be drawn. */
  readonly total: number;
}

const FULL_TURN = 360;
const HALF_TURN = 180;
/** Two decimals, which is what the rendered sheets emit and enough for a 168px circle. */
const PLACES = 2;

function round(value: number): string {
  return value.toFixed(PLACES);
}

function pointAt(angle: number, radius: number, centre: { x: number; y: number }) {
  const radians = (angle * Math.PI) / HALF_TURN;
  return { x: centre.x + radius * Math.cos(radians), y: centre.y + radius * Math.sin(radians) };
}

/**
 * A whole circle, drawn as two half arcs.
 *
 * A single category owns the full turn, and an arc whose start and end are the same point draws nothing at all:
 * that is the degenerate case every pie implementation meets and the reason this is not one arc.
 */
function circlePath(centre: { x: number; y: number }, radius: number): string {
  const top = pointAt(-90, radius, centre);
  const bottom = pointAt(90, radius, centre);
  return (
    `M${round(top.x)} ${round(top.y)}` +
    ` A${radius} ${radius} 0 1 1 ${round(bottom.x)} ${round(bottom.y)}` +
    ` A${radius} ${radius} 0 1 1 ${round(top.x)} ${round(top.y)}Z`
  );
}

function wedgePath(
  centre: { x: number; y: number },
  radius: number,
  from: number,
  to: number,
): string {
  const start = pointAt(from, radius, centre);
  const end = pointAt(to, radius, centre);
  const isMajor = to - from > HALF_TURN ? 1 : 0;
  return (
    `M${round(centre.x)} ${round(centre.y)}` +
    ` L${round(start.x)} ${round(start.y)}` +
    ` A${radius} ${radius} 0 ${isMajor} 1 ${round(end.x)} ${round(end.y)}Z`
  );
}

/**
 * Labels pushed apart until no two in a column overlap, keeping the order they sit in around the circle.
 *
 * A LABEL COLUMN IS WHY THE x IS FIXED PER SIDE. Two adjacent thin wedges anchor their labels at almost the same
 * point, and seven Areas is enough to produce it: the rendered composition puts `Transit`, `Projects`, `Research`
 * and `Admin` inside 6% of the circle between them. Pushing a label along the arc instead would move it INTO the
 * pie, because the arc's own x is inside the circle's horizontal extent near the top and bottom, so the labels sit
 * in two columns clear of the circle and only their height tracks their wedge.
 *
 * Two passes, plus the two clamps that keep the column inside the box. The first pushes each label down to clear
 * the one above it, the second pulls the column back up where that ran past the bottom. Spacing wins over the
 * frame if a column somehow holds more labels than the box has room for: `.pie` sets `overflow: visible`, so a
 * label past the edge is still drawn, while two labels on one line are two labels a reader cannot read.
 */
function spreadColumn(wanted: readonly number[], limit: { top: number; bottom: number }): number[] {
  if (wanted.length === 0) return [];
  const spread = [...wanted];
  spread[0] = Math.max(spread[0], limit.top);
  for (let index = 1; index < spread.length; index += 1) {
    spread[index] = Math.max(spread[index], spread[index - 1] + PIE.labelPitch);
  }
  spread[spread.length - 1] = Math.min(spread[spread.length - 1], limit.bottom);
  for (let index = spread.length - 2; index >= 0; index -= 1) {
    spread[index] = Math.min(spread[index], spread[index + 1] - PIE.labelPitch);
  }
  return spread;
}

interface Slot {
  readonly anchor: "start" | "end";
  readonly wantedY: number;
}

/** Where each label lands, in the order the wedges are drawn. */
function labelPositions(slots: readonly Slot[], height: number): WedgeLabel[] {
  const limit = { top: PIE.labelPitch / 2, bottom: height - PIE.labelPitch / 2 };
  /* An array rather than a map, so every slot has a place by construction: a lookup that could miss would need a
   * fallback height, and a fallback nothing can reach is a branch no test can cover. */
  const placed: number[] = Array.from({ length: slots.length }, () => 0);

  for (const anchor of ["start", "end"] as const) {
    /* Sorted by the height the wedge wants rather than by the order around the circle: the right column runs down
     * from twelve o'clock and the left column runs back up, so one of the two is always descending. */
    const column = slots
      .map((slot, index) => ({ index, ...slot }))
      .filter((slot) => slot.anchor === anchor)
      .toSorted((one, two) => one.wantedY - two.wantedY);
    const spread = spreadColumn(
      column.map((slot) => slot.wantedY),
      limit,
    );
    for (const [position, slot] of column.entries()) placed[slot.index] = spread[position];
  }

  return slots.map((slot, index) => ({
    x:
      slot.anchor === "start"
        ? PIE.radius + PIE.labelGutter + PIE.radius + PIE.labelGap
        : PIE.labelGutter - PIE.labelGap,
    y: Number(round(placed[index])),
    anchor: slot.anchor,
  }));
}

/**
 * The wedges a composition draws, with the box they need and the anchor each label sits at.
 *
 * A CATEGORY HOLDING NOTHING DRAWS NOTHING, AND KEEPS ITS ROW IN THE LEGEND. A zero-hour Area cannot be drawn
 * and dropping it from the ledger would hide what the period did not hold, so the legend is where it stays. A
 * negative takes the same path: the residual is reported as its own quantity and oversubscription is reported
 * separately, so a negative minute count is a caller's arithmetic error rather than a state to draw.
 */
export function layOutPie(slices: readonly AreaQuantity[]): PieLayout {
  const width = 2 * (PIE.radius + PIE.labelGutter);
  const height = 2 * (PIE.radius + PIE.verticalPad);
  const centre = { x: width / 2, y: height / 2 };

  const drawable = slices.filter((slice) => slice.minutes > 0);
  const total = drawable.reduce((sum, slice) => sum + slice.minutes, 0);
  if (drawable.length === 0) return { width, height, wedges: [], total: 0 };

  const drawn: (Omit<Wedge, "labelAt"> & Slot)[] = [];
  let filled = 0;
  for (const slice of drawable) {
    const from = -90 + (FULL_TURN * filled) / total;
    filled += slice.minutes;
    const to = -90 + (FULL_TURN * filled) / total;
    const middle = (from + to) / 2;
    drawn.push({
      id: slice.id,
      label: slice.label,
      pigment: slice.pigment,
      share: slice.minutes / total,
      d:
        drawable.length === 1
          ? circlePath(centre, PIE.radius)
          : wedgePath(centre, PIE.radius, from, to),
      anchor: Math.cos((middle * Math.PI) / HALF_TURN) >= 0 ? "start" : "end",
      wantedY: pointAt(middle, PIE.radius + PIE.labelGap, centre).y,
    });
  }

  const labels = labelPositions(drawn, height);
  return {
    width,
    height,
    wedges: drawn.map((wedge, index) => ({
      id: wedge.id,
      label: wedge.label,
      pigment: wedge.pigment,
      share: wedge.share,
      d: wedge.d,
      labelAt: labels[index],
    })),
    total,
  };
}
