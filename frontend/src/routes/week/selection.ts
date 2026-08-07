/* KEYBOARD TRAVERSAL OVER THE WEEK, AS ARITHMETIC RATHER THAN AS A CURSOR.
 *
 * THE KEYBOARD REACHES EVERY BLOCK AT EVERY TIER. `j` and `k` do not care how tall a block is, so the smallest block
 * in the week is exactly as reachable as the largest. That matters more than the pointer path: a fifteen-minute block
 * at the twelve-hour default is under 14px tall on a 13-inch display, which is a genuinely small pointer target and a
 * perfectly ordinary keyboard one.
 *
 * IN TIME ORDER, WHICH IS NOT DOCUMENT ORDER. A column's blocks arrive in the order the payload holds them, and
 * overlap layout does not sort them either, so every move here sorts by start and then by end: two blocks beginning at
 * one instant are ordered by the one that finishes first, which is the same tie-break the overlap sweep uses.
 *
 * `h` AND `l` PRESERVE THE NEAREST BLOCK IN TIME, not the index. An index would land on a column's third block
 * whatever time it holds, which is meaningless when Monday has nine blocks and Tuesday has two; the nearest start is
 * what a reader means by "the same time in the next day".
 *
 * A COLUMN WITH NO BLOCKS IS SKIPPED RATHER THAN SELECTED EMPTY. Moving to a day that holds nothing would clear the
 * selection, and the reader would have to start again from the day they were on. So `h` and `l` walk past empty
 * columns and stop at the edge, which is what makes the edges a real boundary rather than a place selection dies. */

import type { WeekDay } from "../../ui/domain";

/** Which block is selected: the column it is in and the block's own id. */
export interface Selected {
  readonly date: string;
  readonly blockId: string;
}

/** A block's start in its own column's minutes, which is what a traversal compares. */
interface Ordered {
  readonly id: string;
  readonly startMin: number;
  readonly endMin: number;
}

function inTimeOrder(day: WeekDay): Ordered[] {
  return day.blocks
    .map((block) => ({ id: block.id, startMin: block.span.startMin, endMin: block.span.endMin }))
    .toSorted((left, right) => left.startMin - right.startMin || left.endMin - right.endMin);
}

function dayOf(days: readonly WeekDay[], date: string): WeekDay | undefined {
  return days.find((day) => day.date === date);
}

/** The first block of the week in time order, which is where a first keystroke with no selection lands. */
export function firstBlock(days: readonly WeekDay[]): Selected | null {
  for (const day of days) {
    const first = inTimeOrder(day).at(0);
    if (first !== undefined) return { date: day.date, blockId: first.id };
  }
  return null;
}

/** The next or previous block in the current column, in time order, or the current one at the edge. */
export function stepInColumn(
  days: readonly WeekDay[],
  from: Selected | null,
  direction: 1 | -1,
): Selected | null {
  if (from === null) return firstBlock(days);
  const day = dayOf(days, from.date);
  if (day === undefined) return from;
  const ordered = inTimeOrder(day);
  const at = ordered.findIndex((block) => block.id === from.blockId);
  if (at === -1) return ordered.at(0) === undefined ? from : { ...from, blockId: ordered[0].id };
  const next = ordered.at(at + direction);
  /* At the edge the selection stands. A wrap would move a reader to the other end of a day they were reading down,
   * and clearing it would cost them their place for pressing one key too many. */
  if (next === undefined || at + direction < 0) return from;
  return { date: day.date, blockId: next.id };
}

/** The nearest block in time in the next or previous non-empty column, or the current one at the edge. */
export function stepColumn(
  days: readonly WeekDay[],
  from: Selected | null,
  direction: 1 | -1,
): Selected | null {
  if (from === null) return firstBlock(days);
  const at = days.findIndex((day) => day.date === from.date);
  if (at === -1) return from;
  const anchor = startOf(days[at], from.blockId);

  for (let index = at + direction; index >= 0 && index < days.length; index += direction) {
    const nearest = nearestTo(days[index], anchor);
    if (nearest !== null) return { date: days[index].date, blockId: nearest };
  }
  return from;
}

/** The block whose start is closest to a minute, or null in a column with none. */
function nearestTo(day: WeekDay, startMin: number): string | null {
  let best: Ordered | null = null;
  for (const block of inTimeOrder(day)) {
    if (best === null || Math.abs(block.startMin - startMin) < Math.abs(best.startMin - startMin)) {
      best = block;
    }
  }
  return best?.id ?? null;
}

function startOf(day: WeekDay | undefined, blockId: string): number {
  return day?.blocks.find((block) => block.id === blockId)?.span.startMin ?? 0;
}

/** The selection a redraw leaves standing: the same block where the week still holds it, and null where it does not. */
export function surviving(days: readonly WeekDay[], selected: Selected | null): Selected | null {
  if (selected === null) return null;
  const day = dayOf(days, selected.date);
  if (day === undefined) return null;
  return day.blocks.some((block) => block.id === selected.blockId) ? selected : null;
}
