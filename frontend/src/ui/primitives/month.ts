/* The month grid, as date arithmetic rather than as a rendering.
 *
 * A weekday cannot be wrong if it is computed, which is why `docs/design/components.html` derives its own
 * calendar from real dates rather than laying out a plausible February. The same reasoning applies to the
 * kit: this module is pure, so every boundary case is a literal in a test rather than a thing to squint at.
 *
 * DATES HERE ARE CALENDAR DATES, NOT INSTANTS. A deadline is a day in the user's own zone, so the value is
 * `YYYY-MM-DD` and nothing in this module touches a clock or a zone. `toISOString` is deliberately unused:
 * it converts to UTC, so a local midnight in a positive offset comes back as the previous day. */

export interface CalendarDay {
  /** `YYYY-MM-DD`. */
  readonly iso: string;
  readonly dayOfMonth: number;
  /** True for the leading and trailing days that belong to a neighbouring month. */
  readonly isOutsideMonth: boolean;
}

export interface CalendarMonth {
  readonly year: number;
  /** 1 to 12, so a month is written as a reader would say it. */
  readonly month: number;
}

const DAYS_IN_WEEK = 7;

/** Monday-first, matching the ISO week the whole product is built on. */
export const WEEKDAY_INITIALS = ["M", "T", "W", "T", "F", "S", "S"] as const;

/* Two initials repeat, so a column header carries the full name in `abbr` for a screen reader. */
export const WEEKDAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

export function formatIsoDate(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** The calendar date a `YYYY-MM-DD` string names, or null when it names none. */
export function parseIsoDate(text: string): (CalendarMonth & { readonly day: number }) | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text.trim());
  if (match === null) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1) return null;
  if (day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

export function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

/** The month `offset` months from this one, carrying the year over. */
export function shiftMonth(from: CalendarMonth, offset: number): CalendarMonth {
  const zeroBased = from.month - 1 + offset;
  const year = from.year + Math.floor(zeroBased / 12);
  return { year, month: (((zeroBased % 12) + 12) % 12) + 1 };
}

/** The calendar date `offset` days from an ISO date, or null when the input is not one. */
export function shiftDate(iso: string, offset: number): string | null {
  const parsed = parseIsoDate(iso);
  if (parsed === null) return null;
  const moved = new Date(parsed.year, parsed.month - 1, parsed.day + offset);
  return formatIsoDate(moved.getFullYear(), moved.getMonth() + 1, moved.getDate());
}

/** How the month reads in a header: `February 2025`. */
export function monthLabel(month: CalendarMonth): string {
  const formatter = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });
  return formatter.format(new Date(month.year, month.month - 1, 1));
}

/**
 * How a day reads to a screen reader: `Wednesday, 19 February 2025`.
 *
 * The cell's visible text is the day of the month alone, which says nothing on its own out of the grid's
 * visual context, and an ISO string read aloud is a run of digits. The weekday is included because
 * choosing a deadline is usually a question about which weekday it lands on.
 */
export function dayLabel(iso: string): string {
  const parsed = parseIsoDate(iso);
  if (parsed === null) return iso;
  const formatter = new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  return formatter.format(new Date(parsed.year, parsed.month - 1, parsed.day));
}

/**
 * The weeks a month is drawn as, Monday first, each a full seven days.
 *
 * The leading and trailing days belong to the neighbouring months and are marked, because a grid that
 * skipped them would put the first of the month under the wrong weekday.
 */
export function monthGrid(month: CalendarMonth): readonly (readonly CalendarDay[])[] {
  const first = new Date(month.year, month.month - 1, 1);
  // getDay() is Sunday-first, so Monday becomes 0 and Sunday becomes 6.
  const lead = (first.getDay() + 6) % DAYS_IN_WEEK;
  const total = lead + daysInMonth(month.year, month.month);
  const weekCount = Math.ceil(total / DAYS_IN_WEEK);

  const weeks: CalendarDay[][] = [];
  for (let week = 0; week < weekCount; week += 1) {
    const days: CalendarDay[] = [];
    for (let weekday = 0; weekday < DAYS_IN_WEEK; weekday += 1) {
      const date = new Date(month.year, month.month - 1, 1 - lead + week * DAYS_IN_WEEK + weekday);
      days.push({
        iso: formatIsoDate(date.getFullYear(), date.getMonth() + 1, date.getDate()),
        dayOfMonth: date.getDate(),
        isOutsideMonth: date.getMonth() !== month.month - 1,
      });
    }
    weeks.push(days);
  }
  return weeks;
}
