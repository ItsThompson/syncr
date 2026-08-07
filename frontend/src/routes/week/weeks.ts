/* THE WEEK BEFORE AND THE WEEK AFTER, FROM AN ISO WEEK IDENTIFIER.
 *
 * `[` AND `]` MOVE BY A WEEK, so the arithmetic has to be over weeks rather than over the identifier's text. An ISO
 * year is not a calendar year: `2026-W53` is followed by `2027-W01`, and `2020-W01` is preceded by `2019-W52` on some
 * years and `2019-W53` on others, so incrementing the number and reusing the year is wrong at both ends of a year.
 *
 * The step therefore goes through a DATE: the Monday of the week, seven days either way, and the ISO week that date
 * belongs to. That reuses the one derivation this frontend already has, in `routes/today/isoWeek.ts`, rather than
 * inventing a second one that would have to be right about the same three days at each end of a year. */

import { isoWeekOf } from "../today/isoWeek";

const MS_IN_DAY = 24 * 60 * 60 * 1000;
const DAYS_IN_WEEK = 7;

/** The Monday of an ISO week, as a `YYYY-MM-DD` date, or null where the text names no week. */
export function mondayOf(isoWeek: string): string | null {
  const match = /^(\d{4})-W(\d{2})$/.exec(isoWeek.trim());
  if (match === null) return null;
  const year = Number(match[1]);
  const week = Number(match[2]);
  if (week < 1 || week > 53) return null;

  /* 4 January is in week 1 by definition, so the Monday of week 1 is the Monday of the week holding it. */
  const fourth = new Date(Date.UTC(year, 0, 4));
  const weekday = fourth.getUTCDay() === 0 ? DAYS_IN_WEEK : fourth.getUTCDay();
  const firstMonday = fourth.getTime() - (weekday - 1) * MS_IN_DAY;
  const monday = new Date(firstMonday + (week - 1) * DAYS_IN_WEEK * MS_IN_DAY);
  return isoDateOf(monday);
}

/** The ISO week `steps` weeks away, or the one given where the text names no week. */
export function weekAway(isoWeek: string, steps: number): string {
  const monday = mondayOf(isoWeek);
  if (monday === null) return isoWeek;
  const parts = monday.split("-").map(Number);
  const at = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + steps * DAYS_IN_WEEK));
  return isoWeekOf(isoDateOf(at)) ?? isoWeek;
}

function isoDateOf(at: Date): string {
  const month = String(at.getUTCMonth() + 1).padStart(2, "0");
  const day = String(at.getUTCDate()).padStart(2, "0");
  return `${String(at.getUTCFullYear())}-${month}-${day}`;
}
