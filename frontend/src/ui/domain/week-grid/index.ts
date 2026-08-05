/* THE WEEK GRID: geometry derivation, the tier ladder, overlap columns, the bands that explain a gap, the now
 * rule, the summary strip, and the read-only render of one week's plan.
 *
 * THE DENSEST SURFACE IN THE PRODUCT, and the reason it is a family of its own rather than a component. A reader
 * has to answer three questions from one rectangle -- what is this, whose time is it, and may it move -- across
 * roughly 210 of them, and every module here exists to keep one of those answers honest:
 *
 *   metrics     the numbers the tokens draw with, mirrored so arithmetic can reach them
 *   geometry    the extent, pixels per minute, and the box a span gets. The axis never lies
 *   zoom        the range, and the clamp the modal thirty-minute block puts on it
 *   tiers       the four-step ladder, and the line count a wrapping title is clamped to
 *   overlap     the sweep, the columns, and the stagger past depth three
 *   readings    the strip's three figures, and the word that qualifies the block count
 *
 * WHAT IS NOT HERE. Interaction is not: the discrete drag, keyboard traversal, pinning, the verdict panel and the
 * detail panel arrive with whatever owns them, and every state a block can be in is a PROP here rather than a
 * thing this family decides. Nor is the wire: the grid renders `WeekDay`s, and turning a response into one is the
 * route's business, because the kit does not know what a response is. */

export { Block, type BlockPlacement, type BlockProps, type BlockStates } from "./Block";
export { DayColumn, type DayColumnProps } from "./DayColumn";
export { EmptyWeek, type EmptyWeekProps, type EmptyWeekReason } from "./EmptyWeek";
export { ForbiddenBand, type ForbiddenBandProps } from "./ForbiddenBand";
export { GridLines, type GridLinesProps } from "./GridLines";
export { NowRule, type NowRuleProps } from "./NowRule";
export { SummaryStrip, type SummaryStripProps, type VerdictReading } from "./SummaryStrip";
export { TimeAxis, type TimeAxisProps } from "./TimeAxis";
export { WeekGrid, type WeekGridProps } from "./WeekGrid";

export {
  boxOf,
  canvasHeightPx,
  extentOf,
  lineOffsets,
  offsetSpanOf,
  pxPerMinute,
  totalMinutes,
  type Box,
} from "./geometry";
export {
  AREA_RULE_PX,
  AXIS_W_PX,
  BLOCK_H_COMPACT_PX,
  BLOCK_H_LABEL_PX,
  BLOCK_H_SLIVER_PX,
  BLOCK_PAD_T_PX,
  BOTTOM_RULE_PX,
  DAY_HEADER_H_PX,
  GRID_H_PX,
  GRID_MAJOR_MINUTES,
  GRID_MINOR_MINUTES,
  LINE_HEIGHT_PX,
  OVERLAP_MAX_SPLIT,
  VISIBLE_HOURS_DEFAULT,
  ZOOM_MAX_HOURS,
  ZOOM_MIN_HOURS,
} from "./metrics";
export { placeOverlaps, type Placement } from "./overlap";
export {
  formatCurrency,
  formatHours,
  formatShare,
  type PlanCurrency,
  type StripReadings,
} from "./readings";
export { tierDrawsTitle, tierFor, titleLineCount } from "./tiers";
export type {
  BandReason,
  BlockTier,
  Extent,
  GridBand,
  GridBlock,
  Instants,
  OffsetSpan,
  WeekDay,
} from "./types";
export {
  MODAL_DURATION_MINUTES,
  clampVisibleHours,
  zoomCap,
  zoomLevels,
  type ZoomLevel,
} from "./zoom";
