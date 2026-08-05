/* Instants, spans and durations as this screen states them, all in the one active zone.
 *
 * ONE ZONE AT A TIME, WHICH IS US-TZ-02'S OWN RULE. Every time on this screen renders in the zone active for
 * the date being read, and no second zone is shown beside the first. The zone therefore arrives as an argument
 * everywhere rather than being read from the runtime: a formatter that reached for `Intl`'s default would
 * render a traveller's settings in the zone of the airport they are sitting in.
 *
 * A DURATION IS COARSE ON PURPOSE. `since 4 days` is what makes a reader act; `since 4 days, 3 hours and 12
 * minutes` makes them read. The largest unit that is at least one is the whole statement. */

import { wallOf } from "../../lib/zonedInstant";

const MINUTES_IN_HOUR = 60;
const MILLISECONDS_IN_MINUTE = 60_000;
const MINUTES_IN_DAY = 24 * MINUTES_IN_HOUR;

/** What a value reads as when the api has nothing to report. One spelling, so a column of them lines up. */
export const NOT_YET = "never";

/** `2026-08-05 · 14:32` in the active zone, or the instant unchanged when it cannot be read. */
export function statedInstant(instant: string | null | undefined, zone: string): string {
  if (instant === null || instant === undefined) return NOT_YET;
  const wall = wallOf(instant, zone);
  return wall === null ? instant : `${wall.date} \u00b7 ${wall.time}`;
}

/** `2026-08-07 14:00 to 2026-08-10 09:00`, both ends in the active zone. */
export function statedSpan(start: string, end: string, zone: string): string {
  return `${statedInstant(start, zone)} to ${statedInstant(end, zone)}`;
}

/**
 * How long ago an instant was, in the largest unit that is at least one.
 *
 * `just now` rather than `0 minutes`, because a duration of zero is a statement about rounding rather than about
 * the world. A future instant reads the same way: it is a clock disagreement, not a duration to report.
 */
export function statedAge(instant: string, now: number): string {
  const at = Date.parse(instant);
  if (Number.isNaN(at)) return instant;
  const minutes = Math.floor((now - at) / MILLISECONDS_IN_MINUTE);
  if (minutes < 1) return "just now";
  if (minutes < MINUTES_IN_HOUR) return plural(minutes, "minute");
  if (minutes < MINUTES_IN_DAY) return plural(Math.floor(minutes / MINUTES_IN_HOUR), "hour");
  return plural(Math.floor(minutes / MINUTES_IN_DAY), "day");
}

/** `7h 30m`, `45m`, `8h`. Minutes, because every duration in this product is a count of them. */
export function statedDuration(minutes: number): string {
  const hours = Math.floor(minutes / MINUTES_IN_HOUR);
  const rest = minutes % MINUTES_IN_HOUR;
  if (hours === 0) return `${rest}m`;
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}
