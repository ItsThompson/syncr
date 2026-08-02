/* The design rules that live in markup rather than in a stylesheet.
 *
 * stylelint enforces the CSS half. These are the half that reaches the DOM as a class name or an
 * attribute, which no CSS linter can see:
 *
 *   - no arbitrary value: a value not on the scale becomes a token first
 *   - no layer 0 token in a component: a pigment without a rule is what layer 1 exists to prevent
 *   - `rounded-*` only inside the kit, and `rounded-full` only on the four legal circles
 *   - no decorative motion, because motion is zero without exception
 *   - no `data-*` attribute outside the closed vocabulary
 *
 * The vocabulary is not restated here. It is READ from `theme.css`, where each state is declared as
 * a `@custom-variant`, so a state cannot be styleable without being lintable or the reverse. */

import path from "node:path";

import { classStringsIn, utilitiesIn } from "../lib/class-strings.ts";
import { blankJsComments } from "../lib/comments.ts";
import { createPositionResolver } from "../lib/css-scan.ts";
import { cssPropertyFor, refusalFor } from "../lib/declarations.ts";
import type { Finding } from "../lib/findings.ts";

const basename = (file: string): string => path.basename(file, path.extname(file));
/* An arbitrary value carries its own delimiters, a form no English sentence produces, so these are
 * matched over the whole file rather than only inside a class list.
 *
 * TWO DELIMITERS, NOT ONE. Tailwind v4 accepts `w-[13px]` and `w-(--wide)`, and the paren form is
 * what its own documentation recommends for a CSS variable. Both patterns were written around `[`,
 * so the paren form was invisible and `w-(--wide)` shipped `width: var(--wide)`, which is criterion
 * 11's own `w-[13px]` case in a different spelling. Section 14's `--ai` makes the paren form the
 * first thing the week grid will reach for. */
const ARBITRARY_VALUE = /\b[a-z][a-z0-9-]*-\[[^\]\s]+\]/g;
const ARBITRARY_VARIABLE = /\b[a-z][a-z0-9-]*-\(--[^)\s]+\)/g;

/* Layer 0 is the pigment ramps. Every step ends in a number, which is what separates
 * `--amber-500` from the layer 1 `--amber-wash`. */
const LAYER_ZERO_REFERENCE = /--(?:cobalt|cream|oxide|verdigris|amber)-\d+|--pigment-area-[\w-]+/g;

const ROUNDED_UTILITY = /^rounded(?:-|$)/;
/* `-?` is not cosmetic. Tailwind's negative utilities carry a leading minus, so an anchored pattern
 * without it caught `rotate-3` and missed `-rotate-3`, which compiles to `rotate: calc(3deg * -1)`.
 * A rule that catches the positive form of a utility and misses its negation is the barrel-import
 * defect one character over. */
const MOTION_UTILITY =
  /^-?(?:transition|duration|ease|animate|transform|scale|rotate|translate|skew)(?:-|$)/;

/* Tailwind v4's arbitrary-PROPERTY form, `[color:red]`, which sets a declaration straight from a
 * class list. The theme cannot fence it: it is not namespace-driven, so clearing `--color-*` and
 * `--animate-*` does not touch it, and lint is the only line of defence. It reached a raw hex, a
 * named colour, a blurred shadow and a custom property into the DOM with every check green. */
