/* THE WEEK GRID. Seven proportional columns and one axis, and the geometry every one of them is drawn from.
 *
 * PIXELS PER MINUTE AND THE ZOOM CLAMP BOTH COME FROM THE SAME MEASURED HEIGHT, and they have to. The grid observes
 * its own height and subtracts the day header, because the figure the arithmetic wants is the canvas the blocks are
 * drawn in: the reference figure, 626px on a 13 inch display, is a 790px viewport less the page band, the summary
 * strip and that header. The CLAMP IS APPLIED HERE rather than by the caller for the same reason: a caller has no
 * measurement, so clamping above this component would cap every display at the reference display's own cap. On a 27
 * inch display that renders a stored 24 as 16, and on a window shorter than the reference it offers a level at which
 * the modal thirty-minute block loses its title, which is the one thing the clamp exists to prevent.
 *
 * NO VIRTUALIZATION. Roughly 210 absolutely positioned blocks across seven columns sits well inside a frame
 * budget, and virtualizing a surface with no scroll-driven mount would add complexity for nothing.
 *
 * THE GRID ABSORBS SURPLUS WIDTH and the columns share it equally, because a title in a single-line tier cannot
 * wrap and the grid is the only column that cannot absorb a squeeze. Below --bp-compact it scrolls horizontally at
 * --col-min per day with the axis sticky, which arrives as `max-narrow:` utilities: those compile from the theme's
 * own mirror of --bp-compact, so the threshold is stated once in the whole frontend rather than a third time here.
 *
 * ONE REDRAW, NEVER A SETTLE. A zoom change or a re-solve replaces the props and the grid renders once. There is
 * no transition, here or anywhere: motion is zero, without exception.
 *
 * INTERACTION ARRIVES AS ONE PROP AND SELECTION IS NOT HELD HERE. Every state a block can be in is a prop, so a
 * read-only render passes none of them and this component remembers nothing about what the reader has chosen. The
 * one exception is the DRAG, and it is not an exception to that rule: what the drag holds is a marker position, and
 * only this component can turn a pointer position into a quarter hour, because only it knows pixels per minute. */

import { useRef } from "react";

import { canvasHeightPx, gridHeightPx, pxPerMinute } from "./geometry";
import { DAY_HEADER_H_PX } from "./metrics";
import { useObservedHeight } from "./useObservedHeight";
import { useDiscreteDrag, type BlockDrop } from "./useDiscreteDrag";
import { clampVisibleHours } from "./zoom";
import { DayColumn, type ColumnInteraction } from "./DayColumn";
import { TimeAxis } from "./TimeAxis";
import type { Extent, WeekDay } from "./types";
import "./grid.css";

/** What the grid needs from whatever owns interaction. Absent leaves the grid read-only, which is a real state. */
export interface GridInteraction extends Omit<ColumnInteraction, "onDragBegin"> {
  /**
   * A drop that states a placement, once, on release.
   *
   * The grid owns the pointer mechanics because it owns the geometry: only it can turn a pointer position into a
   * quarter hour. What it hands back is an instant, so a caller sends it without re-deriving a wall time.
   */
  readonly onDrop?: ((drop: BlockDrop) => void) | undefined;
}

export interface WeekGridProps {
  readonly days: readonly WeekDay[];
  readonly extent: Extent;
  /** The visible-hours setting as the reader stored it. Brought inside this display's own range here. */
  readonly visibleHours: number;
  /** What each column's header says, in the same order as `days`. */
  readonly labels: readonly string[];
  /** Now, as an instant, so each column decides for itself whether the rule falls inside it. */
  readonly nowMs: number | null;
  readonly interaction?: GridInteraction | undefined;
}

const MILLISECONDS_IN_MINUTE = 60_000;
const NO_INTERACTION: GridInteraction = {};

export function WeekGrid({
  days,
  extent,
  visibleHours,
  labels,
  nowMs,
  interaction = NO_INTERACTION,
}: WeekGridProps) {
  const viewport = useRef<HTMLDivElement>(null);
  /* Named for what it IS rather than for where it came from: the measurement OR the reference display's height where
   * nothing has been laid out. In the one component whose fix was about not confusing a constant with a measurement,
   * calling this `measuredHeightPx` would be the same conflation one identifier over. */
  const gridPx = gridHeightPx(useObservedHeight(viewport) - DAY_HEADER_H_PX);
  const hours = clampVisibleHours(visibleHours, gridPx);
  const pxPerMin = pxPerMinute(gridPx, hours);
  const canvasPx = canvasHeightPx(extent, pxPerMin);
  const drag = useDiscreteDrag({ extent, pxPerMin, onDrop: interaction.onDrop });

  return (
    <div
      className="week-grid max-narrow:overflow-x-auto"
      data-dragging={drag.isDragging ? "" : undefined}
      ref={viewport}
    >
      <TimeAxis
        canvasHeightPx={canvasPx}
        extent={extent}
        nowMin={nowOffsetIn(days, nowMs)}
        pxPerMin={pxPerMin}
      />
      <div className="week-grid__days">
        {days.map((day, index) => (
          <DayColumn
            canvasHeightPx={canvasPx}
            day={day}
            extent={extent}
            insertionMin={drag.insertion?.date === day.date ? drag.insertion.atMin : null}
            interaction={{ ...interaction, onDragBegin: drag.begin }}
            key={day.date}
            label={labels[index] ?? day.date}
            nowMin={nowOffsetIn([day], nowMs)}
            pxPerMin={pxPerMin}
          />
        ))}
      </div>
    </div>
  );
}

/** Where now falls in the first column that contains it, in that column's own minutes, or null. */
function nowOffsetIn(days: readonly WeekDay[], nowMs: number | null): number | null {
  if (nowMs === null) return null;
  for (const day of days) {
    const offset = (nowMs - day.startMs) / MILLISECONDS_IN_MINUTE;
    if (offset >= 0 && offset < day.minutes) return offset;
  }
  return null;
}
