/* An illustration plate: a dithered engraving of an instrument, in the product's own ink.
 *
 * IT IS DECORATION AND IT SAYS SO. `alt=""` is the correct alt text for an ornament: a plate carries no information
 * a reader needs, the words beside it do, and describing an armillary sphere to somebody who came to read their
 * week is noise. That is also why a plate is never the only thing on a surface.
 *
 * NEVER BEHIND DATA. The plate is an `img` in the flow rather than a background, which is what makes the rule
 * structural: there is no way to place one under the week grid, the Today ledger or a chart. */

import { cva } from "class-variance-authority";

import { PLATES, type PlateName } from "./plates";
import "./plate.css";

const plate = cva("plate", {
  variants: {
    fit: {
      band: "plate--band",
      figure: "plate--figure",
    },
  },
  defaultVariants: { fit: "figure" },
});

export interface PlateProps {
  readonly name: PlateName;
  /** `band` crops to a header band's height; `figure` sets at its own width beside words. */
  readonly fit?: "band" | "figure" | undefined;
}

export function Plate({ name, fit }: PlateProps) {
  return <img className={plate({ fit })} src={PLATES[name]} alt="" />;
}
