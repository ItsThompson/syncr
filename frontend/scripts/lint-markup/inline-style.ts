/* THE INLINE `style` PROP. A door the theme cannot close and stylelint never sees, because stylelint reads
 * stylesheets and this is a TSX object literal.
 *
 * Only the absolutes are refused, not the prop itself: the week grid computes a block's height and top offset
 * per block, and `style` is the only way to set a derived pixel value. So a raw colour literal, a blurred
 * shadow and a motion property are findings, and a computed length is not. Setting a custom property is how
 * the sheets already pass an Area's ink to a component, so `--x` is fine.
 *
 * THE PROPERTY SIDE IS READ FROM THE OBJECT'S KEYS, CONVERTED, AND ASKED OF THE SHARED LIST. It was written
 * as CSS-spelled patterns before, `/\btransform\s*:/` and friends, while React writes `willChange` and
 * `backdropFilter`: `\b` does not match inside a camelCase word, so
 * `style={{ backdropFilter: "blur(4px)", willChange: "transform" }}` rendered a blur on a kit element with
 * all seven checks green, and `style={{ outline: "none" }}` removed the focus ring of a keyboard-first
 * product. Of the sixteen properties stylelint refuses, the pattern list covered three roots. One list with
 * a key conversion in front of it covers all of them, and the next property added to the design language
 * reaches this rule with no edit here.
 *
 * The object is read as keys and values rather than matched as text, which is why this is a scanner in its
 * own file: it is the largest single concern in the markup rules and has nothing to do with class names. */

import { cssPropertyFor, refusalFor } from "../lib/declarations.ts";
import type { Finding } from "../lib/findings.ts";
import { isCircleAllowed } from "./circles.ts";

