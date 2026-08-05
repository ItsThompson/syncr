/* THE TWELVE AREA INKS AS CLASSES, so the Area's pigment reaches a block without a template literal.
 *
 * A class assembled as `week-block--area-${pigment}` reaches an element with the interpolated half invisible to
 * the layer 0 rule, the arbitrary-value rule and the circle allowlist alike, and `lint:markup` refuses that
 * shape for exactly that reason. `charts/paint.ts` answers the same question the same way for a wedge.
 *
 * THE INK IS A `var()` IN A STYLESHEET RATHER THAN A STRING IN A MODULE, which is what keeps it checked: the
 * token validator resolves every reference in `block.css` against the token layer, so renaming a ramp step is a
 * failing gate rather than a block that draws its top rule in nothing.
 *
 * PAST TWELVE AREAS THE RAMP REPEATS. `areaPigment` wraps, so a thirteenth Area is dealt the first step again and
 * two Areas draw one pigment. That is deliberate and a colourless block would be worse, and it is why a block's
 * accessible name carries the Area's NAME: the name is what identity rests on once the pigment stops separating. */

import { cva } from "class-variance-authority";

import type { AreaPigment } from "../marks";
import "./block.css";

const paint = cva("week-block", {
  variants: {
    pigment: {
      "01": "week-block--area-01",
      "02": "week-block--area-02",
      "03": "week-block--area-03",
      "04": "week-block--area-04",
      "05": "week-block--area-05",
      "06": "week-block--area-06",
      "07": "week-block--area-07",
      "08": "week-block--area-08",
      "09": "week-block--area-09",
      "10": "week-block--area-10",
      "11": "week-block--area-11",
      "12": "week-block--area-12",
      none: "",
    },
  },
});

/** The block's own classes plus the one that sets its Area ink, or none where it holds no Area. */
export function blockPaint(pigment: AreaPigment | null, ownClasses: string): string {
  return paint({ pigment: pigment ?? "none", class: ownClasses });
}
