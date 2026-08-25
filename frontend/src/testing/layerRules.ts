/* THE READERS EVERY LAYER'S OWN RULES REST ON.
 *
 * Four claims in this kit are about a layer as a whole rather than about any one component: every state
 * except hover survives forced-colors mode, one file declares the hard offset, no component declares its own
 * focus ring, and no stylesheet ships a rule nothing names. Each layer asserts them over its own directory,
 * and the ANSWERS differ per layer: the primitives own the overlay family, the layout layer owns no state at
 * all. What must not differ is how the question is asked, so the readers live here once.
 *
 * jsdom applies no stylesheet, so a rendered element says nothing about what a rule declares, and
 * forced-colors mode cannot be entered in a headless DOM at all. What CAN be checked is the property a state
 * spends, which is exactly what the design language's own reasoning turns on. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { parse } from "postcss";

import { blankJsComments } from "../../scripts/lib/comments.ts";
import { kitStylesheet } from "./kitStylesheets";

export interface LayerStylesheet {
  readonly name: string;
  readonly css: string;
}

export interface LayerSource {
  readonly name: string;
  /** The file's text with comments blanked, so prose cannot answer a question about code. */
  readonly text: string;
}

export interface StateRule {
  readonly sheet: string;
  readonly state: string;
  readonly selector: string;
  readonly declarations: readonly (readonly [string, string])[];
}

/* Properties forced-colors mode overrides or drops, plus the ones that are invisible in a rendering. A state
 * carried ONLY by these does not survive it, which is the whole of the design language's argument for pairing
 * a fill with a rule or a glyph. A border COLOUR is not here: it is forced to the system's text colour, and a
 * border drawn transparent at rest therefore becomes visible, which is how the current row survives. */
export const NOT_A_SURVIVING_MARK: ReadonlySet<string> = new Set([
  "background",
  "background-color",
  "background-image",
  "color",
  "box-shadow",
  "cursor",
]);

/** Selectors that name a state: a data attribute, an ARIA state, or a state pseudo-class. */
const STATE_SELECTOR =
  /\[(data-\w[\w-]*|aria-(?:invalid|selected|current|disabled|expanded))[^\]]*\]|:hover|:disabled/g;

export const HOVER = ":hover";

/** Every stylesheet in a layer, in file order, so a finding can name the file a reader will open. */
export async function layerStylesheets(dir: string): Promise<LayerStylesheet[]> {
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  const names = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".css"))
    .map((entry) => path.relative(dir, path.join(entry.parentPath, entry.name)))
    .toSorted();
  return Promise.all(names.map(async (name) => ({ name, css: await kitStylesheet(name, dir) })));
}

/** Every rule in a layer that styles a state, keyed by the state its selector names. */
export async function stateRules(dir: string): Promise<StateRule[]> {
  const rules: StateRule[] = [];
  for (const { name, css } of await layerStylesheets(dir)) {
    parse(css).walkRules((rule) => {
      const states = [...rule.selector.matchAll(STATE_SELECTOR)].map((match) => match[0]);
      if (states.length === 0) return;
      const declarations: (readonly [string, string])[] = [];
      rule.walkDecls((declaration) => {
        declarations.push([declaration.prop, declaration.value]);
      });
      if (declarations.length === 0) return;
      for (const state of states) {
        rules.push({ sheet: name, state, selector: rule.selector, declarations });
      }
    });
  }
  return rules;
}

/**
 * Each state in each stylesheet, with every property that state spends there.
 *
 * Grouped by file rather than by rule, because a state is legitimately carried by two rules: a disabled
 * control dashes its own border and mutes the label beside it, and the state survives on the strength of the
 * dash. Judging a rule at a time would call the second rule a casualty while the state is perfectly visible.
 */
export async function propertiesByState(dir: string): Promise<Map<string, Set<string>>> {
  const spent = new Map<string, Set<string>>();
  for (const rule of await stateRules(dir)) {
    const key = `${rule.sheet} ${rule.state}`;
    const properties = spent.get(key) ?? new Set<string>();
    for (const [property] of rule.declarations) properties.add(property);
    spent.set(key, properties);
  }
  return spent;
}

/** Every state in a layer that spends nothing forced-colors mode keeps, hover excepted. */
export async function forcedColorsCasualties(dir: string): Promise<string[]> {
  const casualties: string[] = [];
  for (const [state, properties] of await propertiesByState(dir)) {
    if (state.includes(HOVER)) continue;
    const survives = [...properties].some((property) => !NOT_A_SURVIVING_MARK.has(property));
    if (!survives) casualties.push(state);
  }
  return casualties;
}

/** Every class a layer's stylesheets declare, mapped to the sheet that declares it first. */
export async function declaredClasses(dir: string): Promise<Map<string, string>> {
  const declared = new Map<string, string>();
  for (const { name, css } of await layerStylesheets(dir)) {
    parse(css).walkRules((rule) => {
      for (const match of rule.selector.matchAll(/\.([a-zA-Z][\w-]*)/g)) {
        if (!declared.has(match[1])) declared.set(match[1], name);
      }
    });
  }
  return declared;
}

/** Every source file in a layer, with comments blanked so prose cannot answer a question about code. */
export async function layerSources(dir: string): Promise<LayerSource[]> {
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  const files = entries
    .filter(
      (entry) => entry.isFile() && /\.tsx?$/.test(entry.name) && !entry.name.includes(".test."),
    )
    .map((entry) => path.join(entry.parentPath, entry.name))
    .toSorted();
  return Promise.all(
    files.map(async (file) => ({
      name: path.relative(dir, file),
      text: blankJsComments(await readFile(file, "utf8")),
    })),
  );
}

/** Matches every property whose effect is to clip or refuse to wrap text: the clamp shorthand and its
 * vendor spelling, the ellipsis longhand of the `overflow` shorthand's inline end, and nowrap itself.
 * Matched against the WHOLE property name, so a longer name that merely contains one of these is not swept. */
export const TRUNCATION_PROPERTY =
  /^(?:-webkit-)?(?:line-clamp|block-ellipsis|text-overflow|white-space)$/;

export interface TruncationDeclaration {
  readonly sheet: string;
  readonly selector: string;
  readonly property: string;
  readonly value: string;
}

/** Every truncation-shaped declaration a layer makes, with the rule each sits in.
 *
 * Read over declarations rather than over source text, so a property named in a comment is not a finding,
 * and by PROPERTY NAME rather than by value, because `-webkit-line-clamp: n` carries its ellipsis inside the
 * shorthand where neither `text-overflow` nor `white-space` would see it. */
export async function truncationDeclarations(dir: string): Promise<TruncationDeclaration[]> {
  const found: TruncationDeclaration[] = [];
  for (const { name, css } of await layerStylesheets(dir)) {
    parse(css).walkRules((rule) => {
      rule.walkDecls((declaration) => {
        if (TRUNCATION_PROPERTY.test(declaration.prop)) {
          found.push({
            sheet: name,
            selector: rule.selector,
            property: declaration.prop,
            value: declaration.value,
          });
        }
      });
    });
  }
  return found;
}

/** Every value of a property a layer declares, with the sheet each came from. */
export async function declarationsOf(
  dir: string,
  property: string,
): Promise<{ sheet: string; value: string }[]> {
  const found: { sheet: string; value: string }[] = [];
  for (const { name, css } of await layerStylesheets(dir)) {
    parse(css).walkDecls((declaration) => {
      if (declaration.prop === property) found.push({ sheet: name, value: declaration.value });
    });
  }
  return found;
}
