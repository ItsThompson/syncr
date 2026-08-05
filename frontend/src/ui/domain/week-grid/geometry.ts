/* GEOMETRY DERIVATION. Pixels per minute is DERIVED, not fixed, and the axis never lies.
 *
 *   extent        = union( the declared day bounds, the bounding span of every block in the visible week )
 *   px_per_min    = measured grid height / (visible hours * 60)
 *   canvas_height = extent minutes * px_per_min
 *   block_top     = (block start - extent start) * px_per_min
 *   block_height  = block duration * px_per_min
 *
 * TWO RULES DRIVE EVERY LINE BELOW.
 *
 * The axis ALWAYS expands to contain every block in the visible week, and the day bounds set a DEFAULT extent
 * rather than a crop. A block the axis hides is a scheduling error the reader cannot see, so there is no path
 * here that drops a span or clamps one.
 *
 * Height is proportional to duration at every zoom level. Where a block is too short for its title the BLOCK
 * degrades, in `tiers.ts`, and the axis is untouched. Nothing here has a floor on a height. */

import { GRID_H_PX, VISIBLE_HOURS_DEFAULT } from "./metrics";
import type { Extent, Instants, OffsetSpan } from "./types";

const MILLISECONDS_IN_MINUTE = 60_000;
const MINUTES_IN_HOUR = 60;

/**
 * How many minutes an interval of instants holds.
 *
 * FROM INSTANTS, never from an assumed 1440. A local day across a spring-forward transition is 1380 minutes
 * and one across a fall-back transition is 1500, and both come out of this subtraction with no special case,
 * because the hour that does not exist is not in the difference between the two instants.
 */
export function totalMinutes({ startMs, endMs }: Instants): number {
  return (endMs - startMs) / MILLISECONDS_IN_MINUTE;
}

/** Where a span sits in a column whose own axis starts at `startMs`, in minutes. Signed. */
export function offsetSpanOf(span: Instants, columnStartMs: number): OffsetSpan {
  return {
    startMin: (span.startMs - columnStartMs) / MILLISECONDS_IN_MINUTE,
    endMin: (span.endMs - columnStartMs) / MILLISECONDS_IN_MINUTE,
  };
}

/**
 * The axis window: the declared bounds widened by every span given.
 *
 * The bounds are the DEFAULT, so the result contains them even on an empty week, and it contains every span
 * whether or not the bounds do. A span is never dropped and never clamped.
 */
export function extentOf(bounds: Extent, spans: readonly OffsetSpan[]): Extent {
  let startMin = bounds.startMin;
  let endMin = bounds.endMin;
  for (const span of spans) {
    startMin = Math.min(startMin, span.startMin, span.endMin);
    endMin = Math.max(endMin, span.startMin, span.endMin);
  }
  return { startMin, endMin };
}

/**
 * The grid height the arithmetic runs on: the measurement, or the reference display's until one exists.
 *
 * Stated once, because two questions need the same answer: how many pixels a minute is, and which zoom levels this
 * display can offer. Answering them from different heights is how a screen comes to draw a level it also refuses.
 * A measurement of zero is what a first paint and a headless DOM both report.
 */
export function gridHeightPx(measuredHeightPx: number): number {
  return measuredHeightPx > 0 ? measuredHeightPx : GRID_H_PX;
}

/**
 * Pixels per minute, from the grid's MEASURED height and the visible-hours setting.
 *
 * Returning zero on an unmeasured grid would collapse every block in the week and read as a rendering fault rather
 * than as an unmeasured frame, which is why the HEIGHT falls back and the answer does not.
 */
export function pxPerMinute(measuredHeightPx: number, visibleHours: number): number {
  const hours = visibleHours > 0 ? visibleHours : VISIBLE_HOURS_DEFAULT;
  return gridHeightPx(measuredHeightPx) / (hours * MINUTES_IN_HOUR);
}

/** How tall the canvas is, which is the whole extent rather than the visible window. */
export function canvasHeightPx(extent: Extent, pxPerMin: number): number {
  return (extent.endMin - extent.startMin) * pxPerMin;
}

/** Where a span's box sits on a canvas. A zero-length span is a zero-height box, not a hidden one. */
export interface Box {
  readonly topPx: number;
  readonly heightPx: number;
}

export function boxOf(span: OffsetSpan, extent: Extent, pxPerMin: number): Box {
  return {
    topPx: (span.startMin - extent.startMin) * pxPerMin,
    heightPx: (span.endMin - span.startMin) * pxPerMin,
  };
}

/** The minute offsets an hour or quarter line falls on inside an extent, earliest first. */
export function lineOffsets(extent: Extent, everyMinutes: number): number[] {
  if (everyMinutes <= 0) return [];
  const first = Math.ceil(extent.startMin / everyMinutes) * everyMinutes;
  const offsets: number[] = [];
  for (let minute = first; minute <= extent.endMin; minute += everyMinutes) offsets.push(minute);
  return offsets;
}
