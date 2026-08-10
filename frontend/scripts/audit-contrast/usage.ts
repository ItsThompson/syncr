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
 * where its percentage is known.
 *
 * A RULE THAT NAMES BOTH STATES A PAIRING. Which surface a class sits on is a fact about the DOM, so the ledger
 * measures every ink against every surface and enforces on the pairs it can prove. One shape it can prove: a rule
 * that declares its own fill AND its own ink names both halves in one place, with no DOM to consult. That is what
 * `compositionsOf` reads, and it is the only reachability a stylesheet supports. */

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

/** A pairing one rule states: it names the fill and it names the ink drawn on that fill. */
export interface Composition {
  /** `<sheet> <selector> { <property> }`, so a finding names the rule rather than the pair. */
  readonly where: string;
  /** The token drawn, before resolution. */
  readonly ink: string;
  /** The token filled with, before resolution. */
  readonly surface: string;
  readonly floor: number;
}

export interface Usage {
  readonly inks: Map<string, InkUse>;
  readonly surfaces: Set<string>;
  readonly sheets: string[];
  /** Values a ratio cannot describe, found while classifying: a mix, and anything else composed. */
  readonly mixes: Unmeasurable[];
  /** Every pairing a single rule states, which is the set the audit can hold to a floor off paper. */
  readonly compositions: Composition[];
}

/** One ink declaration a rule keeps after its own cascade, with the floor its property implies. */
interface Drawn {
  readonly value: string;
  readonly floor: number;
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

/**
 * The pairings one rule states, from the fill and the inks it keeps.
 *
 * Both halves are resolved by document order WITHIN THE ONE RULE, which is what the cascade does there and is
 * sound because nothing is concatenated: a later `background: transparent` in the same rule really does replace an
 * earlier ink fill, and then the rule states no pairing at all.
 */
function compositionsOf(
  where: string,
  fill: string | null,
  drawn: ReadonlyMap<string, Drawn>,
): Composition[] {
  if (fill === null || isMix(fill)) return [];
  const surfaces = tokensIn(fill);
  if (surfaces.length === 0) return [];

  const stated: Composition[] = [];
  for (const [property, one] of drawn) {
    for (const surface of surfaces) {
      for (const ink of tokensIn(one.value)) {
        stated.push({ where: `${where} { ${property} }`, ink, surface, floor: one.floor });
      }
    }
  }
  return stated;
}

/** The inks and the surfaces the shipped stylesheets actually use. */
export async function paletteInUse(sheets: readonly string[]): Promise<Usage> {
  const inks = new Map<string, InkUse>();
  const surfaces = new Set<string>([PAGE]);
  const mixes: Unmeasurable[] = [];
  const compositions: Composition[] = [];

  for (const file of sheets) {
    const sheet = path.relative(appSourceDir, file);
    parse(await readFile(file, "utf8")).walkRules((rule) => {
      const properties = new Set<string>();
      rule.walkDecls((declaration) => {
        properties.add(declaration.prop.toLowerCase());
      });

      let fill: string | null = null;
      const drawn = new Map<string, Drawn>();

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
          drawn.set(property, { value: declaration.value, floor });
          for (const token of tokensIn(declaration.value)) {
            const held = inks.get(token);
            if (held === undefined || floor > held.floor) {
              inks.set(token, { floor, where: `${sheet} ${rule.selector} { ${property} }` });
            }
          }
        }
        if (SURFACE_PROPERTIES.has(property) && !isMix(declaration.value)) {
          fill = declaration.value;
          for (const token of tokensIn(declaration.value)) surfaces.add(token);
        }
      });

      compositions.push(...compositionsOf(`${sheet} ${rule.selector}`, fill, drawn));
    });
  }

  return {
    inks,
    surfaces,
    sheets: sheets.map((file) => path.relative(appSourceDir, file)),
    mixes,
    compositions,
  };
}
