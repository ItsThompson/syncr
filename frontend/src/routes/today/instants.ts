/* An instant read as a clock time in a stated zone, and a clock time resolved back to an instant.
 *
 * THE `moved` OUTCOME IS WHY THE SECOND DIRECTION EXISTS. The control is a time-range input prefilled
 * with the planned interval, so the reader edits wall time and the api is owed instants with an explicit
 * offset. Nothing else on this screen writes a time.
 *
 * THE TWO TRANSITION RULES ARE THE DOMAIN'S, NOT THIS MODULE'S, and they are the reason resolving a wall
 * time is arithmetic rather than a string join. `05-time-and-intervals.md` states them: a local time that
 * does not exist shifts forward by the length of the gap, and a local time that occurs twice takes the
 * earlier offset. A frontend that answered either differently would send an instant an hour from the one
 * the plan was built with, on the two dates a year the naive mapping breaks.
 *
 * THE ZONE IS A PARAMETER AND NEVER A DEFAULT. Rendering is single-zone: every time on this screen reads
 * in the zone the day's bounds were resolved in, which the day response states, and the host's own zone is
 * not that zone for a reader who is travelling. */

import { formatIsoDate } from "../../ui/primitives";

const MS_IN_MINUTE = 60 * 1000;
const MS_IN_DAY = 24 * 60 * MS_IN_MINUTE;

/** The wall-clock fields a zone shows for an instant, as numbers. */
interface WallTime {
  readonly year: number;
  readonly month: number;
  readonly day: number;
  readonly hour: number;
  readonly minute: number;
}

function wallTimeIn(instant: Date, zone: string): WallTime {
  const parts = new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: zone,
  }).formatToParts(instant);

  const field = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((part) => part.type === type)?.value ?? "0");

  return {
    year: field("year"),
    month: field("month"),
    day: field("day"),
    hour: field("hour"),
    minute: field("minute"),
  };
}

/** Minutes to add to UTC to reach the zone's wall time at that instant, so BST is 60 and GMT is 0. */
function offsetMinutesAt(instant: Date, zone: string): number {
  const wall = wallTimeIn(instant, zone);
  const asIfUtc = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
  /* Seconds are dropped from `asIfUtc`, so they are dropped from the instant too before comparing:
     every zone offset in the IANA database this product can meet is a whole number of minutes. */
  const truncated = Math.floor(instant.getTime() / MS_IN_MINUTE) * MS_IN_MINUTE;
  return (asIfUtc - truncated) / MS_IN_MINUTE;
}

/**
 * A `HH:MM` clock time for an instant, in the given zone.
 *
 * An unreadable instant is handed back unchanged rather than rendered as a plausible time, which is what
 * the templates screen's instant label does for the same reason: a figure this screen cannot explain is
 * worse read as a different figure.
 */
export function clockIn(iso: string, zone: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return iso;
  const wall = wallTimeIn(instant, zone);
  return `${String(wall.hour).padStart(2, "0")}:${String(wall.minute).padStart(2, "0")}`;
}

/**
 * The host's own local date for an instant, as `YYYY-MM-DD`.
 *
 * The host's, deliberately: the ledger is addressed by date and this is the only date the client can know
 * without a second read. `toISOString` is not used for it, because that converts to UTC and would answer
 * with yesterday for every reader in a positive offset before their own midnight.
 */
export function hostDateOf(at: Date): string {
  return formatIsoDate(at.getFullYear(), at.getMonth() + 1, at.getDate());
}

/** Whether resolving `candidate` with this zone lands back on the wall time that was asked for. */
function landsOn(candidate: number, wallAsUtc: number, zone: string): boolean {
  const wall = wallTimeIn(new Date(candidate), zone);
  return Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute) === wallAsUtc;
}

/**
 * The instant a `YYYY-MM-DD` date and a `HH:MM` clock time name in a zone, as an ISO string in UTC.
 *
 * Null when either half is unreadable, so a caller sends nothing rather than an instant it invented.
 *
 * The offsets a day either side of the wall time bound the answer, because a transition moves a clock by
 * less than a day: taking a candidate under each is what makes both transition cases decidable. Two
 * candidates that both land on the wall time is the ambiguous case, and the earlier is the pre-transition
 * offset the domain rule names. None landing on it is the gap, and resolving under the offset in force
 * before it puts the result the same distance into the day as it would have been had the gap not existed.
 */
export function instantAt(isoDate: string, clock: string, zone: string): string | null {
  const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate.trim());
  const time = /^(\d{2}):(\d{2})$/.exec(clock.trim());
  if (date === null || time === null) return null;

  const wallAsUtc = Date.UTC(
    Number(date[1]),
    Number(date[2]) - 1,
    Number(date[3]),
    Number(time[1]),
    Number(time[2]),
  );
  if (Number.isNaN(wallAsUtc)) return null;

  const before = offsetMinutesAt(new Date(wallAsUtc - MS_IN_DAY), zone);
  const after = offsetMinutesAt(new Date(wallAsUtc + MS_IN_DAY), zone);
  const candidates = [wallAsUtc - before * MS_IN_MINUTE, wallAsUtc - after * MS_IN_MINUTE];
  const landing = candidates.filter((candidate) => landsOn(candidate, wallAsUtc, zone));

  const resolved = landing.length === 0 ? candidates[0] : Math.min(...landing);
  return new Date(resolved).toISOString();
}
