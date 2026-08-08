/* WHICH TOKENS THE SHIPPED STYLESHEETS DRAW WITH, AND WHICH THEY FILL WITH.
 *
 * The token layer is not read for USAGE: it declares every pigment, including the layer 0 ramp steps no component
 * may reference, and a ledger over the declarations would measure pairs the product cannot draw. It is read for
 * RESOLUTION, which is a different question and lives in `resolution.ts`.
 *
 * THE FLOOR COMES FROM THE PROPERTY THAT WRITES THE VALUE, which is the only classification a stylesheet can
 * support: `color` is text at 4.5:1 and a border is an indicator at 3:1. Two refinements the first version needed,
 * each measured against a real rule in this kit:
 *
 * A HATCH IS A CARRIER, NOT A LABEL. `color` on a rule that also paints a hatch is what the hatch's own
 * `currentColor` reads: `.week-band` sets `color: var(--forbidden-hatch-ink)` and `background-image:
 * var(--hatch-back)` in one rule, and holding that ink to the text floor would report a defect on a band nobody
 * reads words off.
 *
 * A MIX IS NOT ATTRIBUTED TO ITS PARTS. `.chart-ink` colours with `color-mix(in srgb, var(--ai) var(--hatch-mix),
 * var(--paper-raised))`, and reading the tokens out of that value would put the text floor on twelve Area pigments
 * and on a percentage. The mix is recorded as unmeasurable, with the reason, and the hatch's own ratio is computed
 * where its percentage is known. */

import { parse } from "postcss";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { appSourceDir } from "../lib/paths.ts";
import { INDICATOR_FLOOR, TEXT_FLOOR } from "../lib/contrast.ts";
import { tokensIn, type Unmeasurable } from "./resolution.ts";

/** Properties that put ink on a surface, and the floor each has to clear. */
const INK_PROPERTIES: Readonly<Record<string, number>> = {
  color: TEXT_FLOOR,
  "border-color": INDICATOR_FLOOR,
  "border-top-color": INDICATOR_FLOOR,
  "border-right-color": INDICATOR_FLOOR,
  "border-bottom-color": INDICATOR_FLOOR,
  "border-left-color": INDICATOR_FLOOR,
  "outline-color": INDICATOR_FLOOR,
  stroke: INDICATOR_FLOOR,
};

/** Properties that fill a surface, whose value is therefore something ink can land on. */
const SURFACE_PROPERTIES = new Set(["background", "background-color"]);

/** The page's own fill, which every surface ultimately sits on. */
const PAGE = "--paper";

export interface InkUse {
  /** The strictest floor any shipped declaration puts this ink to. */
  readonly floor: number;
  /** The declaration that set it, so a reader can check the classification rather than trust it. */
  readonly where: string;
}

export interface Usage {
  readonly inks: Map<string, InkUse>;
  readonly surfaces: Set<string>;
  readonly sheets: string[];
  /** Values a ratio cannot describe, found while classifying: a mix, and anything else composed. */
  readonly mixes: Unmeasurable[];
}

/** The floor a property implies, or undefined when the property writes no ink. */
function floorFor(property: string, rule: ReadonlySet<string>): number | undefined {
  const floor = INK_PROPERTIES[property];
  if (floor === undefined) return undefined;
  if (property === "color" && rule.has("background-image")) return INDICATOR_FLOOR;
  return floor;
}

/** True for a value whose colour is a mix, which is measured where the mix percentage is known. */
function isMix(value: string): boolean {
  return value.toLowerCase().includes("color-mix(");
}

/** The inks and the surfaces the shipped stylesheets actually use. */
export async function paletteInUse(sheets: readonly string[]): Promise<Usage> {
  const inks = new Map<string, InkUse>();
  const surfaces = new Set<string>([PAGE]);
  const mixes: Unmeasurable[] = [];

  for (const file of sheets) {
    const sheet = path.relative(appSourceDir, file);
    parse(await readFile(file, "utf8")).walkRules((rule) => {
      const properties = new Set<string>();
      rule.walkDecls((declaration) => {
        properties.add(declaration.prop.toLowerCase());
      });
      rule.walkDecls((declaration) => {
        const property = declaration.prop.toLowerCase();
        const floor = floorFor(property, properties);
        if (floor !== undefined) {
          if (isMix(declaration.value)) {
            mixes.push({
              token: `${sheet} ${rule.selector}`,
              value: declaration.value.replace(/\s+/g, " "),
              reason:
                "it is a mix, measured where its percentage is known, in the charts' own contrast ledger",
            });
            return;
          }
          for (const token of tokensIn(declaration.value)) {
            const held = inks.get(token);
            if (held === undefined || floor > held.floor) {
              inks.set(token, { floor, where: `${sheet} ${rule.selector} { ${property} }` });
            }
          }
        }
        if (SURFACE_PROPERTIES.has(property) && !isMix(declaration.value)) {
          for (const token of tokensIn(declaration.value)) surfaces.add(token);
        }
      });
    });
  }

  return { inks, surfaces, sheets: sheets.map((file) => path.relative(appSourceDir, file)), mixes };
}
