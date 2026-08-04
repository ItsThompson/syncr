/* THE THIRTEEN INKS AND THE SIX TEXTURES, AS CLASSES, IN ONE PLACE.
 *
 * Four components paint a category: a pie wedge's pattern, a stacked segment, a legend chip and nothing else.
 * They read this map rather than each assembling a class list, for the reason `notices/surface.ts` exists: a
 * class built from a template literal, `chart-ink--${pigment}`, reaches an element with the interpolated half
 * invisible to the layer 0 rule, the arbitrary-value rule and the circle allowlist alike, and `lint:markup`
 * refuses that shape.
 *
 * THE ELEMENT'S OWN CLASS ARRIVES AT THE CALL SITE, through cva's `class`, so the map answers only "what ink and
 * what texture" and the caller answers "on what". That also keeps the class list at the attribute readable: the
 * element's class is a literal where a reader and the markup scan both meet it.
 *
 * A pigment sets `--ai` and `--hx` and the pigment's own rule sets nothing else, so the same pair drives a
 * background-color, a background-image and an SVG fill without any of them knowing which pigment it got. */

import { cva } from "class-variance-authority";

import { hatchFor } from "./hatch";
import type { ChartPigment } from "./series";
import "./charts.css";

const ink = cva("chart-ink", {
  variants: {
    pigment: {
      "01": "chart-ink--01",
      "02": "chart-ink--02",
      "03": "chart-ink--03",
      "04": "chart-ink--04",
      "05": "chart-ink--05",
      "06": "chart-ink--06",
      "07": "chart-ink--07",
      "08": "chart-ink--08",
      "09": "chart-ink--09",
      "10": "chart-ink--10",
      "11": "chart-ink--11",
      "12": "chart-ink--12",
      unallocated: "chart-ink--unallocated",
    },
    hatch: {
      fwd: "chart-hatch--fwd",
      back: "chart-hatch--back",
      vert: "chart-hatch--vert",
      horz: "chart-hatch--horz",
      cross: "chart-hatch--cross",
      dot: "chart-hatch--dot",
      none: "chart-hatch--none",
    },
  },
});

/**
 * The classes that paint one category: its ink, its texture, and whatever the element itself is.
 *
 * The hatch is DERIVED from the pigment rather than passed, so two surfaces showing the same Area cannot
 * disagree about its texture, and the vacancy cannot be given one.
 *
 * `ownClasses` is the ELEMENT'S own class list, written by the component that draws it. It is not a `className`
 * prop and this module is not exported past the family barrel: no caller can reach a kit element's classes, which
 * is the rule the layer test enforces over every component in the layer.
 */
export function chartPaint(pigment: ChartPigment, ownClasses: string): string {
  return ink({ pigment, hatch: hatchFor(pigment) ?? "none", class: ownClasses });
}
