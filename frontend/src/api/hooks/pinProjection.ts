/* THE OPTIMISTIC FRAME A PIN HOLDS FOR ONE ROUND TRIP.
 *
 * THE SERVER'S PIN PLACEMENT IS EXACTLY WHAT WAS REQUESTED, which is the whole reason this is safe: the block goes
 * where the reader put it and the pin glyph appears, and neither depends on a solve. A solve's OUTPUT is not
 * predictable, so nothing here touches the unpinned remainder: it stays exactly as the last read left it, and it
 * changes when the solve lands and the week is refetched.
 *
 * THE DURATION IS UNCHANGED, because a drag moves and does not resize. So the new span is the requested instant plus
 * the block's own length, computed from the two instants it already holds rather than from a stored duration.
 *
 * NO PIN ROW IS FABRICATED. The `pins` list carries server-assigned identifiers, and inventing one would put a shape
 * on the screen that no response produces: a reader of the detail panel would meet a pin id that names nothing. What
 * the grid draws a pin from is the block's own `pinned` flag, and what the panel needs -- the superseded placement --
 * is on the block too. The real pin row arrives with the next read.
 *
 * A BLOCK THE PLAN NO LONGER HOLDS LEAVES THE VIEW UNTOUCHED. A pin can be requested against a block a landing solve
 * has just removed, and the honest answer is to change nothing: the response is what decides, and the refetch that
 * follows it is what the reader sees. */

import type { WeekView } from "./useWeek";

/** The week with one block moved to a requested instant and marked as the reader's own edit. */
export function withPinAt(view: WeekView, blockId: string, startMs: number): WeekView {
  const live = view.live;
  if (live === null) return view;
  const found = live.blocks.find((block) => block.id === blockId);
  if (found === undefined) return view;

  const durationMs = Date.parse(found.interval.end) - Date.parse(found.interval.start);
  const moved = {
    ...found,
    pinned: true,
    interval: {
      start: new Date(startMs).toISOString(),
      end: new Date(startMs + durationMs).toISOString(),
    },
    /* What the solver had chosen, which is where this block was until the reader moved it. A pin that lands on the
     * block's own placement never reaches here: a same-quarter drop issues no request at all. */
    supersededPlacement: found.interval,
  };

  return {
    ...view,
    live: { ...live, blocks: live.blocks.map((block) => (block.id === blockId ? moved : block)) },
  };
}

/** The week with one block's pin released, which is a fill change until the next solve moves it. */
export function withPinReleased(view: WeekView, blockId: string): WeekView {
  const live = view.live;
  if (live === null) return view;
  const found = live.blocks.find((block) => block.id === blockId);
  if (found === undefined) return view;
  const released = { ...found, pinned: false };
  return {
    ...view,
    live: {
      ...live,
      blocks: live.blocks.map((block) => (block.id === blockId ? released : block)),
    },
  };
}