const ARBITRARY_PROPERTY = /^-{0,2}\[-{0,2}[a-z][a-z-]*:/;

/* The one legal animation value, and the four elements allowed to be circles. Matched on the
 * FILENAME, not on the path: `context.file.includes(name)` allowed every file inside a directory
 * named `AreaChip/` or `Avatar/` a circle, which is not what the design language closes the list at. */
const LEGAL_ANIMATION = "animate-none";
const CIRCLE_ALLOWLIST = new Set(["StatusDot", "RadioDot", "AreaChip", "Avatar"]);

/* Three JSX shapes reach the DOM as the same attribute, and all three are the state a component
 * should not be inventing:
 *
 *   <span data-busy="true">        written with a value
 *   <span data-busy>               valueless, which React renders as data-busy="true"
 *   <span {...{ "data-busy": x }}> spread, where the name is a quoted property
 *
 * Two patterns rather than one loose one. The first covers attribute position; the second covers a
 * FULLY quoted name, so a data attribute merely mentioned inside a longer sentence is not a match. */
const DATA_ATTRIBUTE_SHAPES = [
  /(?<=[\s{])(data-[a-z][a-z0-9-]*)(?=[\s/>=}])/g,
  /(?<=["'])(data-[a-z][a-z0-9-]*)(?=["'])/g,
];

/* THE INLINE `style` PROP. A door the theme cannot close and stylelint never sees, because stylelint
 * reads stylesheets and this is a TSX object literal.
 *
 * Only the absolutes are refused here, not the prop itself: the week grid computes a block's height
 * and top offset per block, and `style` is the only way to set a derived pixel value. So a raw colour
 * literal, a blurred shadow and a motion property are findings, and a computed length is not. Setting
 * a custom property is how the sheets already pass an Area's ink to a component, so `--x` is fine.
 *
 * THE PROPERTY SIDE IS READ FROM THE OBJECT'S KEYS, CONVERTED, AND ASKED OF THE SHARED LIST. It was
 * written as CSS-spelled patterns before, `/\btransform\s*:/` and friends, while React writes
 * `willChange` and `backdropFilter`: `\b` does not match inside a camelCase word, so
 * `style={{ backdropFilter: "blur(4px)", willChange: "transform" }}` rendered a blur on a kit element
 * with all seven checks green, and `style={{ outline: "none" }}` removed the focus ring of a
 * keyboard-first product. Of the sixteen properties stylelint refuses, the pattern list covered three
 * roots. One list with a key conversion in front of it covers all of them, and the next property added
 * to the design language reaches this rule with no edit here. */
const STYLE_PROP = /\bstyle\s*=\s*\{\{/g;

/* Where the VALUE is the offence rather than the property, so no key conversion helps. Matched over
 * the object's whole text, since a colour is a colour wherever it is assigned. */
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

export interface MarkupRuleContext {
  readonly file: string;
  readonly source: string;
  /** Every `data-*` name the theme declares a variant for. */
  readonly vocabulary: ReadonlySet<string>;
  /** True while the file is part of the kit, where `rounded-*` is permitted. */
  readonly isKitFile: boolean;
}

export function lintSource(context: MarkupRuleContext): Finding[] {
  const at = createPositionResolver(context.source);
  /* Every pattern below runs over CODE, not prose. Offsets are preserved, so a finding still points
   * at the real line and column. */
  const code = blankJsComments(context.source);
  const findings: Finding[] = [];

  for (const match of code.matchAll(ARBITRARY_VALUE)) {
    findings.push({
      file: context.file,
      ...at(match.index),
      check: "no-arbitrary-value",
      message: `${match[0]} is an arbitrary value. A value not on the scale becomes a token first.`,
    });
  }

  for (const match of code.matchAll(ARBITRARY_VARIABLE)) {
    findings.push({
      file: context.file,
      ...at(match.index),
      check: "no-arbitrary-value",
      message:
        `${match[0]} is an arbitrary value in Tailwind's parenthesised form, which is the same ` +
        "thing as the bracket form. A value not on the scale becomes a token first.",
    });
  }

  for (const match of code.matchAll(LAYER_ZERO_REFERENCE)) {
    findings.push({
      file: context.file,
      ...at(match.index),
      check: "no-layer-zero-token",
      message: `${match[0]} is a layer 0 ramp step. A component reads a layer 1 semantic name.`,
    });
  }

  for (const classString of code.length === 0 ? [] : classStringsIn(code)) {
    for (const utility of utilitiesIn(classString.text)) {
      const position = { line: classString.line, column: classString.column };

      if (ARBITRARY_PROPERTY.test(utility)) {
        findings.push({
          file: context.file,
          ...position,
          check: "no-arbitrary-property",
          message:
            `${utility} sets a CSS declaration straight from a class list, so no theme namespace ` +
            "can fence it. A value not on the scale becomes a token first.",
        });
        continue;
      }

      if (MOTION_UTILITY.test(utility) && utility !== LEGAL_ANIMATION) {
        findings.push({
          file: context.file,
          ...position,
          check: "motion-is-zero",
          message: `${utility} animates or transforms. Motion is zero, without exception.`,
        });
      }

      if (!ROUNDED_UTILITY.test(utility)) continue;

      if (utility === "rounded-full") {
        if (CIRCLE_ALLOWLIST.has(basename(context.file))) continue;
        findings.push({
          file: context.file,
          ...position,
          check: "circle-allowlist",
          message:
            "rounded-full is allowed on the status dot, the radio dot, the Area chip and the " +
            "avatar, and the allowlist is closed at those four.",
        });
        continue;
      }

      if (context.isKitFile) continue;
      findings.push({
        file: context.file,
        ...position,
        check: "no-radius-outside-the-kit",
        message: `${utility} rounds a corner outside the kit. Radius is zero.`,
      });
    }
  }

  for (const match of code.matchAll(STYLE_PROP)) {
    const objectEnd = findObjectEnd(code, match.index + match[0].length - 1);
    const body = code.slice(match.index, objectEnd);
    for (const violation of RAW_VALUE_PATTERNS) {
      if (!violation.pattern.test(body)) continue;
      findings.push({
        file: context.file,
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
          file: context.file,
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
      if (value === CIRCLE_RADIUS_VALUE && CIRCLE_ALLOWLIST.has(basename(context.file))) continue;
      findings.push({
        file: context.file,
        ...at(match.index + declaration.index),
        check: "no-radius-in-style",
        message:
          `an inline style sets ${declaration.key}: ${declaration.value}. Radius is zero, and 50% ` +
          "survives for the status dot, the radio dot, the Area chip and the avatar only.",
      });
    }
  }

  const seen = new Set<string>();
  for (const shape of DATA_ATTRIBUTE_SHAPES) {
    for (const match of code.matchAll(shape)) {
      if (context.vocabulary.has(match[1])) continue;
      // One finding per position, so a name matched by both shapes is reported once.
      if (seen.has(`${match[1]}:${match.index}`)) continue;
      seen.add(`${match[1]}:${match.index}`);
      findings.push({
        file: context.file,
        ...at(match.index),
        check: "closed-state-vocabulary",
        message:
          `${match[1]} is not in the closed state vocabulary. Declare the state as a ` +
          "@custom-variant in theme.css, so the same name is both styleable and lintable.",
      });
    }
  }

  return findings.toSorted((left, right) => (left.line ?? 0) - (right.line ?? 0));
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
 * `outline: "none"` is the declaration `outline: none`, and a check that compares the quoted text
 * against `none` refuses nothing. It read as a passing rule until the fixture disagreed.
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
 * A key is taken only where it is followed by a colon, so a colon inside a ternary or a string yields
 * a key the shared list does not know and therefore no finding. That is the fail-safe direction: the
 * colour patterns run over the object's whole text regardless.
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
