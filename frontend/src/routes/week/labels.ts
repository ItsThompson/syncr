/* THE COLUMN HEADERS AND THE WEEK'S OWN RANGE, in the words a reader reads them in.
 *
 * A header is an uppercase weekday and a day of the month, `MON 09`, which is what fits a 134px column: a full
 * weekday name does not, and an initial alone repeats twice in a week. The initials the calendar already uses are
 * not reused here for that reason: a column header has room for three letters and a date grid does not.
 *
 * THE DATE IS READ FROM THE ISO DATE RATHER THAN FROM AN INSTANT, because a column IS a local date: reading its
 * start instant in the browser's own zone would label a Monday column `SUN` for every reader east of the plan. */

import { parseIsoDate, WEEKDAY_NAMES } from "../../ui/primitives";

/** Monday first, matching the ISO weekday the domain counts in. */
const SHORT_WEEKDAYS = WEEKDAY_NAMES.map((name) => name.slice(0, 3).toUpperCase());

const DAYS_IN_WEEK = 7;

/** `MON 09` for `2026-02-09`, or the date itself when it is not one. */
export function columnLabel(isoDate: string): string {
  const parsed = parseIsoDate(isoDate);
  if (parsed === null) return isoDate;
  const at = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day));
  /* `getUTCDay` puts Sunday at 0 and the ISO week starts on Monday, so the index shifts by one. */
  const weekday = SHORT_WEEKDAYS[(at.getUTCDay() + DAYS_IN_WEEK - 1) % DAYS_IN_WEEK];
  return `${weekday} ${String(parsed.day).padStart(2, "0")}`;
}

/** `9 Feb to 15 Feb` for a week's first and last dates, or an empty string for no dates at all. */
export function weekRange(dates: readonly string[]): string {
  const first = dates.at(0);
  const last = dates.at(-1);
  if (first === undefined || last === undefined) return "";
  return `${monthDay(first)} to ${monthDay(last)}`;
}

function monthDay(isoDate: string): string {
  const parsed = parseIsoDate(isoDate);
  if (parsed === null) return isoDate;
  const at = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day));
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(at);
}
