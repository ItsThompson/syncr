/* How this screen's figures and words read. Pure, so every boundary is a literal in a test.
 *
 * THE LEDGER COUNTS MINUTES. `docs/design/screens.html` renders the duration column as `30m` and `210m`,
 * which is the form the kit's own row documents, and it is not the `2h 30m` the templates screen uses: a
 * ledger's column exists so a reader compares durations down it without reading each one, and mixed hours
 * and minutes do not compare at a glance.
 *
 * A ROW WITH NOTHING SAID ABOUT IT READS AS `presumed` BEHIND NOW AND `planned` AHEAD OF IT, which is the
 * rendered sheet's own pair of words. The state is one state either way: what differs is that a block still
 * to come has not had the chance to happen, and a reader answering for the day is looking for the rows they
 * have to correct. The section header says the same thing at the top of each run.
 *
 * A PRESUMPTION THE READER HAS ANSWERED FOR READS AS `recorded`, because that is what confirming a day does
 * to it: the state the api stores is still `presumed` and what changed is that the day carries an instant.
 * Two words for one stored state is the product's own vocabulary rather than a second model of it, and it is
 * what makes a confirmed day legible row by row instead of only in the header.
 *
 * WHAT `moved` AND `partial` ADD IS THE MEASUREMENT, beside the planned figure rather than instead of it.
 * The row's own time column keeps the planned interval and its duration column the planned minutes, so a
 * `moved` row shows both intervals and a `partial` row shows both figures. */

import { dayLabel } from "../../ui/primitives";
import { stateOf, type Day, type DayRow, type OutcomeState } from "../../api/hooks/useDay";
import { clockIn } from "./instants";
import type { LedgerSectionKind } from "./types";

/** U+2013, which is what a range takes: a hyphen is for a compound word. */
const EN_DASH = "\u2013";
const MIDDOT = "\u00B7";

export const BEHIND_TITLE = `Recorded ${MIDDOT} before now`;
export const AHEAD_TITLE = `Ahead ${MIDDOT} presumed until you say otherwise`;

/** The word a row with no recorded outcome reads as, per section. */
const NOTHING_SAID: Readonly<Record<LedgerSectionKind, string>> = {
  behind: "presumed",
  ahead: "planned",
};

/** A span in whole minutes, as the ledger's duration column counts them. */
export function minutesRead(minutes: number): string {
  return `${Math.trunc(minutes)}m`;
}

/** An interval as two clock times in the day's own zone, joined by an en dash. */
export function clockRange(
  interval: { readonly start: string; readonly end: string },
  zone: string,
): string {
  return `${clockIn(interval.start, zone)}${EN_DASH}${clockIn(interval.end, zone)}`;
}

/**
 * What the row says happened, and the figure the state carries.
 *
 * The planned figure is repeated beside a measurement rather than left to the column, because the two sit
 * in different places on the row and the comparison is the whole point of recording one.
 */
export function stateReading(row: DayRow, section: LedgerSectionKind, zone: string): string {
  const outcome = row.outcome ?? null;
  if (outcome === null) return NOTHING_SAID[section];
  const state: OutcomeState = stateOf(row);

  const minutes = outcome.actualMinutes;
  if (state === "partial" && minutes !== null && minutes !== undefined) {
    return `partial ${MIDDOT} ${minutesRead(minutes)} of ${minutesRead(row.durationMinutes)} planned`;
  }

  const interval = outcome.actualInterval;
  if (state === "moved" && interval !== null && interval !== undefined) {
    return `moved ${MIDDOT} ran ${clockRange(interval, zone)}`;
  }

  if (state === "presumed") {
    return (outcome.confirmedAt ?? null) === null ? "presumed" : "recorded";
  }
  return state;
}

/** The date, as a reader says it: `Monday, 9 February 2026`. */
export function dateReading(day: Day): string {
  return dayLabel(day.date);
}

/** The clock the screen was drawn at, in the day's own zone, and the zone it is read in. */
export function nowReading(nowIso: string, zone: string): string {
  return `${clockIn(nowIso, zone)} ${MIDDOT} ${zone}`;
}

/** The band's eyebrow: which day this is, when it was drawn, and the zone both are read in. */
export function bandReading(day: Day, nowIso: string): string {
  return `${dateReading(day)} ${MIDDOT} ${nowReading(nowIso, day.zone)}`;
}

/** How the day's confirmation reads: the instant it was settled at, or that it has not been. */
export function confirmationReading(day: Day): string {
  if (day.confirmedAt === null) return "not yet";
  return clockIn(day.confirmedAt, day.zone);
}

/** What the backfill control offers, stating how many days it would settle. */
export function backfillLabel(unconfirmedDays: number): string {
  const days = unconfirmedDays === 1 ? "day" : "days";
  return `Backfill ${unconfirmedDays} ${days}`;
}

/** What a backfill settled, as the sentence the reader gets back. */
export function backfillReading(confirmedDays: number, blocksRecorded: number): string {
  const days = confirmedDays === 1 ? "day" : "days";
  const blocks = blocksRecorded === 1 ? "block" : "blocks";
  return `${confirmedDays} ${days} confirmed, ${blocksRecorded} ${blocks} recorded.`;
}

/**
 * That the day on screen is not the day being lived, or null while it is.
 *
 * Reachable two ways, and the reader can act on neither without being told: a tab left open past local
 * midnight holds the date it was opened on, and a reader whose home zone is a date ahead of the host's is
 * shown the host's day. The day's own span and the zone it was resolved in are what make it sayable, and
 * both come from the response rather than from this screen's guess.
 */
export function dayStanding(day: Day, nowIso: string): string | null {
  const now = Date.parse(nowIso);
  if (Number.isNaN(now)) return null;
  if (now >= Date.parse(day.span.end)) {
    return `This day ended at ${clockIn(day.span.end, day.zone)} in ${day.zone}. Reload to read the current day.`;
  }
  if (now < Date.parse(day.span.start)) {
    return `This day begins at ${clockIn(day.span.start, day.zone)} in ${day.zone}, so nothing in it has happened yet.`;
  }
  return null;
}
