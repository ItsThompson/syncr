/* What a kit element would look like, derived from the stylesheet rather than from a screenshot.
 *
 * jsdom applies no stylesheet, so `getComputedStyle` on a rendered element reports nothing and an assertion
 * over it passes whether the rule exists or not. Every claim in this kit about a state's channel would be
 * unpinned. So the rules are parsed with postcss, matched against the real element with `matches`, and the
 * declarations that apply are collected.
 *
 * THE POINT IS THE COMBINATION MATRIX. The design language records that four plausible state systems each
 * looked correct on a single state and produced two pixel-identical rows in a combination matrix while
 * meaning different things. A signature that can be compared across combinations is what makes that
 * checkable here rather than by eye, so `signatureOf` returns the sorted declarations and a test asserts no
 * two combinations produce the same set.
 *
 * HOVER HAS TO BE SIMULATED, because jsdom's `matches(":hover")` is always false: nothing hovers in a
 * headless DOM. A pseudo-class named in `active` is removed from the selector before matching, which is the
 * same thing the browser does when the state is on. Nothing else about the selector is rewritten. */

import { parse, type Rule } from "postcss";

/** A declaration a rule applies, as `property: value`. A pseudo-element prefixes its own. */
export type AppliedDeclaration = string;

export interface VisualStateInput {
  readonly element: Element;
  readonly css: string;
  /** Pseudo-classes to treat as active, such as `:hover`. Anything jsdom can match is left alone. */
  readonly active?: readonly string[] | undefined;
}

const PSEUDO_ELEMENT = /::(before|after)\b/;

function selectorParts(selector: string): string[] {
  return selector.split(",").map((part) => part.trim());
}

/** The selector with the active pseudo-classes removed, or null when jsdom cannot match it at all. */
function matchable(selector: string, active: readonly string[]): string | null {
  let cleaned = selector;
  for (const pseudo of active) cleaned = cleaned.split(pseudo).join("");
  cleaned = cleaned.replace(PSEUDO_ELEMENT, "").trim();
  return cleaned === "" ? null : cleaned;
}

export function appliedDeclarations({
  element,
  css,
  active,
}: VisualStateInput): AppliedDeclaration[] {
  const applied: AppliedDeclaration[] = [];
  const root = parse(css);

  root.walkRules((rule: Rule) => {
    for (const part of selectorParts(rule.selector)) {
      const selector = matchable(part, active ?? []);
      if (selector === null) continue;
      let hit = false;
      try {
        hit = element.matches(selector);
      } catch {
        // A selector jsdom cannot parse is not a claim about this element.
        continue;
      }
      if (!hit) continue;
      const prefix = PSEUDO_ELEMENT.exec(part)?.[0] ?? "";
      rule.walkDecls((declaration) => {
        applied.push(
          `${prefix}${prefix === "" ? "" : " "}${declaration.prop}: ${declaration.value}`,
        );
      });
      break;
    }
  });

  return applied;
}

/** The applied declarations, sorted and de-duplicated, so two combinations can be compared. */
export function signatureOf(input: VisualStateInput): string {
  return [...effectiveDeclarations(input)]
    .map(([property, value]) => `${property}: ${value}`)
    .toSorted()
    .join(" | ");
}

/**
 * What the element actually ends up with: the last declaration of each property wins.
 *
 * A set of applied declarations is not the same thing as a rendering. Two combinations can apply different
 * rules and still land on the same pixels, which is the failure the combination matrix exists to catch, so the
 * per-property resolution matters. Document order stands in for the cascade, which holds here because these
 * stylesheets state a base rule and then its states, in that order, at rising specificity.
 */
export function effectiveDeclarations(input: VisualStateInput): Map<string, string> {
  const effective = new Map<string, string>();
  for (const declaration of appliedDeclarations(input)) {
    const split = declaration.indexOf(":");
    effective.set(declaration.slice(0, split), declaration.slice(split + 1).trim());
  }
  return effective;
}