const STYLE_PROP = /\bstyle\s*=\s*\{\{/g;

/* Where the VALUE is the offence rather than the property, so no key conversion helps. Matched over the
 * object's whole text, since a colour is a colour wherever it is assigned. */
const RAW_VALUE_PATTERNS: readonly { readonly pattern: RegExp; readonly what: string }[] = [
  { pattern: /#[0-9a-f]{3,8}\b/i, what: "a raw colour literal" },
  { pattern: /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\s*\(/i, what: "a raw colour function" },
  {
    pattern: /\b(?:red|blue|green|black|white|gray|grey|yellow|orange|purple|pink)\b/i,
    what: "a named colour",
  },
];

/* Radius is zero, and 50% survives for the four legal circles. Mirrors the `rounded-*` rules exactly,
 * including the filename allowlist, because an inline style bypassed both:
 * `style={{ borderRadius: "8px" }}` defeated the radius rule and the circle allowlist together. */
const RADIUS_PROPERTIES = /^border(-[a-z]+)*-radius$/;
const SQUARE_RADIUS_VALUES = new Set(["0", "0px", "var(--radius)"]);
const CIRCLE_RADIUS_VALUE = "50%";

export interface InlineStyleInput {
  readonly file: string;
  /** The source with comments blanked and offsets preserved, so a finding still points at the real line. */
  readonly code: string;
  /** Where an offset in `code` sits, which the caller already holds for the file as a whole. */
  readonly at: (offset: number) => { readonly line: number; readonly column: number };
}

export function inlineStyleFindings({ file, code, at }: InlineStyleInput): Finding[] {
  const findings: Finding[] = [];

  for (const match of code.matchAll(STYLE_PROP)) {
    const objectEnd = findObjectEnd(code, match.index + match[0].length - 1);
    const body = code.slice(match.index, objectEnd);

    for (const violation of RAW_VALUE_PATTERNS) {
      if (!violation.pattern.test(body)) continue;
      findings.push({
        file,
        ...at(match.index),
        check: "no-raw-value-in-style",
        message:
          `an inline style sets ${violation.what}. A component reads tokens rather than restating ` +
          "their values, and stylelint cannot see a TSX object literal. A computed length is fine.",
      });
    }

    for (const declaration of styleDeclarationsIn(body)) {
      const property = cssPropertyFor(declaration.key);
      const value = literalValueOf(declaration.value);
      const refusal = refusalFor(property, value);
      if (refusal !== null) {
        findings.push({
          file,
          ...at(match.index + declaration.index),
          check: "no-banned-property-in-style",
          message:
            `an inline style sets ${declaration.key}, which is the declaration ${property}: ` +
            `${value}, and ${refusal}. stylelint cannot see a TSX object literal, and React's ` +
            "camelCase is the same declaration as the CSS spelling.",
        });
        continue;
      }
      if (!RADIUS_PROPERTIES.test(property)) continue;
      if (SQUARE_RADIUS_VALUES.has(value)) continue;
      if (value === CIRCLE_RADIUS_VALUE && isCircleAllowed(file)) continue;
      findings.push({
        file,
        ...at(match.index + declaration.index),
        check: "no-radius-in-style",
        message:
          `an inline style sets ${declaration.key}: ${declaration.value}. Radius is zero, and 50% ` +
          "survives for the status dot, the radio dot, the Area chip and the avatar only.",
      });
    }
  }

  return findings;
}

/** The offset just past the `}}` closing an inline style object opening at `openBrace`. */
function findObjectEnd(code: string, openBrace: number): number {
  let depth = 0;
  for (let index = openBrace; index < code.length; index += 1) {
    if (code[index] === "{") depth += 1;
    else if (code[index] === "}") {
      depth -= 1;
      if (depth === 0) return index + 1;
    }
  }
  return code.length;
}

/**
 * The CSS value a style entry sets, with its quotes removed.
 *
 * `outline: "none"` is the declaration `outline: none`, and a check that compares the quoted text against
 * `none` refuses nothing. It read as a passing rule until the fixture disagreed.
 */
function literalValueOf(value: string): string {
  const collapsed = value.replace(/\s+/g, " ").trim();
  const quoted = /^(["'`])(.*)\1$/.exec(collapsed);
  return (quoted === null ? collapsed : quoted[2]).trim();
}

interface StyleDeclaration {
  /** The key as written, so a finding names what the author will search for. */
  readonly key: string;
  /** The text assigned to it, which may be an expression rather than a literal. */
  readonly value: string;
  /** Offset of the key within the style object's text. */
  readonly index: number;
}

const STYLE_KEY = /^(?:([A-Za-z_$][\w$]*)|"([^"]+)"|'([^']+)')\s*:/;

/**
 * The declarations a style object assigns, read as key and value rather than matched as text.
 *
 * A key is taken only where it is followed by a colon, so a colon inside a ternary or a string yields a key
 * the shared list does not know and therefore no finding. That is the fail-safe direction: the colour
 * patterns run over the object's whole text regardless.
 */
function styleDeclarationsIn(body: string): StyleDeclaration[] {
  const declarations: StyleDeclaration[] = [];
  let index = 0;
  let depth = 0;

  while (index < body.length) {
    const key = depth > 0 ? STYLE_KEY.exec(body.slice(index)) : null;
    if (key !== null) {
      const name = key[1] ?? key[2] ?? key[3];
      const valueStart = index + key[0].length;
      const valueEnd = endOfValue(body, valueStart);
      declarations.push({ key: name, value: body.slice(valueStart, valueEnd).trim(), index });
      index = valueEnd;
      continue;
    }
    const character = body[index];
    if (character === '"' || character === "'" || character === "`") {
      index = endOfString(body, index);
      continue;
    }
    if (character === "{" || character === "[" || character === "(") depth += 1;
    else if (character === "}" || character === "]" || character === ")") depth -= 1;
    index += 1;
  }
  return declarations;
}

/** The offset of the comma or brace ending a value that starts at `from`. */
function endOfValue(body: string, from: number): number {
  let index = from;
  let nested = 0;
  while (index < body.length) {
    const character = body[index];
    if (character === '"' || character === "'" || character === "`") {
      index = endOfString(body, index);
      continue;
    }
    if (character === "{" || character === "[" || character === "(") nested += 1;
    else if (character === "}" || character === "]" || character === ")") {
      if (nested === 0) return index;
      nested -= 1;
    } else if (character === "," && nested === 0) return index;
    index += 1;
  }
  return body.length;
}

/** The offset just past the string opening at `from`, which ends at its quote or at a newline. */
function endOfString(body: string, from: number): number {
  const quote = body[from];
  let index = from + 1;
  while (index < body.length && body[index] !== quote && body[index] !== "\n") {
    if (body[index] === "\\") index += 1;
    index += 1;
  }
  return index + 1;
}
