/* THE INK A HOST HANDS A MARK IT CONTAINS, AND THE SURFACE IT PUTS UNDER IT.
 *
 * A mark inside a control is drawn in the control's ink rather than the page's, so the pairing is a fact about
 * two stylesheets at once: the mark's sheet reads a custom property and the host's sheet sets it. jsdom applies
 * neither, so `getComputedStyle` reports nothing and an assertion over it would pass whether the host set the
 * property or not. These readers parse the sheets instead, the way `visualState` does for one element, and hand
 * a test the two token names a ratio needs.
 *
 * A TRANSLUCENT FILL IS NOT A SURFACE, AND THIS READER CANNOT SEE WHICH ONE IS UNDER IT. What a host filled
 * `transparent` shows through is a fact about the DOM, which no stylesheet states. It resolves here to the two
 * papers, which are where those ranks sit almost everywhere and are the only surfaces a stylesheet can name.
 * That is the reader's limit rather than a claim about the product: a translucent host inside an ink-filled
 * container is a composition this reader calls a pass and cannot measure, so
 * `ui/domain/marks/__tests__/contrast.test.tsx` measures that pairing directly instead of asking here. Every
 * other value a fill can hold is REFUSED rather than guessed, because a ratio computed against a gradient or an
 * image is a made-up figure. */

import { parse } from "postcss";

/** The two papers, which are where a translucent rank sits almost everywhere. */
const PAPERS = ["--paper", "--paper-raised"] as const;

/** The properties that fill a surface. Both are the same channel, so the last one a rule declares wins. */
const FILL_PROPERTIES = new Set(["background", "background-color"]);

export interface InkRule {
  /** The rule's selector as written, which may name several elements. */
  readonly selector: string;
  /** The ink the rule writes for its own text. */
  readonly ink: string;
  /** The ink it hands a mark inside it, or null where it hands none. */
  readonly markInk: string | null;
  /** The fill it puts under both, or null where it declares none. */
  readonly fill: string | null;
}

/** Every rule in a host's stylesheet that writes ink, with what it hands a mark and what it fills with. */
export function inkRules(css: string, markInkProperty: string): InkRule[] {
  const rules: InkRule[] = [];
  parse(css).walkRules((rule) => {
    const declared = new Map<string, string>();
    const fills: string[] = [];
    rule.walkDecls((declaration) => {
      const value = declaration.value.trim();
      declared.set(declaration.prop, value);
      if (FILL_PROPERTIES.has(declaration.prop)) fills.push(value);
    });
    const ink = declared.get("color");
    if (ink === undefined) return;
    rules.push({
      selector: rule.selector,
      ink,
      markInk: declared.get(markInkProperty) ?? null,
      fill: fills.at(-1) ?? null,
    });
  });
  return rules;
}

/** The one token a value names, for a value that is a single `var()` and nothing else. */
export function tokenIn(value: string | undefined): string {
  const reference = /^var\((--[\w-]+)\)$/.exec((value ?? "").trim());
  if (reference === null) {
    throw new Error(
      `${value ?? "nothing"} names no single token, so no ratio can be computed from it`,
    );
  }
  return reference[1];
}

/** The surfaces a fill puts under a mark: its own token, or the papers a translucent one is rendered on. */
export function surfacesUnder(fill: string | null): readonly string[] {
  if (fill === null) {
    throw new Error("the rule declares no fill, so it does not say what a mark inside it sits on");
  }
  const value = fill.trim();
  if (value === "transparent") return PAPERS;
  return [tokenIn(value)];
}
