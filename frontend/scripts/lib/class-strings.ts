/* Pulling the class lists out of a TSX file.
 *
 * A class list reaches the DOM through one of two shapes: a `className` attribute, or a string
 * handed to a class-composing helper. Both are extracted, so a rule cannot be dodged by moving a
 * utility into a variant map.
 *
 * Extraction is deliberately narrow rather than whole-file: a utility name like `transition` is
 * also an English word, and a rule that scanned prose would fail on a comment that explains why
 * the rule exists. */

import { createPositionResolver, type Position } from "./css-scan.ts";

export interface ClassString extends Position {
  readonly text: string;
}

/* The helpers a variant map is written with. `cva` is the one section 14 names; the others are the
 * conventional companions, listed so a kit component cannot route around the rules by picking a
 * different composer. */
export const CLASS_COMPOSERS = ["cva", "cx", "cn", "clsx", "twMerge", "tv"];

const CLASS_NAME_ATTRIBUTE = /className\s*=\s*/g;
const COMPOSER_CALL = new RegExp(`\\b(?:${CLASS_COMPOSERS.join("|")})\\s*\\(`, "g");
const QUOTE_CHARACTERS = new Set(['"', "'", "`"]);

/** Returns the offset just past the region opened by `open` at `from`, matching nesting. */
function findRegionEnd(text: string, from: number, open: string, close: string): number {
  let depth = 0;
  for (let index = from; index < text.length; index += 1) {
    if (text[index] === open) depth += 1;
    else if (text[index] === close) {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return text.length;
}

function stringLiteralsIn(text: string, from: number, to: number, at: (o: number) => Position) {
  const found: ClassString[] = [];
  let index = from;
  while (index < to) {
    const character = text[index];
    if (!QUOTE_CHARACTERS.has(character)) {
      index += 1;
      continue;
    }
    let end = index + 1;
    while (end < to && text[end] !== character) {
      if (text[end] === "\\") end += 1;
      end += 1;
    }
    found.push({ ...at(index + 1), text: text.slice(index + 1, end) });
    index = end + 1;
  }
  return found;
}

export function classStringsIn(source: string): ClassString[] {
  const at = createPositionResolver(source);
  const found: ClassString[] = [];

  for (const match of source.matchAll(CLASS_NAME_ATTRIBUTE)) {
    const start = match.index + match[0].length;
    const opener = source[start];
    if (opener === "{") {
      found.push(...stringLiteralsIn(source, start, findRegionEnd(source, start, "{", "}"), at));
      continue;
    }
    if (QUOTE_CHARACTERS.has(opener)) {
      found.push(...stringLiteralsIn(source, start, source.length, at).slice(0, 1));
    }
  }

  for (const match of source.matchAll(COMPOSER_CALL)) {
    const open = match.index + match[0].length - 1;
    found.push(...stringLiteralsIn(source, open, findRegionEnd(source, open, "(", ")"), at));
  }

  return found;
}

/**
 * Every `className={...}` expression, with the braces stripped.
 *
 * `classStringsIn` returns the lists it CAN read, which is silence when there are none: a class list moved
 * into a module constant leaves nothing behind for a rule to judge. This returns the attribute itself, so a
 * rule can refuse the shapes the extractor cannot see rather than passing them.
 */
export function classNameExpressions(source: string): ClassString[] {
  const at = createPositionResolver(source);
  const found: ClassString[] = [];

  for (const match of source.matchAll(CLASS_NAME_ATTRIBUTE)) {
    const start = match.index + match[0].length;
    if (source[start] !== "{") continue;
    const end = findRegionEnd(source, start, "{", "}");
    found.push({ ...at(start), text: source.slice(start + 1, end) });
  }

  return found;
}

/**
 * The names a class composer's return value is bound to, such as `const button = cva(...)`.
 *
 * A variant map is called at the attribute, `className={button({ rank })}`, and the class lists live in the
 * `cva` call this module already reads. Knowing which callees are those products is what separates that shape
 * from a hoisted string constant, which reaches an element with nothing readable at either end.
 */
export function composerProductNames(source: string): Set<string> {
  const bindings = new RegExp(
    `\\b(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*(?:${CLASS_COMPOSERS.join("|")})\\s*\\(`,
    "g",
  );
  return new Set([...source.matchAll(bindings)].map((match) => match[1]));
}

/** The individual utility names in a class list, with the variant prefixes stripped. */
export function utilitiesIn(classList: string): string[] {
  return classList
    .split(/\s+/)
    .filter((token) => token !== "")
    .map(stripVariants);
}

/* Variants are stripped at TOP-LEVEL colons only.
 *
 * Splitting on every colon destroyed Tailwind v4's arbitrary-PROPERTY form before any rule saw it:
 * `[color:red]` became `red]`, so the motion rule, the radius rule and the circle allowlist were all
 * structurally blind to it, and `md:[color:red]` was mangled the same way. Seven shapes compiled to
 * real CSS through that gap, including a raw hex and a blurred shadow.
 *
 * This is the same class as the CSS string tokenizer and the oxlint report parser before it: a
 * parser inside a check, wrong about a shape the language permits. */
function stripVariants(token: string): string {
  let depth = 0;
  let start = 0;
  for (let index = 0; index < token.length; index += 1) {
    const character = token[index];
    if (character === "[" || character === "(") depth += 1;
    else if (character === "]" || character === ")") depth -= 1;
    else if (character === ":" && depth === 0) start = index + 1;
  }
  return token.slice(start);
}
