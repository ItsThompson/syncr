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

import { classStringsIn, utilitiesIn } from "../lib/class-strings.ts";
import { blankJsComments } from "../lib/comments.ts";
import { createPositionResolver } from "../lib/css-scan.ts";
import type { Finding } from "../lib/findings.ts";
/* An arbitrary value carries its own brackets, a form no English sentence produces, so this one is
 * matched over the whole file rather than only inside a class list. */
const ARBITRARY_VALUE = /\b[a-z][a-z0-9-]*-\[[^\]\s]+\]/g;

/* Layer 0 is the pigment ramps. Every step ends in a number, which is what separates
 * `--amber-500` from the layer 1 `--amber-wash`. */
const LAYER_ZERO_REFERENCE = /--(?:cobalt|cream|oxide|verdigris|amber)-\d+|--pigment-area-[\w-]+/g;

const ROUNDED_UTILITY = /^rounded(?:-|$)/;
const MOTION_UTILITY =
  /^(?:transition|duration|ease|animate|transform|scale|rotate|translate|skew)(?:-|$)/;

/* The one legal animation value, and the four elements allowed to be circles. The allowlist is by
 * file, so a fifth circle has to be argued for in review rather than added in passing. */
const LEGAL_ANIMATION = "animate-none";
const CIRCLE_ALLOWLIST = ["StatusDot", "RadioDot", "Radio", "AreaChip", "Avatar"];

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
        if (CIRCLE_ALLOWLIST.some((name) => context.file.includes(name))) continue;
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
