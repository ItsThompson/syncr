/* ACTUAL AGAINST TARGET PER AREA, signed off a zero rule. COBALT ONLY.
 *
 * NO AREA INK APPEARS ANYWHERE IN THIS COMPONENT, INCLUDING THE LABEL CELL, and that is the one rule it exists
 * to demonstrate. Area ink encodes identity and cobalt encodes magnitude and direction; giving the bar its
 * Area's pigment would make one channel carry both, and a chip beside a cobalt bar would imply the bar could
 * have been Area-coloured. The ramp's only legal chart carriers are a wedge fill and a stacked-bar fill, so a
 * deviation bar in an Area's own pigment would be a fourth carrier. The Area's NAME identifies the row, which is
 * what a name is for. A `DeviationRow` carries no pigment field, so a caller that passes one is refused by the
 * typecheck rather than by review.
 *
 * ALL THE ROWS, NOT ONE ROW PER COMPONENT. The scale is symmetric about zero and derived from the largest
 * absolute deviation in the set, so a single row cannot know how wide its own bar is. Handing the scale in as a
 * prop would make a caller that computed it wrongly silently clip the one row the chart exists to show.
 *
 * DIRECTION IS SIDE AND SIGN, NEVER HUE. Both bars are the same cobalt. */

import { cva } from "class-variance-authority";

import { plotDeviations, MINUS_SIGN } from "./deviation";
import type { DeviationRow, FigureFormat } from "./series";
import "./charts.css";

/* DIRECTION IS SIDE AND SIGN, NEVER HUE, so the side is a variant of one bar rather than two bars. Written as a
 * variant map because a variant is a named design decision, which is the kit's own rule. */
const bar = cva("deviation__bar", {
  variants: {
    side: {
      under: "deviation__bar--under",
      over: "deviation__bar--over",
      on: "",
    },
  },
});

export interface DeviationBarProps {
  readonly rows: readonly DeviationRow[];
  readonly caption: string;
  /** Turns a magnitude into the figure the row reads: hours on the Areas screen, points on the review. */
  readonly format: FigureFormat;
}

export function DeviationBar({ rows, caption, format }: DeviationBarProps) {
  const { plotted, scale } = plotDeviations(rows);

  return (
    <figure className="chart">
      <figcaption className="chart__caption">{caption}</figcaption>
      {plotted.length === 0 ? (
        <p className="chart__nothing">
          No category has a target in this period, so there is nothing to compare.
        </p>
      ) : (
        <>
          <div className="deviation__head">
            <span>Area</span>
            <span>under · zero · over</span>
            <span>actual · target</span>
          </div>
          {plotted.map(({ row, side, width, sign, deviation }) => (
            <div key={row.id} className="deviation__row">
              <span className="deviation__name">{row.label}</span>
              <span className="deviation__track">
                {side === "on" ? null : (
                  <span className={bar({ side })} style={{ width: `${width}%` }} />
                )}
                <span className="deviation__zero" />
              </span>
              <span className="deviation__figure">
                {sign}
                {format(Math.abs(deviation))}{" "}
                <span className="deviation__against">
                  {format(row.actual)} / {format(row.target)}
                </span>
              </span>
            </div>
          ))}
          {/* THE AXIS IS THE SCALE THE BARS WERE SIZED BY. With every row exactly on target there is no scale
              to state, and an axis reading zero at both ends would be a scale that does not exist. */}
          {scale === 0 ? null : (
            <div className="deviation__axis">
              <span>
                {MINUS_SIGN}
                {format(scale)} under target
              </span>
              <span>+{format(scale)} over target</span>
            </div>
          )}
        </>
      )}
    </figure>
  );
}
