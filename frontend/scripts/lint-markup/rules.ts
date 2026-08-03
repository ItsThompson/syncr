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
 *   - a class list sits where the scan can read it, so the four rules above have an input
 *
 * The inline `style` prop is the sixth rule family and lives in `inline-style.ts`: it reads an object's keys
 * and values rather than a class list, which is a scanner of its own.
 *
 * The vocabulary is not restated here. It is READ from `theme.css`, where each state is declared as
 * a `@custom-variant`, so a state cannot be styleable without being lintable or the reverse. */

import {
  classNameExpressions,
  classStringsIn,
  composerProductNames,
  utilitiesIn,
} from "../lib/class-strings.ts";
import { blankJsComments } from "../lib/comments.ts";
import { createPositionResolver } from "../lib/css-scan.ts";
import { abbreviate, type Finding } from "../lib/findings.ts";
import { isCircleAllowed } from "./circles.ts";
import { inlineStyleFindings } from "./inline-style.ts";

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

/* The one legal animation value. */
const LEGAL_ANIMATION = "animate-none";

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

/* A class list is read where it is WRITTEN, so a list that is not written at the attribute or inside a class
 * composer's call is read by nothing at all. Four rules take a class list as their input and all four go
 * silent together: hoisting `className="tabs rounded-full transition-all"` into a module constant turns three
 * findings into an exit code of 0, and the only available signal, the count of utilities compiled, goes DOWN
 * when the violation is added.
 *
 * The emitted-CSS gate covers part of it from the other side, because `transition-property: all` is a banned
 * declaration in the built stylesheet whatever named it. THE CIRCLE ALLOWLIST HAS NO SECOND READER: a
 * `border-radius: 50%` is legal CSS for the four allowlisted files, so only a scan that knows WHICH file
 * wrote the class can judge it. Refusing the unreadable shape is what keeps that rule enforceable.
 *
 * THREE SHAPES ARE REFUSED. An expression carrying no string literal and calling no variant map hides the
 * whole list. A template literal with an interpolation hides the interpolated part. And a TERNARY BRANCH that
 * is not a literal hides that branch: `cond ? "tabs" : LIST_CLASS` passed both this scan and the bundle gate,
 * which is the exposure that matters, because the constant behind the identifier is where a circle goes to
 * hide.
 *
 * The branches are split at top-level `?` and `:`, which needs no parser: quotes, brackets, `?.` and `??` are
 * tracked, and the segment before a `?` is a condition rather than a branch. An earlier version of this comment
 * said deciding this needed a JavaScript parser, and that was wrong for this shape: what needs one is an
 * identifier whose VALUE has to be traced, while a branch is decided by what is written in it. Every
 * `className` expression in `src` that mixes a literal with an identifier is either a variant map's call or a
 * ternary whose branches are both literals, so the rule refuses nothing the kit is written with. */
const TEMPLATE_INTERPOLATION = /\$\{/;
const STRING_LITERAL = /["'`]/;
const QUOTES = new Set(['"', "'", "`"]);
const OPENERS = new Set(["(", "[", "{"]);
const CLOSERS = new Set([")", "]", "}"]);

/**
 * The value branches of a ternary, split at top-level `?` and `:`. Empty when the expression has no ternary.
 *
 * The segment before a `?` is a condition and is not returned: `isWide ? "a" : "b"` yields the two class lists
 * and not the test that chooses between them. A nested ternary yields each of its value branches for the same
 * reason.
 */
function ternaryBranches(expression: string): string[] {
  const branches: string[] = [];
  let depth = 0;
  let start = -1;
  let quote = "";

  for (let index = 0; index < expression.length; index += 1) {
    const character = expression[index];
    if (quote !== "") {
      if (character === "\\") index += 1;
      else if (character === quote) quote = "";
      continue;
    }
    if (QUOTES.has(character)) {
      quote = character;
      continue;
    }
    if (OPENERS.has(character)) depth += 1;
    else if (CLOSERS.has(character)) depth -= 1;
    else if (depth === 0 && character === "?") {
      // `?.` and `??` are not a ternary.
      if (expression[index + 1] === "." || expression[index + 1] === "?") continue;
      start = index + 1;
    } else if (depth === 0 && character === ":" && start !== -1) {
      branches.push(expression.slice(start, index));
      start = index + 1;
    }
  }

  if (branches.length > 0 && start !== -1) branches.push(expression.slice(start));
  return branches;
}

function unreadableClassList(expression: string, products: ReadonlySet<string>): string | null {
  if (TEMPLATE_INTERPOLATION.test(expression)) {
    return "interpolates part of its class list, so the interpolated part reaches an element unread";
  }
  const hidden = ternaryBranches(expression).find((branch) => !STRING_LITERAL.test(branch));
  if (hidden !== undefined) {
    return `chooses a branch, \`${hidden.trim()}\`, which is not a class list the scan can read`;
  }
  if (STRING_LITERAL.test(expression)) return null;
  const callsVariantMap = [...products].some((name) =>
    new RegExp(`\\b${name}\\s*\\(`).test(expression),
  );
  if (callsVariantMap) return null;
  return "names a class list the scan cannot read";
}

export interface MarkupRuleContext {
  readonly file: string;
  readonly source: string;
  /** Every `data-*` name the theme declares a variant for. */
  readonly vocabulary: ReadonlySet<string>;
  /** True while the file is part of the kit, where `rounded-*` is permitted. */
  readonly isKitFile: boolean;
  /**
   * True for a test file, which is exempt from the closed-vocabulary rule and from nothing else.
   *
   * A test asserts what a component RENDERS, and a Radix control renders `data-state` and `data-highlighted`
   * whether or not the kit's vocabulary names them: `toHaveAttribute("data-state", "active")` is a claim about
   * a library's own attribute rather than a state the kit invented. The rule's purpose is that a COMPONENT
   * cannot invent an attribute, and a component file is still read, so the fence is unchanged. This is the
   * same exemption `check-channels` and `check-imports` already make, for the same reason.
   */
  readonly isTestFile: boolean;
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
        if (isCircleAllowed(context.file)) continue;
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

  for (const expression of context.isTestFile ? [] : classNameExpressions(code)) {
    const reason = unreadableClassList(expression.text, composerProductNames(code));
    if (reason === null) continue;
    findings.push({
      file: context.file,
      line: expression.line,
      column: expression.column,
      check: "readable-class-list",
      message:
        `className={${abbreviate(expression.text)}} ${reason}. Four rules take a class list as ` +
        "their input, and all four go silent on a list they cannot see. Write the list at the " +
        "attribute, or inside a class composer's call.",
    });
  }

  findings.push(...inlineStyleFindings({ file: context.file, code, at }));

  const seen = new Set<string>();
  for (const shape of context.isTestFile ? [] : DATA_ATTRIBUTE_SHAPES) {
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
