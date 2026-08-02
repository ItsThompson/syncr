/* THE VERDICT DERIVED FROM WHAT A UTILITY EMITS, rather than from how it is spelled.
 *
 * This module exists to end a defect class, not to add a rule. Four times a check in this repository
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
 * The prohibitions themselves are the design language's, not new, and they live in
 * `../lib/declarations.ts` because the bundle gate, the inline-style rule and stylelint ask the same
 * question of a different input. */

import { refusalFor } from "../lib/declarations.ts";
import type { Declaration, EmittedDeclarations } from "../lib/tailwind.ts";

export interface EmittedVerdict {
  readonly utility: string;
  readonly reason: string;
}

function verdictFor(utility: string, declarations: readonly Declaration[]): EmittedVerdict | null {
  for (const [property, value] of declarations) {
    const refusal = refusalFor(property, value);
    if (refusal !== null) return { utility, reason: refusal };
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
