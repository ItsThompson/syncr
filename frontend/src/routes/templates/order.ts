/* Moving one rule through the evaluation order.
 *
 * THE WHOLE ORDER IS THE ANSWER, because the api takes the whole order: a partial one would leave the types it
 * does not name at positions the caller cannot see, and first-match-wins makes that a silent change to what
 * every one of them matches. So a move returns every identifier, once, in the new order.
 *
 * A MOVE PAST EITHER END RETURNS THE SAME ORDER, unchanged and not clamped-with-a-swap. The first rule cannot
 * move earlier and the last cannot move later, and answering with an equal list lets the caller send nothing
 * rather than send a reorder that reorders nothing.
 *
 * Pure: no React, no client, no DOM. */

/** The order with one identifier one place earlier, or the same order when it is already first or absent. */
export function movedEarlier(order: readonly string[], id: string): readonly string[] {
  return moved(order, id, -1);
}

/** The order with one identifier one place later, or the same order when it is already last or absent. */
export function movedLater(order: readonly string[], id: string): readonly string[] {
  return moved(order, id, 1);
}

function moved(order: readonly string[], id: string, step: number): readonly string[] {
  const from = order.indexOf(id);
  const to = from + step;
  if (from === -1 || to < 0 || to >= order.length) return order;
  const next = [...order];
  next[from] = order[to];
  next[to] = order[from];
  return next;
}
