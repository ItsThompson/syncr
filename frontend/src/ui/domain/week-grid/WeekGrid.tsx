/* THE WEEK GRID. Seven proportional columns and one axis, and the geometry every one of them is drawn from.
 *
 * PIXELS PER MINUTE IS DERIVED FROM A MEASUREMENT. The grid observes its own height and recomputes, so the axis is
 * proportional to whatever the viewport gives it rather than to an assumed height. The day header is subtracted,
 * because the measurement the arithmetic wants is the canvas the blocks are drawn in: the reference figure, 626px
 * on a 13 inch display, is a 790px viewport less the page band, the summary strip and that header.
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
 * no transition, here or anywhere: motion is zero, without exception. */

import { useRef } from "react";

import { canvasHeightPx, pxPerMinute } from "./geometry";
import { DAY_HEADER_H_PX } from "./metrics";
import { useObservedHeight } from "./useObservedHeight";
import { DayColumn } from "./DayColumn";
import { TimeAxis } from "./TimeAxis";
import type { Extent, WeekDay } from "./types";
import "./grid.css";

export interface WeekGridProps {
  readonly days: readonly WeekDay[];
  readonly extent: Extent;
  /** The visible-hours setting, already brought inside the range this display offers. */
  readonly visibleHours: number;
  /** What each column's header says, in the same order as `days`. */
  readonly labels: readonly string[];
  /** Now, as an instant, so each column decides for itself whether the rule falls inside it. */
  readonly nowMs: number | null;
}

const MILLISECONDS_IN_MINUTE = 60_000;

export function WeekGrid({ days, extent, visibleHours, labels, nowMs }: WeekGridProps) {
  const viewport = useRef<HTMLDivElement>(null);
  const viewportHeightPx = useObservedHeight(viewport);
  const pxPerMin = pxPerMinute(Math.max(0, viewportHeightPx - DAY_HEADER_H_PX), visibleHours);
  const canvasPx = canvasHeightPx(extent, pxPerMin);

  return (
    <div className="week-grid max-narrow:overflow-x-auto" ref={viewport}>
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
