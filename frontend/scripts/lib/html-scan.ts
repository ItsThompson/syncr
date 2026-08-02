/* Scanning a rendered reference sheet for the token names it declares and consumes.
 *
 * The six sheets in `docs/design/` LINK the token layer rather than copying values, so a
 * value cannot drift between the reference and the build. That only holds while every
 * reference resolves: a renamed token leaves a sheet rendering with a missing value and
 * looking entirely plausible, which is the failure this scan exists to catch.
 *
 * Scanning is over the raw text rather than a parsed DOM, because a sheet declares custom
 * properties in three places at once: a `<style>` rule, an inline `style` attribute, and a
 * string a script assembles. All three are the same contract and all three must be seen. */

import { createPositionResolver, type Position } from "./css-scan.ts";

export interface SheetReference extends Position {
  readonly name: string;
}

export interface SheetLink extends Position {
  readonly href: string;
}

export interface HtmlScan {
  /** Custom properties the sheet declares itself, so a local `--ai` resolves. */
  readonly declaredNames: ReadonlySet<string>;
  readonly varReferences: readonly SheetReference[];
  readonly dynamicVarReferences: readonly Position[];
  readonly stylesheetLinks: readonly SheetLink[];
}

const CUSTOM_PROPERTY = "--[A-Za-z0-9_-]+";
const DECLARATION_PATTERN = new RegExp(`(${CUSTOM_PROPERTY})\\s*:`, "g");
const VAR_PATTERN = new RegExp(`\\bvar\\(\\s*(${CUSTOM_PROPERTY})?`, "g");
const LINK_PATTERN = /<link\b[^>]*\brel=["']stylesheet["'][^>]*>/gi;
const HREF_PATTERN = /\bhref=["']([^"']+)["']/i;

export function scanHtml(text: string): HtmlScan {
  const at = createPositionResolver(text);

  const declaredNames = new Set<string>();
  for (const match of text.matchAll(DECLARATION_PATTERN)) declaredNames.add(match[1]);

  const varReferences: SheetReference[] = [];
  const dynamicVarReferences: Position[] = [];
  for (const match of text.matchAll(VAR_PATTERN)) {
    if (match[1] === undefined) dynamicVarReferences.push(at(match.index));
    else varReferences.push({ ...at(match.index), name: match[1] });
  }

  const stylesheetLinks: SheetLink[] = [];
  for (const match of text.matchAll(LINK_PATTERN)) {
    const href = HREF_PATTERN.exec(match[0]);
    if (href !== null) stylesheetLinks.push({ ...at(match.index), href: href[1] });
  }

  return { declaredNames, varReferences, dynamicVarReferences, stylesheetLinks };
}
