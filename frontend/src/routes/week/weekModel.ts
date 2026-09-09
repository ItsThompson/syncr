/* THE SEVEN COLUMNS, CUT FROM ONE WEEK'S INSTANTS.
 *
 * The wire sends instants and the grid draws columns, and this is where one becomes the other. Three rules do
 * all the work.
 *
 * A COLUMN'S OWN START IS AN INSTANT, RESOLVED IN THE ZONE IN FORCE ON ITS DATE. Every offset the grid then
 * works in is a subtraction between two instants, so a local day across a spring-forward transition is 1380
 * minutes and one across a fall-back transition is 1500, with no special case and no assumed 1440. On a zone
 * whose transition falls at local midnight there is no 00:00 at all, and `zonedInstant` answers with the first
 * instant that date does have, which is the day's real start.
 *
 * THE DECLARED DAY BOUNDS ARE RESOLVED PER COLUMN AND THEN UNIONED, for the same reason: 22:00 sits 1320
 * minutes into an ordinary day, 1260 into a spring-forward one and 1380 into a fall-back one. One axis serves
 * seven columns, so it takes the widest reading of the bounds rather than one column's.
 *
 * A SPAN CROSSING MIDNIGHT IS CUT AT THE COLUMN BOUNDARY, ONE PIECE PER COLUMN IT TOUCHES, and no piece is ever
 * dropped or shortened. `docs/design/scratch/block-states.html` renders the circadian frame this way, as spans
 * per day rather than one span across two. Drawing the whole span in the column its start falls in makes a
 * nightly Sleep occurrence widen the axis to 31 hours for all seven columns, which is a real cost paid by every
 * week for one block.
 *
 * THE ONE PIECE THAT IS NOT CUT is the tail reaching past the LAST column. A Sunday-night frame occurrence
 * belongs to the week its start falls in and ends inside the next one, so its final hours have no column of
 * their own; they are drawn past Sunday's day end and the extent expands to hold them. That is the axis rule
 * obeyed rather than excepted: nothing is hidden, and the cost is visible. */

import { zonedInstant } from "../../lib/zonedInstant";
import { extentOf, offsetSpanOf, totalMinutes } from "../../ui/domain";
import type { Extent, GridBand, GridBlock, OffsetSpan, WeekDay } from "../../ui/domain";
import type { WeekBand } from "./bands";
import type { WeekBlock } from "./blocks";
import { staleDayMark } from "./notices";

const MILLISECONDS_IN_MINUTE = 60_000;

/** A half-open run of instants, which is the one shape everything here is cut against. */
interface Instants {
  readonly startMs: number;
  readonly endMs: number;
}

/** One day column before anything is placed in it: its date, its zone, and the instants it spans. */
interface Column extends Instants {
  readonly date: string;
  readonly zone: string;
}

/** The axis default, in wall minutes since midnight. Never a crop: the axis expands past it. */
export interface DayBounds {
  /** From `settings.dayStart`. */
  readonly startMin: number;
  /** From `settings.dayEnd`. At or before the start it means the end of the local day. */
  readonly endMin: number;
}

export interface WeekModel {
  readonly days: readonly WeekDay[];
  readonly extent: Extent;
}

export interface WeekModelInput {
  /** The week's zone map, keyed by ISO date. Seven entries, and the grid draws one column each. */
  readonly zoneByDate: Readonly<Record<string, string>>;
  /** The week's own span end, which is where the last column ends, so the seventh day needs no eighth key. */
  readonly spanEnd: string;
  readonly bounds: DayBounds;
  readonly blocks: readonly WeekBlock[];
  readonly bands: readonly WeekBand[];
}

