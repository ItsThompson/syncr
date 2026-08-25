/* COMPOSITION NOW: a pie, wedges hatched, labels outside.
 *
 * A pie answers "what is the shape of my time", which is the model the user already holds, and it is the one
 * chart in the product the Area ramp exists for. It cannot answer "how far off target am I", because it shows
 * one series: that is the deviation bars' job.
 *
 * SVG, SO EACH WEDGE CARRIES ITS OWN HATCH. Colour is never the only encoding of a category, so every wedge
 * pairs its pigment with a texture in a lighter step of its own ink, always on.
 *
 * LABELS SIT OUTSIDE THE WEDGES. A wedge fill only has to clear 3:1 as an indicator and text on a fill would
 * need 4.5:1, so no label is drawn on one. The label is the category's NAME rather than its figure: the name
 * identifies a wedge wherever its ink cannot, and the figures are the legend's column.
 *
 * NO SIZE COMES FROM CSS. One user unit is one CSS pixel, which is what holds the hatch at the pitch the token
 * layer declares. */

import { useId } from "react";

import type { AreaQuantity } from "./series";
import { layOutPie } from "./wedges";
import { WedgePatterns, patternId } from "./WedgePatterns";
import "./charts.css";

/** A fragment reference is a plain name, and React's generated ids are not, so the punctuation goes. */
function referenceable(id: string): string {
  return id.replaceAll(/[^\w-]/g, "");
}

export interface PieChartProps {
  readonly slices: readonly AreaQuantity[];
  /** What the pie is of, stated above it and used as the graphic's accessible name. */
  readonly caption: string;
}

export function PieChart({ slices, caption }: PieChartProps) {
  const prefix = referenceable(useId());
  const { width, height, wedges } = layOutPie(slices);

  return (
    <figure className="chart">
      <figcaption className="chart__caption">{caption}</figcaption>
      {wedges.length === 0 ? (
        <p className="chart__nothing">
          No category holds any time in this period, so there is no composition to draw.
        </p>
      ) : (
        <svg
          className="pie"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={caption}
        >
          <WedgePatterns idPrefix={prefix} pigments={wedges.map((wedge) => wedge.pigment)} />
          {wedges.map((wedge) => (
            <path
              key={wedge.id}
              className="pie__wedge"
              d={wedge.d}
              fill={`url(#${patternId(prefix, wedge.pigment)})`}
            />
          ))}
          {wedges.map((wedge) => (
            <text
              key={wedge.id}
              className="pie__label"
              x={wedge.labelAt.x}
              y={wedge.labelAt.y}
              textAnchor={wedge.labelAt.anchor}
              dominantBaseline="middle"
            >
              {wedge.label}
              {wedge.name !== wedge.label ? <title>{wedge.name}</title> : null}
            </text>
          ))}
        </svg>
      )}
    </figure>
  );
}
