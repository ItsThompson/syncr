/* CONTRAST, COMPUTED FROM THE TOKEN FILES RATHER THAN ASSERTED.
 *
 * Every ratio the design language states is derived here: the token chain is resolved to a hex, converted to
 * relative luminance, and put through the WCAG formula. A retuned pigment that dropped a border below 3:1 or a
 * label below 4.5:1 therefore fails a test rather than reaching a review that has to notice it by eye.
 *
 * ONE DEFINITION, and this file no longer holds it. The formula and the two floors live in
 * `scripts/lib/contrast.ts`, because the generated ledger's gate needs them too and a script cannot import from
 * `src/`: a second copy of the formula in a second ledger is precisely the drift these ledgers exist to prevent,
 * and the ledger's first version made exactly that copy. What is re-exported here is the same definition under
 * the name the kit's suites already import, so no call site changed.
 *
 * The token layer is read by `scripts/lib/tokens.ts`, which the plate generator reads too, so a plate and a
 * ledger cannot disagree about what --ink-deep is. */

import { declaredTokens, resolveToken } from "../../scripts/lib/tokens.ts";

export {
  INDICATOR_FLOOR,
  TEXT_FLOOR,
  contrastRatio,
  mixInSrgb,
} from "../../scripts/lib/contrast.ts";

import { contrastRatio } from "../../scripts/lib/contrast.ts";

/** The ratio between two token names, each resolved through the layer to a literal. */
export async function ratioBetween(foreground: string, background: string): Promise<number> {
  const tokens = await declaredTokens();
  return contrastRatio(resolveToken(tokens, foreground), resolveToken(tokens, background));
}
