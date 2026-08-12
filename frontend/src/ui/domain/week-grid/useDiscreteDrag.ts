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
 * A RELEASE STATES A PLACEMENT ONLY AFTER THE POINTER HAS TRAVELLED ONE SNAP STEP, and that threshold is the whole
 * of "a drop on the same quarter hour is a no-op". It is measured in PIXELS, not in quarters, and the difference is
 * the defect it exists to close: a rounded quarter flips on the smallest movement across a rounding midpoint, so
 * comparing quarters suppressed only a release that had not moved at all. Pressing one pixel below the 09:00/09:15
 * midpoint and releasing one pixel lower posted a pin at 09:15 for a block at 09:00, and over a 90-minute block with
 * an ordinary three-pixel trackpad slop, six of seventy-five press positions wrote one, at starts up to a full block
 * height away.
 *
 * BELOW THE FLOOR THE HAIRLINE STATES THE QUARTER THE BLOCK ALREADY HOLDS, not the one under the cursor. The marker
 * exists to say what the release will do, so for the twelve pixels before the floor is crossed it has to say "nothing
 * moves": a marker at 09:15 over a release that states 09:00 is the two halves of one rule disagreeing.
 *
 * THAT MATTERS BECAUSE A CLICK IS THE SELECTION GESTURE. `onClick` and `onPointerDown` are on the same element, so
 * without the threshold the primary way a reader selects a block moves it, and a pin is a hard constraint the solver
 * then honours AND a training label the learning layer fits against. One snap step is the smallest distance that can
 * mean a placement at all.
 *
 * THE POINTER IS READ AGAINST THE COLUMN IT PRESSED IN, ON BOTH AXES. A release outside that box states no placement
 * and cancels, rather than being clamped to an edge nobody aimed at. The horizontal pair is not symmetry for its own
 * sake: without it a drag over the NEXT column was read against the starting one, so dragging Monday's block over
 * Tuesday at 13:00 pinned it to MONDAY at 13:00 -- a placement the reader never stated, in a column they had left.
 *
 * SO THE DRAG HAS ONE DEGREE OF FREEDOM, THE MINUTE, AND THAT IS A DECISION RATHER THAN A MISSING FEATURE. A pointer
 * over another column does not retarget, and no drag reaches another week, because none leaves the column it began
 * in. `docs/DESIGN-LANGUAGE.md` § Keyboard settles it: `Shift+↑` and `Shift+↓` are glossed "move by 15 minutes and
 * pin. the keyboard equivalent of the drag", and the table lists no horizontal pair, so the gesture the document
 * calls this drag's equivalent cannot change days either. `h` and `l` move the SELECTION between columns and move no
 * block. § The week grid carries the refusal and the two questions that follow from it, so a reader of that document
 * does not have to infer the rule from this file.
 *
 * THE POINTER IS CAPTURED, so a release anywhere reaches this drag. Without capture a mouse released outside the
 * viewport delivers no `pointerup` to the page at all: the drag stayed live, the marker stayed drawn, and the next
 * release posted a pin at whatever quarter the cursor then held. `pointercancel` is a cancel for the same reason:
 * the platform has taken the pointer away, so no placement was stated.
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
  /** The block's own start, in the column's minutes, which a release that lands back on it is compared against. */
  readonly fromMin: number;
  /** The instant the column's local day began, which every offset here is measured from. */
  readonly dayStartMs: number;
  /** The column's canvas, whose box turns a pointer position into a minute and bounds both axes. */
  readonly canvas: HTMLElement | null;
  readonly pointerX: number;
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
  /** Called once, on a release that states a placement: see the header for the two ways one does not. */
  readonly onDrop?: ((drop: BlockDrop) => void) | undefined;
}

export interface DiscreteDrag {
  /** True while a drag is in progress, which is what steps the quarter lines up. */
  readonly isDragging: boolean;
  /** Where the hairline sits, or null while the pointer states no target. */
  readonly insertion: InsertionAt | null;
  readonly begin: (origin: DragOrigin) => void;
}

/** A pointer position read against the origin column: the quarter it names, and the pixel it was read at. */
interface Point {
  readonly min: number;
  readonly y: number;
}

/** What the whole drag is decided from, held in a ref so the window listeners attach once per drag. */
interface Live extends DiscreteDragOptions {
  readonly origin: DragOrigin | null;
  /** Where the pointer went down, which is what the travel is measured from and what the marker states below it. */
  readonly grabbed: Point | null;
  /** Where the pointer was last seen. A release carries no position of its own here. */
  readonly at: Point | null;
}

/** How far a pointer must travel before a release may state a placement: one snap step, in pixels. */
export function travelFloorPx(pxPerMin: number): number {
  return SNAP_MINUTES * pxPerMin;
}

