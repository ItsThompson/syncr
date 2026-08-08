/* THE WCAG CONTRAST FORMULA AND THE TWO FLOORS, IN ONE PLACE.
 *
 * Two consumers need them and each used to carry its own copy: `src/testing/contrast.ts`, which the pigment and
 * primitive suites compute their ratios through, and `scripts/audit-contrast`, which generates the committed
 * ledger. The copied file's own header forbids exactly that -- "one definition, because a second copy of the
 * formula in a second ledger is precisely the drift these ledgers exist to prevent" -- and the second copy was
 * made anyway, so the floors briefly had two homes and a retune of one would have left the other stating a
 * different rule.
 *
 * IT LIVES UNDER `scripts/` BECAUSE THAT IS THE DIRECTION THAT RESOLVES. A script cannot import from `src/`
 * without the bundler, and a test can import from `scripts/` because vitest resolves both: `src/testing/
 * contrast.ts` and `src/testing/noticeLiterals.ts` already read `scripts/lib/`. So the shared definition sits on
 * the side both can reach, and the test-side module re-exports it.
 *
 * THE FLOORS ARE WCAG'S, not this product's: 4.5:1 for text at every size this product sets, and 3:1 for a
 * non-text indicator. What IS this product's is where each applies, and that lives with the consumer that knows
 * which is which. */

/** An indicator: a border, a rule, a dot or a glyph. WCAG's non-text floor. */
export const INDICATOR_FLOOR = 3;

/** Text, at every size this product sets. */
export const TEXT_FLOOR = 4.5;

const SIX_DIGIT_HEX = /^#([0-9a-f]{6})$/i;

function channelLuminance(channel: number): number {
  const ratio = channel / 255;
  return ratio <= 0.039_28 ? ratio / 12.92 : ((ratio + 0.055) / 1.055) ** 2.4;
}

export function channelsOf(hex: string): [number, number, number] {
  const digits = SIX_DIGIT_HEX.exec(hex.trim());
  if (digits === null) throw new Error(`${hex} is not a six-digit hex colour`);
  const value = Number.parseInt(digits[1], 16);
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

/** True for a literal a ratio can be computed from at all. */
export function isSixDigitHex(value: string): boolean {
  return SIX_DIGIT_HEX.test(value.trim());
}

function relativeLuminance(hex: string): number {
  const [red, green, blue] = channelsOf(hex);
  return (
    0.2126 * channelLuminance(red) +
    0.7152 * channelLuminance(green) +
    0.0722 * channelLuminance(blue)
  );
}

export function contrastRatio(one: string, two: string): number {
  const first = relativeLuminance(one);
  const second = relativeLuminance(two);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

/**
 * The literal `color-mix(in srgb, one P%, two)` resolves to.
 *
 * Needed because a token chain resolves to a hex and a mix does not: the hatch on a chart fill is
 * `color-mix(in srgb, var(--ai) var(--hatch-mix), var(--paper-raised))`, so its ratio against the fill it sits on
 * cannot be computed from token values alone. Mixing in the sRGB space is a per-channel interpolation of the
 * gamma-encoded values, which is what CSS Color 5 specifies for that colour space.
 */
export function mixInSrgb(one: string, two: string, percent: number): string {
  const left = channelsOf(one);
  const right = channelsOf(two);
  const blended = left.map((value, index) =>
    Math.round((value * percent + right[index] * (100 - percent)) / 100),
  );
  return `#${blended.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}
