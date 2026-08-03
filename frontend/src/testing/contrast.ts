/* CONTRAST, COMPUTED FROM THE TOKEN FILES RATHER THAN ASSERTED.
 *
 * Every ratio the design language states is derived here: the token chain is resolved to a hex, converted to
 * relative luminance, and put through the WCAG formula. A retuned pigment that dropped a border below 3:1 or a
 * label below 4.5:1 therefore fails a test rather than reaching a review that has to notice it by eye.
 *
 * One definition, because a second copy of the formula in a second ledger is precisely the drift these ledgers
 * exist to prevent. The token layer is read by `scripts/lib/tokens.ts`, which the plate generator reads too, so a
 * plate and a ledger cannot disagree about what --ink-deep is. */

import { declaredTokens, resolveToken } from "../../scripts/lib/tokens.ts";

/** An indicator: a border, a rule, a dot or a glyph. */
export const INDICATOR_FLOOR = 3;

/** Text, at every size this product sets. */
export const TEXT_FLOOR = 4.5;

function channelLuminance(channel: number): number {
  const ratio = channel / 255;
  return ratio <= 0.039_28 ? ratio / 12.92 : ((ratio + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const digits = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (digits === null) throw new Error(`${hex} is not a six-digit hex colour`);
  const value = Number.parseInt(digits[1], 16);
  const red = channelLuminance((value >> 16) & 0xff);
  const green = channelLuminance((value >> 8) & 0xff);
  const blue = channelLuminance(value & 0xff);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

export function contrastRatio(one: string, two: string): number {
  const first = relativeLuminance(one);
  const second = relativeLuminance(two);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

/** The ratio between two token names, each resolved through the layer to a literal. */
export async function ratioBetween(foreground: string, background: string): Promise<number> {
  const tokens = await declaredTokens();
  return contrastRatio(resolveToken(tokens, foreground), resolveToken(tokens, background));
}
