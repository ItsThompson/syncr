/* THE VERDICT DERIVED FROM WHAT A UTILITY EMITS, rather than from how it is spelled.
 *
 * This module exists to end a defect class, not to add a rule. Four times a check in this ticket
 * matched syntax the author had listed and missed a spelling the language permits:
 *
 *   a glob that missed a bare barrel import
 *   a regex anchored without `-?`, so `-rotate-3` passed
 *   a tokenizer that split on every colon, so `[color:red]` became `red]`
 *   two arbitrary-value patterns written around `[`, so `blur-(--haze)` was invisible
 *
 * Each fix added a pattern and the next spelling walked through. `blur-(--haze)`, `blur-[3px]` and
 * `@apply blur-sm` are three spellings of one thing, and the thing they have in common is that all
 * three emit `filter`. So the rules below are stated over emitted declarations, which makes them
 * immune to the next form Tailwind adds and, for the same reason, cover `@apply` in a stylesheet as
 * well as a class name in markup.
 *
 * The prohibitions themselves are the design language's, not new: motion is zero without exception,
 * shadows have no blur and there is exactly one of them, and print has no blur at all. */

import type { Declaration, EmittedDeclarations } from "../lib/tailwind.ts";

/* Mirrors `stylelint.config.mjs`'s `property-disallowed-list`. Both read the same rule; keeping them
 * in step is a review question, and a divergence shows up as a shape caught in CSS and not in markup. */
const BANNED_PROPERTIES = new Set([
  "transition",
  "transition-property",
  "transition-duration",
  "transition-timing-function",
  "transition-delay",
  "animation",
  "animation-name",
  "animation-duration",
  "animation-timing-function",
  "animation-delay",
  "animation-iteration-count",
  "transform",
  "translate",
  "rotate",
  "scale",
  "will-change",
]);

/* Print has no blur. No utility in this system has any business emitting either. */
const FILTER_PROPERTIES = new Set(["filter", "backdrop-filter", "-webkit-backdrop-filter"]);

/* The system has exactly one shadow. Tailwind routes a utility's shadow through `--tw-shadow`, so
 * that is where a `shadow-*` value has to be read; the `box-shadow` declaration a utility emits is
 * always the same composition of `--tw-*` variables. An ARBITRARY PROPERTY skips that machinery and
 * writes `box-shadow` directly, which is why both are checked. */
const SHADOW_CARRIER = "--tw-shadow";
const LEGAL_SHADOW_VALUES = new Set(["var(--shadow-hard)", "none", "0 0 #0000"]);
const COMPOSED_FROM_VARIABLES = "var(--tw-";

/* `animation: none` is the one legal animation, which is why `--animate-none` is mapped at all. */
const LEGAL_MOTION_VALUES = new Set(["none"]);

export interface EmittedVerdict {
  readonly utility: string;
  readonly reason: string;
}

function verdictFor(utility: string, declarations: readonly Declaration[]): EmittedVerdict | null {
  for (const [property, value] of declarations) {
    if (FILTER_PROPERTIES.has(property)) {
      return { utility, reason: `it emits ${property}, and print has no blur` };
    }
    if (BANNED_PROPERTIES.has(property) && !LEGAL_MOTION_VALUES.has(value)) {
      return {
        utility,
        reason: `it emits ${property}: ${value}, and motion is zero without exception`,
      };
    }
    if (property === SHADOW_CARRIER && !LEGAL_SHADOW_VALUES.has(value)) {
      return {
        utility,
        reason: `it emits a shadow of ${value}, and the system has one shadow, --shadow-hard`,
      };
    }
    if (
      property === "box-shadow" &&
      !value.includes(COMPOSED_FROM_VARIABLES) &&
      !LEGAL_SHADOW_VALUES.has(value)
    ) {
      return {
        utility,
        reason: `it emits box-shadow: ${value} directly, and the system has one shadow, --shadow-hard`,
      };
    }
  }
  return null;
}

/** Every utility whose emitted CSS the design language forbids, whatever its spelling. */
export function refusedByEmittedCss(emitted: EmittedDeclarations): EmittedVerdict[] {
  const refused: EmittedVerdict[] = [];
  for (const [utility, declarations] of emitted) {
    const verdict = verdictFor(utility, declarations);
    if (verdict !== null) refused.push(verdict);
  }
  return refused;
}
