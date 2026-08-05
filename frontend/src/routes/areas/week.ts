/* Which ISO week a date falls in, spelled the way the api reads it.
 *
 * `2026-W07`. Derived from the calendar rather than read from the server: which week today is in is a fact
 * about the date, and a route that answered it would be a read whose only output the client already has.
 *
 * THE ISO YEAR IS NOT THE CALENDAR YEAR, and that is the whole reason this is a function rather than a
 * template string. 1 January 2027 is in `2026-W53` and 31 December 2025 is in `2026-W01`, so neither the week
 * number nor the year can be taken from the date directly. The rule is the standard's: week 1 is the week
 * holding the first Thursday, so the ISO year is the year of the Thursday in the same week as the date.
 *
 * THE DATE IS THE CALLER'S, so a test names one rather than depending on when it runs, and the screen passes
 * the reader's own `new Date()`. */

const DAYS_PER_WEEK = 7;
const THURSDAY = 4;
const MILLISECONDS_PER_DAY = 86_400_000;

/** The ISO week `on` falls in, as `2026-W07`. */
export function thisIsoWeek(on: Date): string {
  /* Local wall time is what the reader means by "today", and the arithmetic below is on dates rather than
   * instants, so the parts are read locally and rebuilt as UTC. Rebuilding in UTC is what stops a day's
   * length mattering: every step from here is a whole number of days. */
  const date = Date.UTC(on.getFullYear(), on.getMonth(), on.getDate());
  const thursday = new Date(date);
  /* getUTCDay is 0 for Sunday, so the ISO weekday is 7 for it. Moving to the Thursday of the same week is
   * what names the ISO year: a week belongs to the year holding its Thursday. */
  const isoWeekday = thursday.getUTCDay() || DAYS_PER_WEEK;
  thursday.setUTCDate(thursday.getUTCDate() + THURSDAY - isoWeekday);

  const firstThursday = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 4));
  const firstIsoWeekday = firstThursday.getUTCDay() || DAYS_PER_WEEK;
  firstThursday.setUTCDate(firstThursday.getUTCDate() + THURSDAY - firstIsoWeekday);

  const weeks =
    Math.round(
      (thursday.getTime() - firstThursday.getTime()) / MILLISECONDS_PER_DAY / DAYS_PER_WEEK,
    ) + 1;
  return `${thursday.getUTCFullYear()}-W${String(weeks).padStart(2, "0")}`;
}
