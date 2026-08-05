/* THE GRID'S NUMBERS, MIRRORED FROM THE TOKENS THAT DRAW THEM.
 *
 * The geometry is arithmetic and the arithmetic runs in TypeScript, which cannot read a custom property. So
 * each value below is a second spelling of a declaration in `tokens.css` or `tokens/type.css`, and
 * `__tests__/metrics.test.ts` reads those files and requires every constant here to equal the token it
 * mirrors. That is the shape `ui/primitives/quarterHour.ts` already uses for `--snap` and the theme uses for
 * its two breakpoint literals: the duplicate is made incapable of drifting rather than avoided, because
 * avoiding it is not available across that boundary.
 *
 * Nothing here is a choice. Every value's reasoning lives beside the token it mirrors. */

/** `--block-h-label`. At or above this a block carries a wrapping title. */
export const BLOCK_H_LABEL_PX = 19;

/** `--block-h-compact`. At or above this a block carries one line of title at the smaller size. */
export const BLOCK_H_COMPACT_PX = 13;

/** `--block-h-sliver`. At or above this a block carries its origin mark and no title. */
export const BLOCK_H_SLIVER_PX = 8;

/** `--block-pad-t`. The air between the Area rule and the first line of the title. */
export const BLOCK_PAD_T_PX = 2;

/** `--rule-emphasis`. The Area top rule's weight, which the title's line count has to pay for. */
export const AREA_RULE_PX = 2;

/** `--hairline`. The bottom rule, which closes the block at grid weight. */
export const BOTTOM_RULE_PX = 1;

/** `--lh-block-px`. One line of block title: `--fs-block` at `--lh-block`. */
export const LINE_HEIGHT_PX = 13.8;

/** `--grid-major`. Minutes between hour lines. */
export const GRID_MAJOR_MINUTES = 60;

/** `--grid-minor`. Minutes between quarter lines, which must equal the snap. */
export const GRID_MINOR_MINUTES = 15;

/** `--overlap-max-split`. Past this depth an even split leaves no column to write in. */
export const OVERLAP_MAX_SPLIT = 3;

/** `--zoom-min`. The shallowest zoom the range offers. */
export const ZOOM_MIN_HOURS = 6;

/** `--zoom-max`. The deepest zoom the range offers, before the per-display clamp. */
export const ZOOM_MAX_HOURS = 24;

/** `--visible-hours`. The default, which the user changes and the clamp bounds. */
export const VISIBLE_HOURS_DEFAULT = 12;

/** `--grid-h`. The grid a 13 inch reference display yields, used until one is measured. */
export const GRID_H_PX = 626;

/** `--day-header-h`. Inside the grid's own height and outside the canvas the blocks are drawn in. */
export const DAY_HEADER_H_PX = 28;

/** `--axis-w`. The time axis column, which is fixed while the day columns share the surplus. */
export const AXIS_W_PX = 56;
