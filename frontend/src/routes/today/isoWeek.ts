/* The ISO week a local date belongs to, as the api spells one.
 *
 * RECORDING AN OUTCOME NAMES THE WEEK, because a block id is a digest of the week and the content it
 * holds, so the week cannot be read back out of the id. The ledger is addressed by date, so the date is
 * the only thing this screen has to derive it from.
 *
 * THE ISO YEAR IS NOT THE CALENDAR YEAR, which is the whole reason this is arithmetic rather than a
 * template string. 1 January 2027 belongs to `2026-W53` and 30 December 2019 to `2020-W01`, so a
 * derivation reading the calendar year off the date is wrong for up to three days at each end of it, and
 * the api answers 422 for a week the block does not belong to.
 *
 * Computed in UTC. A week number is a fact about a calendar date, and building the arithmetic on local
 * instants would put a zone in the middle of it. */

import { parseIsoDate } from "../../ui/primitives";

const MS_IN_DAY = 24 * 60 * 60 * 1000;
const DAYS_IN_WEEK = 7;
/** ISO weekdays run Monday 1 to Sunday 7, and the Thursday of a week decides its number and its year. */
const THURSDAY = 4;

/** The ISO weekday of a UTC date, Monday 1 to Sunday 7, where `getUTCDay` puts Sunday at 0. */
function isoWeekday(at: Date): number {
  const sundayFirst = at.getUTCDay();
  return sundayFirst === 0 ? DAYS_IN_WEEK : sundayFirst;
}

/** The Thursday of the ISO week holding this date, which is the day that names the week. */
function thursdayOfTheWeek(at: Date): Date {
  const thursday = new Date(at.getTime());
  thursday.setUTCDate(thursday.getUTCDate() + THURSDAY - isoWeekday(at));
  return thursday;
}

/**
 * The ISO week identifier for a `YYYY-MM-DD` date, as `2026-W07`, or null when the text names no date.
 *
 * Null rather than a guess: a caller holding no week has nothing to record an outcome against, and a
 * fabricated identifier would attribute a fact about one week to another.
 */
export function isoWeekOf(isoDate: string): string | null {
  const parsed = parseIsoDate(isoDate);
  if (parsed === null) return null;

  const thursday = thursdayOfTheWeek(new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day)));
  const isoYear = thursday.getUTCFullYear();
  /* 4 January is in week 1 by definition, so the Thursday of its week is week 1's Thursday. */
  const firstThursday = thursdayOfTheWeek(new Date(Date.UTC(isoYear, 0, 4)));
  const week =
    1 + Math.round((thursday.getTime() - firstThursday.getTime()) / (MS_IN_DAY * DAYS_IN_WEEK));

  return `${isoYear}-W${String(week).padStart(2, "0")}`;
}