export function useDiscreteDrag(options: DiscreteDragOptions): DiscreteDrag {
  const [origin, setOrigin] = useState<DragOrigin | null>(null);
  const [at, setAt] = useState<Point | null>(null);
  const grabbed = useRef<Point | null>(null);
  const live = useRef<Live>({ ...options, origin, grabbed: null, at: null });
  live.current = { ...options, origin, grabbed: grabbed.current, at };

  const begin = useCallback((next: DragOrigin) => {
    const from = pointAt(next.pointerX, next.pointerY, next, live.current);
    grabbed.current = from;
    setOrigin(next);
    setAt(from);
  }, []);

  useEffect(() => {
    if (origin === null) return;

    const clear = (): void => {
      setOrigin(null);
      setAt(null);
      grabbed.current = null;
    };
    const onMove = (event: PointerEvent): void => {
      setAt(pointAt(event.clientX, event.clientY, live.current.origin, live.current));
    };
    const onUp = (): void => {
      const settled = live.current;
      clear();
      const drop = dropOf(settled);
      if (drop !== null) settled.onDrop?.(drop);
    };
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      /* Cancelled with no request, and the keystroke is consumed: Escape also clears the selection, and one press
       * means one thing. */
      event.preventDefault();
      event.stopImmediatePropagation();
      clear();
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    /* The platform took the pointer away, so nothing was stated. Both events are listened for because a browser
     * sends `pointercancel` and a capture loss sends `lostpointercapture`, and either one ends this drag. Neither is
     * dispatched by jsdom, so the ordering the spec states -- `lostpointercapture` AFTER `pointerup`, which is what
     * makes it a no-op on a real drop -- rests on the specification rather than on a test here. */
    window.addEventListener("pointercancel", clear);
    window.addEventListener("lostpointercapture", clear);
    window.addEventListener("keydown", onKeyDown, CAPTURE);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", clear);
      window.removeEventListener("lostpointercapture", clear);
      window.removeEventListener("keydown", onKeyDown, CAPTURE);
    };
  }, [origin]);

  return {
    isDragging: origin !== null,
    insertion: insertionOf(live.current),
    begin,
  };
}

const CAPTURE = { capture: true } as const;

/**
 * Where the hairline sits, which is what the release WILL state rather than what the cursor is over.
 *
 * Below the travel floor a release states nothing, so the marker names the quarter the block already holds: the
 * marker's whole job is to say what a release will do, and one at 09:15 over a release that keeps 09:00 is the two
 * halves of one rule disagreeing.
 */
function insertionOf(live: Live): InsertionAt | null {
  const { origin, at, grabbed } = live;
  if (origin === null || at === null || grabbed === null) return null;
  const isBelowFloor = Math.abs(at.y - grabbed.y) < travelFloorPx(live.pxPerMin);
  return { date: origin.date, atMin: isBelowFloor ? grabbed.min : at.min };
}

/** What a release states, or null where it states nothing a request should be made about. */
function dropOf(live: Live): BlockDrop | null {
  const { origin, at, grabbed } = live;
  if (origin === null || at === null || grabbed === null) return null;
  /* A click, a jitter, or a drag that came back inside one snap step of where it started: no placement is stated. */
  if (Math.abs(at.y - grabbed.y) < travelFloorPx(live.pxPerMin)) return null;
  /* A release that lands the block back on its own start states nothing either. */
  if (at.min === origin.fromMin) return null;
  return {
    blockId: origin.blockId,
    date: origin.date,
    atMin: at.min,
    startMs: origin.dayStartMs + at.min * MILLISECONDS_IN_MINUTE,
  };
}

/**
 * The quarter hour under a pointer and the pixel it was read at, or null outside the column the drag started in.
 *
 * BOTH AXES ARE BOUNDED BY THE SAME BOX. A pointer outside it vertically is over no quarter at all; one outside it
 * horizontally is over ANOTHER COLUMN, and reading that position against the starting column produced a placement in
 * a day the reader had left. A pointer over another column states nothing here rather than retargeting, which is the
 * decision the header states.
 *
 * THE SNAP IS COMPUTED HERE RATHER THAN THROUGH `snapMinutes`, which floors at zero. A column's minute offset may be
 * negative: a frame occurrence beginning at 23:00 on Sunday is a block of Monday's column, so Monday's axis starts
 * before Monday did, and flooring would refuse every quarter hour above the day's own start.
 *
 * EXPORTED FOR THE RENDERED-PIXEL GATE, because the horizontal bound cannot be observed anywhere else. jsdom lays
 * nothing out, so a test gives the canvas a box and gives every canvas the SAME box, which puts a position "over the
 * next column" inside the origin column as well. `scripts/check-render` compiles this function into a page that lays
 * out seven real day columns and asks it what a position over one of them names against the box of the one beside it.
 */
export function pointAt(
  clientX: number,
  clientY: number,
  origin: DragOrigin | null,
  live: Live,
): Point | null {
  if (origin === null || origin.canvas === null) return null;
  const box = origin.canvas.getBoundingClientRect();
  if (clientY < box.top || clientY > box.bottom) return null;
  if (clientX < box.left || clientX > box.right) return null;
  const minutes = live.extent.startMin + (clientY - box.top) / live.pxPerMin;
  return { min: Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES, y: clientY };
}
