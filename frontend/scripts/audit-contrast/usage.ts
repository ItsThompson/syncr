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
 * that declares its own fill AND its own ink names both halves in one place, with no DOM to consult.
 *
 * THE UNIT IS A SELECTOR IN A FILE, NOT A BLOCK. Two blocks with the same selector in one sheet compose by the
 * cascade, so `.x { background: ink }` and a later `.x { color: pale }` state a pairing neither block states
 * alone, and reading blocks one at a time misses it silently. Declarations are merged per selector before the
 * pairing is derived.
 *
 * THE BOUND IS BYTE-IDENTICAL SELECTOR TEXT, after whitespace is collapsed, within the same at-rule chain. It is
 * not a semantic bound: nothing here parses a selector, so two spellings of one element are two keys. Measured,
 * these all compose on one element and all state nothing: a selector list with one member later specialised,
 * `.host>.probe` against `.host > .probe`, `:is(.probe)` or `:where(.probe)` against `.probe`, `.probe.probe`
 * against `.probe`, `DIV.probe` against `div.probe`, and one attribute value in single quotes against the same
 * value in double quotes. Every one is a MISSED pairing rather than a false one, which is the safe direction.
 * That list is what was measured; it is not a bound on what else could be missed.
 *
 * The at-rule chain is part of the key because a declaration inside `@media print` and one outside it may never
 * apply together, and a pairing that never composes is not a pairing. `@layer` and `@supports (color: red)` always
 * apply, so refusing to merge across those two is an under-read rather than conservatism.
 *
 * ONLY A RULE'S OWN DECLARATIONS ARE READ. `walkDecls` is recursive, so reading it whole attributed a nested
 * block's ink to its parent's fill and manufactured a pairing across two elements: `.host { background: ink; &
 * .child { color: pale } }` reported `.host` as stating a pairing it does not state. A nested block is visited
 * under its own selector instead, where it states nothing unless it names both halves itself. The property set
 * that reclassifies a hatch carrier is read from one block's own declarations for the same reason.
 *
 * Two consequences, both under-reads. A declaration written directly inside an at-rule nested inside a rule is not
 * read at all, because no rule owns it. And `&:hover` inside a filled rule is the same element in another state,
 * so its ink really does land on that fill, and this reader does not claim it: resolving `&` against a parent
 * selector is selector semantics, which nothing here does.
 *
 * What is out of reach for the same reason is a pairing split across DIFFERENT selectors, `.a` filling and `.b`
 * drawing, which composes only where the markup nests them. That is the DOM's answer and not a sheet's. */

import { parse, type Declaration, type Rule } from "postcss";
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

/** One ink declaration a selector keeps after the cascade, with the floor its property implies. */
interface Drawn {
  readonly value: string;
  readonly floor: number;
}

/** What one selector in one file declares, accumulated across every block that writes it. */
interface Declared {
  readonly where: string;
  /** The last fill any block for this selector declares, which is the one the cascade keeps. */
  fill: string | null;
  /** The last ink per property, for the same reason. */
  readonly drawn: Map<string, Drawn>;
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
 * The pairings one selector states, from the fill and the inks it keeps.
 *
 * Resolved by document order across the blocks sharing the selector IN ONE FILE, which is what the cascade does at
 * equal specificity. Nothing is concatenated across files or layers, so the unsoundness that comes from ordering
 * two sheets against each other cannot arise: a later `background: transparent` really does replace an earlier ink
 * fill, and then the selector states no pairing at all.
 */
function compositionsOf(declared: Declared): Composition[] {
  const { where, fill, drawn } = declared;
  if (fill === null || isMix(fill)) return [];

  const stated: Composition[] = [];
  for (const [property, one] of drawn) {
    for (const surface of tokensIn(fill)) {
      for (const ink of tokensIn(one.value)) {
        stated.push({ where: `${where} { ${property} }`, ink, surface, floor: one.floor });
      }
    }
  }
  return stated;
}

/**
 * The at-rules a block sits inside, as a key, so two blocks merge only where both can apply.
 *
 * postcss types `parent` as a union that includes `Document`, whose own `nodes` are roots rather than children, so
 * following the chain with the library's types requires a cast at every hop. One local shape describing what this
 * walk actually reads keeps the cast to the single boundary below.
 */
interface Enclosing {
  readonly type: string;
  readonly name?: string | undefined;
  readonly params?: string | undefined;
  readonly parent?: Enclosing | undefined;
}

function contextOf(rule: Rule): string {
  const enclosing: string[] = [];
  let node = rule.parent as Enclosing | undefined;
  while (node !== undefined) {
    if (node.type === "atrule") {
      enclosing.unshift(`@${node.name ?? ""} ${node.params ?? ""}`.trim());
    }
    node = node.parent;
  }
  return enclosing.join(" ");
}

/** The inks and the surfaces the shipped stylesheets actually use. */
export async function paletteInUse(sheets: readonly string[]): Promise<Usage> {
  const inks = new Map<string, InkUse>();
  const surfaces = new Set<string>([PAGE]);
  const mixes: Unmeasurable[] = [];
  const compositions: Composition[] = [];

  for (const file of sheets) {
    const sheet = path.relative(appSourceDir, file);
    const perSelector = new Map<string, Declared>();

    parse(await readFile(file, "utf8")).walkRules((rule) => {
      const own = rule.nodes.filter((node): node is Declaration => node.type === "decl");
      const properties = new Set(own.map((declaration) => declaration.prop.toLowerCase()));

      const key = `${contextOf(rule)}|${rule.selector.replace(/\s+/g, " ").trim()}`;
      const declared = perSelector.get(key) ?? {
        where: `${sheet} ${rule.selector}`,
        fill: null,
        drawn: new Map<string, Drawn>(),
      };
      perSelector.set(key, declared);

      for (const declaration of own) {
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
            continue;
          }
          declared.drawn.set(property, { value: declaration.value, floor });
          for (const token of tokensIn(declaration.value)) {
            const held = inks.get(token);
            if (held === undefined || floor > held.floor) {
              inks.set(token, { floor, where: `${sheet} ${rule.selector} { ${property} }` });
            }
          }
        }
        if (SURFACE_PROPERTIES.has(property) && !isMix(declaration.value)) {
          declared.fill = declaration.value;
          for (const token of tokensIn(declaration.value)) surfaces.add(token);
        }
      }
    });

    for (const declared of perSelector.values()) compositions.push(...compositionsOf(declared));
  }

  return {
    inks,
    surfaces,
    sheets: sheets.map((file) => path.relative(appSourceDir, file)),
    mixes,
    compositions,
  };
}
