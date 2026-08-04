/* How this screen's figures and words read. Pure, so every boundary is a literal in a test.
 *
 * ONE RULE PER FIGURE, APPLIED EVERYWHERE. `docs/design/screens.html` renders a duration three ways in one
 * screen: `150m` for a slot, `8h 00m` for sleep, and `6h` for a prep lead. Three spellings of one quantity
 * make a column of them incomparable, which is the whole reason a duration column exists, so this file
 * states one: minutes below the hour, whole hours alone, and hours plus minutes otherwise.
 *
 * A FLEX BAND BELOW ONE STEP IS NOT A SMALL BAND, IT IS NO BAND. Every placement lands on the quarter hour,
 * so a band of five permits no shift at all and `±5m` would promise one. It reads as fixed instead, which is
 * what it is. */

import { SNAP_MINUTES, WEEKDAY_NAMES } from "../../ui/primitives";
import type { AnchorType } from "../../api/hooks/useAnchorTypes";
import type { Anchor } from "../../api/hooks/useAnchors";
import type { Habit } from "../../api/hooks/useHabits";
import type { WeekPatternBody } from "../../api/hooks/useWeekPattern";

const MINUTES_IN_HOUR = 60;

/** U+2212, which sets at the width of a plus. A hyphen does not. */
const MINUS = "\u2212";

/**
 * A span in minutes, as `45m`, `6h` or `2h 30m`.
 *
 * The wire's spans are whole minutes from zero, so a fraction is truncated and a negative keeps its sign
 * rather than being silently made positive: a figure this screen cannot explain is worse read as its own
 * opposite.
 */
export function minutesLabel(minutes: number): string {
  const whole = Math.trunc(minutes);
  const sign = whole < 0 ? MINUS : "";
  const magnitude = Math.abs(whole);
  const hours = Math.trunc(magnitude / MINUTES_IN_HOUR);
  const rest = magnitude % MINUTES_IN_HOUR;
  if (hours === 0) return `${sign}${rest}m`;
  if (rest === 0) return `${sign}${hours}h`;
  return `${sign}${hours}h ${rest}m`;
}

/** How far a placement may shift the entry either way, or `fixed` when it may not. */
export function flexLabel(minutes: number): string {
  if (Math.trunc(minutes) < SNAP_MINUTES) return "fixed";
  return `\u00B1${minutesLabel(minutes)}`;
}

/** The cadence, in the words the rendered sheet uses: `4 / wk`, `daily`, `~7d`. */
export function cadenceLabel(cadence: Habit["cadence"]): string {
  if (cadence.kind === "daily") return "daily";
  if (cadence.kind === "times_per_week") return `${cadence.timesPerWeek ?? 0} / wk`;
  return `~${cadence.approxDays ?? 0}d`;
}

/** One occurrence's span: the floor alone when the duration is fixed, and the range when it is elastic. */
export function habitDurationLabel(habit: Habit): string {
  if (habit.minDurationMinutes === habit.maxDurationMinutes) {
    return minutesLabel(habit.minDurationMinutes);
  }
  return `${minutesLabel(habit.minDurationMinutes)}\u2013${minutesLabel(habit.maxDurationMinutes)}`;
}

/** What a recovery window forbids, in the three words the control offers. */
export const POST_SCOPE_LABELS = {
  none: "nothing",
  all: "everything",
  areas: "these Areas",
} as const;

/** The whole three-way choice, as the form's own question. */
export const POST_SCOPE_QUESTION = "forbids after: nothing, everything, or these Areas";

/**
 * Which commitments a type's rules match, as the rules table states it.
 *
 * A type with neither rule matches every commitment, and saying so beats an empty cell: an empty cell in a
 * first-match-wins list reads as an unfinished row rather than as a catch-all sitting above everything below
 * it.
 */
export function matchLabel(type: AnchorType, sourceName: string | null): string {
  const clauses: string[] = [];
  if (type.matchTitleContains !== null)
    clauses.push(`title has \u201C${type.matchTitleContains}\u201D`);
  if (type.matchSourceId !== null)
    clauses.push(`source = ${sourceName ?? "a source you no longer have"}`);
  if (clauses.length === 0) return "any commitment";
  return clauses.join(" \u00B7 ");
}

/**
 * Where a commitment's type came from.
 *
 * The three readings are not interchangeable: a rule match may be replaced by a rule change, a retype
 * persists on the series and survives one, and an unmatched commitment is opaque busy time that casts no
 * shadow at all. A reader editing rules is deciding which of those they are looking at.
 */
export function typeProvenanceLabel(typeSource: Anchor["typeSource"]): string {
  if (typeSource === "override") return "retyped by you, on the series";
  if (typeSource === "rule") return "rule match";
  return "nothing matched";
}

/** The weekday members of the pattern, Monday first, in the order the wire declares them. */
export const WEEKDAY_KEYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const satisfies readonly (keyof WeekPatternBody)[];

export type Weekday = (typeof WEEKDAY_KEYS)[number];

/** The weekday's name, taken from the kit's own Monday-first list rather than from a second copy of it. */
export function weekdayLabel(weekday: Weekday): string {
  return WEEKDAY_NAMES[WEEKDAY_KEYS.indexOf(weekday)];
}

/**
 * An instant, in a stated zone.
 *
 * THE ZONE IS A PARAMETER AND NOT A DEFAULT, because an instant reads differently in each one and this module
 * does not know the reader's. A commitment at 23:30 in London is the next day in Auckland, so a helper that
 * quietly took the host's zone would render a date that is right for the machine and wrong for the reader.
 * The caller states which zone it is showing, and the surface says so beside the figure.
 */
export function instantLabel(iso: string, timeZone: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone,
  }).format(at);
}
