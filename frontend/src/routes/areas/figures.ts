/* How a figure reads on this screen: hours, percentage points, and the share of a denominator.
 *
 * THE DENOMINATOR IS DISCRETIONARY TIME, NEVER SCHEDULED TIME. Measuring against scheduled time would inflate
 * every Area's share by excluding exactly the hours nobody planned, and the report would read as healthy while
 * the gap grew. One function turns a minute count into a share, so the pie's wedge, the legend's figure and the
 * deviation row's point figure cannot come from three different divisions.
 *
 * A SHARE OF NOTHING IS ZERO, NOT A DIVISION BY ZERO. A week off-plan from end to end has no discretionary
 * time, and every category's share of it is nothing.
 *
 * POINTS ARE SPELLED `pp`, NOT `%`. The deviation chart's magnitude is a difference between two percentages,
 * and calling that a percentage would invite a reader to add it to one. */

const MINUTES_PER_HOUR = 60;
const PERCENT = 100;
/** One decimal on an hour figure and on a point figure, which is what the rendered budget sheet draws. */
const PLACES = 1;
/** U+2014 EM DASH, which is how every table in this product spells a cell with nothing in it. */
const NOTHING = "\u2014";

/** A minute count as hours: `18.4h`. */
export function asHours(minutes: number): string {
  return `${(minutes / MINUTES_PER_HOUR).toFixed(PLACES)}h`;
}

/** A magnitude in percentage points: `3.4pp`. Unsigned: the chart carries the sign. */
export function asPoints(points: number): string {
  return `${points.toFixed(PLACES)}pp`;
}

/** A share as a percentage: `35.3%`. */
export function asPercent(share: number): string {
  return `${share.toFixed(PLACES)}%`;
}

/** A whole-number share as the budget authors it: `30%`. */
export function asWholePercent(share: number): string {
  return `${Math.round(share)}%`;
}

/** `minutes` as a share of the discretionary time it was measured against, in percentage points. */
export function shareOf(minutes: number, discretionaryMinutes: number | null): number {
  if (discretionaryMinutes === null || discretionaryMinutes <= 0) return 0;
  return (minutes / discretionaryMinutes) * PERCENT;
}

/** A weekly floor in hours as the sheet reads it: `5h 00m`, or a dash for an Area declaring none. */
export function asFloor(floorHours: number | null): string {
  if (floorHours === null) return NOTHING;
  const minutes = Math.round(floorHours * MINUTES_PER_HOUR);
  const hours = Math.floor(minutes / MINUTES_PER_HOUR);
  return `${hours}h ${String(minutes % MINUTES_PER_HOUR).padStart(2, "0")}m`;
}

/** An ISO week as the trend labels it: `W07`. */
export function asWeekLabel(period: string): string {
  return `W${period.split("-W").at(1) ?? period}`;
}

/**
 * What a reader typed, as the figure the api takes, or null for nothing.
 *
 * NOTHING IS ROUNDED AND NOTHING IS CLAMPED HERE. Every figure this screen authors is stored as
 * `NUMERIC(5, 2)`: the api's own comment says that holds every legal percentage and every legal floor to the
 * hundredth of an hour, and the domain's `floor_minutes` says a floor authored to the hundredth converts
 * deterministically. So a share of 33.5 and a floor of 3.5 are both legal declarations, and a control that
 * snapped either to a grid would write a budget the reader did not author. The api's own bounds refuse a
 * figure out of range, and its 422 names the field.
 *
 * Blank is null rather than zero, because a reader who cleared the box stated nothing rather than none.
 */
export function parseFigure(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const figure = Number(trimmed);
  return Number.isFinite(figure) ? figure : null;
}

/** A figure as the field shows it back: the reader's own text, or empty for nothing declared. */
export function asFieldText(figure: number | null): string {
  return figure === null ? "" : String(figure);
}
