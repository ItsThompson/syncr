/* An Area's chip, and the Area's NAME, which is not optional.
 *
 * COLOUR IS NEVER THE ONLY ENCODING OF ANYTHING. Roughly one man in twelve cannot separate twelve categorical
 * hues, and three of the ramp's pigments sit on the sealed signal hues by construction, so a bare chip says
 * nothing reliable at all. The name is a required prop rather than a documented convention: a chip without one
 * fails the typecheck, which is the same rule enforced by the compiler rather than by review.
 *
 * The pigment is a variant per ramp step rather than a computed class, so the twelve are written where the
 * markup scan can read them. A component that assembled `bg-area-${n}` would be invisible to the layer 0 rule,
 * the arbitrary-value rule and the circle allowlist alike. Which step an assigned index lands on is
 * `pigment.ts`'s question, because a chart and a legend need the same answer without importing a chip. */

import { cva } from "class-variance-authority";

import type { AreaPigment } from "./pigment";
import "./marks.css";

const chip = cva("area-chip", {
  variants: {
    pigment: {
      "01": "bg-area-01",
      "02": "bg-area-02",
      "03": "bg-area-03",
      "04": "bg-area-04",
      "05": "bg-area-05",
      "06": "bg-area-06",
      "07": "bg-area-07",
      "08": "bg-area-08",
      "09": "bg-area-09",
      "10": "bg-area-10",
      "11": "bg-area-11",
      "12": "bg-area-12",
    },
  },
});

export interface AreaChipProps {
  /** The Area's name. Required: a chip on its own encodes a category in colour alone. */
  readonly name: string;
  /** The ramp step, from `areaPigment(area.pigmentIndex)`. */
  readonly pigment: AreaPigment;
}

export function AreaChip({ name, pigment }: AreaChipProps) {
  return (
    <span className="area-name">
      {/* Decorative: the name beside it is what identifies the Area, and announcing both reads it twice. */}
      <span className={chip({ pigment })} aria-hidden="true" />
      {name}
    </span>
  );
}
