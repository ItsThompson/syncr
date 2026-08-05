/* THE TIER LADDER, AND THE LINE COUNT A WRAPPING TITLE IS CLAMPED TO.
 *
 * Four tiers, because height is proportional to duration and at a deep zoom a short block falls below the
 * height its own title needs. The BLOCK degrades and the axis does not:
 *
 *   >= --block-h-label    the title wraps to as many lines as fit
 *   >= --block-h-compact  one line at the smaller size, and no top padding
 *   >= --block-h-sliver   no title. the origin mark and the Area rule survive
 *   below                 the Area rule alone
 *
 * THE TITLE WRAPS; IT DOES NOT TRUNCATE. A measured ledger over one real week found 4 of 37 distinct titles
 * becoming ambiguous under end-ellipsis, because an ellipsis discards precisely the tail that separates a title
 * from its sibling: `Amazon Interview Prep` and `Amazon Interview Prep - Behavioral` both collapse to
 * `Amazon Interview P...`. So the line count is computed per block from its own height,
 *
 *   lines = floor( (height - 2 area rule - 2 pad-top - 1 bottom rule) / --lh-block-px )
 *
 * and the title is clamped to that count, which puts a clip on a LINE BOUNDARY rather than mid-glyph and keeps
 * the tail on any block tall enough for a second line. */

import {
  AREA_RULE_PX,
  BLOCK_H_COMPACT_PX,
  BLOCK_H_LABEL_PX,
  BLOCK_H_SLIVER_PX,
  BLOCK_PAD_T_PX,
  BOTTOM_RULE_PX,
  LINE_HEIGHT_PX,
} from "./metrics";
import type { BlockTier } from "./types";

/** What the block's own chrome costs before a single line of title fits. */
const CHROME_PX = AREA_RULE_PX + BLOCK_PAD_T_PX + BOTTOM_RULE_PX;

/** The tier a height lands in. Every height lands in one: the ladder has no gap and no ceiling. */
export function tierFor(heightPx: number): BlockTier {
  if (heightPx >= BLOCK_H_LABEL_PX) return "label";
  if (heightPx >= BLOCK_H_COMPACT_PX) return "compact";
  if (heightPx >= BLOCK_H_SLIVER_PX) return "sliver";
  return "hairline";
}

/** Whether a tier draws a title at all, which is what decides whether the origin mark claims the glyph slot. */
export function tierDrawsTitle(tier: BlockTier): boolean {
  return tier === "label" || tier === "compact";
}

/**
 * How many lines of title a block of this height holds.
 *
 * One at the compact tier by definition: the tier exists because there is room for a line and not for the
 * padding above it. Zero below, where there is no title to count. At the label tier it is the arithmetic above,
 * floored at one, because a block at exactly the 19px floor has 18.8px of content in it and would otherwise
 * compute zero lines while being the tier whose whole purpose is to carry one.
 */
export function titleLineCount(heightPx: number): number {
  const tier = tierFor(heightPx);
  if (!tierDrawsTitle(tier)) return 0;
  if (tier === "compact") return 1;
  return Math.max(1, Math.floor((heightPx - CHROME_PX) / LINE_HEIGHT_PX));
}