/** The columns, what each holds, and the axis window all seven share. */
export function weekModel(input: WeekModelInput): WeekModel {
  const columns = columnsOf(input.zoneByDate, input.spanEnd);
  const spans: OffsetSpan[] = [];

  const days: WeekDay[] = columns.map((column, index) => {
    const isLast = index === columns.length - 1;
    const blocks: GridBlock[] = [];
    const bands: GridBand[] = [];
    const staleSourceIds = new Set<string>();

    for (const block of input.blocks) {
      const span = pieceIn(block, column, isLast);
      if (span === null) continue;
      const { staleSourceId, ...gridBlock } = block;
      blocks.push({ ...gridBlock, span });
      if (staleSourceId !== null) staleSourceIds.add(staleSourceId);
      spans.push(span);
    }
    for (const band of input.bands) {
      const span = pieceIn(band, column, isLast);
      if (span === null) continue;
      bands.push({ id: band.id, label: band.label, reason: band.reason, span });
      spans.push(span);
    }

    return {
      date: column.date,
      zone: column.zone,
      startMs: column.startMs,
      minutes: totalMinutes(column),
      blocks,
      bands,
      marks: [...staleSourceIds].map((sourceId) => staleDayMark(column.date, sourceId)),
    };
  });

  return { days, extent: extentOf(boundsExtent(input.bounds, columns), spans) };
}

/** The declared bounds as offsets, read in each column's own zone and widened to hold every reading. */
function boundsExtent(bounds: DayBounds, columns: readonly Column[]): Extent {
  const readings = columns.map((column) => ({
    startMin: wallOffsetMin(bounds.startMin, column),
    endMin:
      bounds.endMin > bounds.startMin ? wallOffsetMin(bounds.endMin, column) : totalMinutes(column),
  }));
  return extentOf(readings[0] ?? { startMin: 0, endMin: 0 }, readings);
}

/** How far into a column a wall time falls, from instants, so a transition inside the day is in the figure. */
function wallOffsetMin(wallMinutes: number, column: Column): number {
  const resolved = zonedInstant({ date: column.date, minutes: wallMinutes, zone: column.zone });
  if (resolved === null) return wallMinutes;
  return (Date.parse(resolved.instant) - column.startMs) / MILLISECONDS_IN_MINUTE;
}

/** The piece of a span that belongs in a column, or null when the span does not reach it. */
function pieceIn(span: Instants, column: Column, isLastColumn: boolean): OffsetSpan | null {
  /* Half-open at both ends, with one exception: a zero-length span sits AT an instant rather than covering one,
   * so it belongs to the column holding that instant instead of to none of them. */
  const reaches =
    span.endMs === span.startMs
      ? span.startMs >= column.startMs && span.startMs < column.endMs
      : span.startMs < column.endMs && span.endMs > column.startMs;
  if (!reaches) return null;

  return offsetSpanOf(
    {
      startMs: Math.max(span.startMs, column.startMs),
      endMs: isLastColumn ? span.endMs : Math.min(span.endMs, column.endMs),
    },
    column.startMs,
  );
}

/** The columns, earliest first, each starting at the instant its own local date does. */
function columnsOf(zoneByDate: Readonly<Record<string, string>>, spanEnd: string): Column[] {
  const starts = Object.entries(zoneByDate)
    .flatMap(([date, zone]) => {
      const resolved = zonedInstant({ date, minutes: 0, zone });
      const startMs = resolved === null ? Number.NaN : Date.parse(resolved.instant);
      return Number.isNaN(startMs) ? [] : [{ date, zone, startMs }];
    })
    .toSorted((left, right) => left.startMs - right.startMs);

  /* A column ends where the next one begins, and the LAST one ends where the week does: the seventh date needs no
   * eighth key, and taking the week's own span end is what makes a 167 or 169 hour week come out of the arithmetic
   * rather than out of an assumption about the seventh day's length. */
  const endOfWeekMs = Date.parse(spanEnd);
  const columns: Column[] = [];
  for (const [index, start] of starts.entries()) {
    columns.push({
      date: start.date,
      zone: start.zone,
      startMs: start.startMs,
      endMs: starts[index + 1]?.startMs ?? endOfWeekMs,
    });
  }
  return columns;
}
