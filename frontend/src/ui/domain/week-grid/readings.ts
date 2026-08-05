/* THE STRIP'S THREE FIGURES, AND THE WORD THAT QUALIFIES THE BLOCK COUNT.
 *
 * A figure arrives as minutes and reads as hours, and how it reads is a domain decision rather than a container's,
 * which is why `StatCell` takes a formatted figure and this module produces one.
 *
 * ONE DECIMAL PLACE. `80.8h` is what the design record renders and it is the right precision for a week: a whole
 * number hides a two-hour swing across three cells, and two decimals invite a reader to compare minutes on a
 * surface whose whole point is the shape of a week.
 *
 * PLAN CURRENCY SHARES THE SCHEDULED CELL'S SUB-LINE rather than claiming a fifth cell, because the strip's
 * content budget is settled at three readings plus the verdict, and currency qualifies the block count, which is
 * exactly what it does: it says whether that count is current. Never a spinner, and never anything that moves.
 *
 * THE SHARE IS A RATIO OF THE TWO FIGURES THE SERVER SENT, never a difference computed here. The same arithmetic
 * produces both, so the strip and the pie review cannot disagree about a percentage even while the denominator's
 * own definition is under revision. Deriving it from what the grid happens to draw would make two surfaces answer
 * one question differently, which is the whole reason the figures are computed server-side. */

/** Whether the block count is current, being recomputed, or the last one that worked. Never a spinner. */
export type PlanCurrency = "current" | "solving" | "stale";

/** The three readings, the count they describe, and the word that qualifies it. */
export interface StripReadings {
  readonly scheduledMinutes: number;
  readonly discretionaryMinutes: number;
  readonly unallocatedMinutes: number;
  readonly blockCount: number;
  readonly planCurrency: PlanCurrency;
}

const MINUTES_IN_HOUR = 60;
const PLACES = 1;
const PERCENT = 100;

/** Minutes as hours, to one decimal place: `80.8h`. */
export function formatHours(minutes: number): string {
  return `${(minutes / MINUTES_IN_HOUR).toFixed(PLACES)}h`;
}

/**
 * A share of the discretionary denominator: `35.3% of discretionary`.
 *
 * A zero denominator reads as the sentence rather than as `NaN%` or `0.0%`: a week with no discretionary time at
 * all has no share to report, and reporting zero would say the opposite of what is true.
 */
export function formatShare(minutes: number, ofMinutes: number): string {
  if (ofMinutes <= 0) return "no discretionary time";
  return `${((minutes / ofMinutes) * PERCENT).toFixed(PLACES)}% of discretionary`;
}

/**
 * The SCHEDULED cell's sub-line: the block count, and the word that says whether it is current.
 *
 * `91 blocks` when it is, `91 · solving` and `91 · stale` when it is not. The count is spelled out only in the
 * current case, because the other two need the room for the word and the word is what the reader is being told.
 */
export function formatCurrency(blockCount: number, currency: PlanCurrency): string {
  if (currency === "current") return `${blockCount} blocks`;
  return `${blockCount} · ${currency}`;
}
