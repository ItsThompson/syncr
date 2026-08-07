/* THE DISCRETE DRAG. Continuous input, discrete output, and the block does not move.
 *
 * WHAT IS STATE DURING A DRAG IS THE MARKER'S POSITION AND NOTHING ELSE. The block stays exactly where it is, so a
 * drag re-renders one hairline rather than 210 positioned elements, and motion stays zero: there is no follow, no
 * ghost and no settle. One redraw happens on drop.
 *
 * THE MARKER SNAPS TO THE QUARTER HOUR because the snap is fifteen minutes, and the quarter lines step up to hour
 * weight for the same reason: the reader is aiming at them, so they sharpen at the one moment that matters. That is
 * a discrete state change, not motion.
 *
 * A DROP THAT STATES NO NEW PLACEMENT ISSUES NO REQUEST, and there are two of those. A release on the quarter hour
 * the pointer STARTED over is a click or a jitter: a plain click selects a block and must not move it, and a pin is a
 * training label, so one created by a jittery pointer is a false preference the learning layer would fit against. A
 * release that lands the block back on its own start states nothing either. The same argument covers a release with no
 * target at all: a pointer released outside the column has stated no placement, so it cancels rather than clamping to
 * an edge the reader never aimed at. Clamping would turn a slip into a hard constraint on the solver.
 *
 * THE INSTANT IS BUILT FROM THE COLUMN'S OWN START PLUS ELAPSED MINUTES, never from a wall time. A column's offsets
 * are measured between instants, so adding minutes to its start cannot produce a local time that does not exist:
 * dragging across a spring-forward boundary lands on a real instant with no special case, and the hour that does not
 * exist is simply not in the difference. */

import { useCallback, useEffect, useRef, useState } from "react";

import { SNAP_MINUTES } from "../../primitives";
import type { Extent } from "./types";

const MILLISECONDS_IN_MINUTE = 60_000;

/** Where a drag began: the block, the column it is in, and the minute it currently starts at. */
export interface DragOrigin {
  readonly blockId: string;
  readonly date: string;
  /** The block's own start, in the column's minutes, which is what a same-quarter drop is compared against. */
  readonly fromMin: number;
  /** The instant the column's local day began, which every offset here is measured from. */
  readonly dayStartMs: number;
  /** The column's canvas, whose box turns a pointer position into a minute. */
  readonly canvas: HTMLElement | null;
  readonly pointerY: number;
}

/** Where the hairline currently sits: one column, one quarter hour. */
export interface InsertionAt {
  readonly date: string;
  readonly atMin: number;
}

/** What a drop states: the block, and the instant it now begins at. */
export interface BlockDrop {
  readonly blockId: string;
  readonly date: string;
  readonly atMin: number;
  /** The new start, as an instant, so a caller sends it without re-deriving a wall time. */
  readonly startMs: number;
}

export interface DiscreteDragOptions {
  readonly extent: Extent;
  readonly pxPerMin: number;
  /** Called once, on a drop that states a different quarter hour from the one the block already holds. */
  readonly onDrop?: ((drop: BlockDrop) => void) | undefined;
}

export interface DiscreteDrag {
  /** True while a drag is in progress, which is what steps the quarter lines up. */
  readonly isDragging: boolean;
  /** Where the hairline sits, or null while the pointer states no target. */
  readonly insertion: InsertionAt | null;
  readonly begin: (origin: DragOrigin) => void;
}

/** What the whole drag is decided from, held in a ref so the window listeners attach once per drag. */
interface Live extends DiscreteDragOptions {
  readonly origin: DragOrigin | null;
  /** The quarter hour the pointer was over when it went down, which is what a click is compared against. */
  readonly grabbedAtMin: number | null;
  readonly atMin: number | null;
}

export function useDiscreteDrag(options: DiscreteDragOptions): DiscreteDrag {
  const [origin, setOrigin] = useState<DragOrigin | null>(null);
  const [atMin, setAtMin] = useState<number | null>(null);
  const grabbedAtMin = useRef<number | null>(null);
  const live = useRef<Live>({ ...options, origin, atMin, grabbedAtMin: grabbedAtMin.current });
  live.current = { ...options, origin, atMin, grabbedAtMin: grabbedAtMin.current };

  const begin = useCallback((next: DragOrigin) => {
    const at = minuteUnder(next.pointerY, next, live.current);
    grabbedAtMin.current = at;
    setOrigin(next);
    setAtMin(at);
  }, []);

  useEffect(() => {
    if (origin === null) return;

    const onMove = (event: PointerEvent): void => {
      setAtMin(minuteUnder(event.clientY, live.current.origin, live.current));
    };
    const onUp = (): void => {
      const settled = live.current;
      setOrigin(null);
      setAtMin(null);
      const drop = dropOf(settled);
      if (drop !== null) settled.onDrop?.(drop);
    };
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      /* Cancelled with no request, and the keystroke is consumed: Escape also clears the selection, and one press
       * means one thing. */
      event.preventDefault();
      event.stopImmediatePropagation();
      setOrigin(null);
      setAtMin(null);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onKeyDown, CAPTURE);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("keydown", onKeyDown, CAPTURE);
    };
  }, [origin]);

  return {
    isDragging: origin !== null,
    insertion: origin === null || atMin === null ? null : { date: origin.date, atMin },
    begin,
  };
}

const CAPTURE = { capture: true } as const;

/** What a release states, or null where it states nothing a request should be made about. */
function dropOf(live: Live): BlockDrop | null {
  const { origin, atMin, grabbedAtMin } = live;
  if (origin === null || atMin === null) return null;
  /* A click, a jitter, or a drag that came back to where it started: no new placement has been stated. */
  if (atMin === grabbedAtMin) return null;
  if (atMin === origin.fromMin) return null;
  return {
    blockId: origin.blockId,
    date: origin.date,
    atMin,
    startMs: origin.dayStartMs + atMin * MILLISECONDS_IN_MINUTE,
  };
}

/**
 * The quarter hour under a pointer, or null where the pointer is outside the column the drag started in.
 *
 * THE SNAP IS COMPUTED HERE RATHER THAN THROUGH `snapMinutes`, which floors at zero. A column's minute offset may be
 * negative: a frame occurrence beginning at 23:00 on Sunday is a block of Monday's column, so Monday's axis starts
 * before Monday did, and flooring would refuse every quarter hour above the day's own start.
 */
function minuteUnder(clientY: number, origin: DragOrigin | null, live: Live): number | null {
  if (origin === null || origin.canvas === null) return null;
  const box = origin.canvas.getBoundingClientRect();
  if (clientY < box.top || clientY > box.bottom) return null;
  const minutes = live.extent.startMin + (clientY - box.top) / live.pxPerMin;
  return Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES;
}
