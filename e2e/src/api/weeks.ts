/* ISO weeks and civil dates, derived from the clock the stack actually runs against.
 *
 * WHY THESE ARE COMPUTED RATHER THAN WRITTEN DOWN. The repository's other fixtures sit in February
 * 2026, because a unit test may name any week it likes. This suite may not: the plan-horizon
 * maintainer plans `[today_local, today_local + horizon_days)`, so a week named as a literal falls
 * out of the horizon the day after it is written and the scenario then observes an empty week and
 * calls it a failure. Every week a scenario names is therefore derived from today.
 *
 * The civil date is read IN THE TENANT'S HOME ZONE rather than in UTC, because that is the boundary
 * the horizon advances at: at 00:30 London in winter the UTC date and the London date agree, and at
 * 00:30 London in summer they do not, which would put a suite an hour either side of midnight on a
 * different week from the api.
 *
 * The arithmetic below runs on civil dates held as UTC instants at midnight, which is a calendar
 * representation and not an instant: no DST offset can shift it, because no local zone is involved
 * once the date has been read.
 */

const DAY_MS = 86_400_000;

export type IsoWeekId = string;
export type CivilDate = string;

export const MONDAY = 1;
export const TUESDAY = 2;
export const WEDNESDAY = 3;
export const THURSDAY = 4;
export const FRIDAY = 5;
export const SATURDAY = 6;
export const SUNDAY = 7;

/** Today's date in `zone`, as `YYYY-MM-DD`. */
export const civilDateIn = (zone: string, at: Date = new Date()): CivilDate =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(at);

const asUtcMidnight = (date: CivilDate): Date => new Date(`${date}T00:00:00Z`);

const asCivilDate = (at: Date): CivilDate => at.toISOString().slice(0, 10);

/** Monday is 1 and Sunday is 7, as ISO 8601 numbers them. */
const isoWeekday = (at: Date): number => at.getUTCDay() || SUNDAY;

/** The ISO week `date` falls in, as `2026-W07`. */
export const isoWeekOf = (date: CivilDate): IsoWeekId => {
  const thursday = asUtcMidnight(date);
  // The ISO year is the year of the Thursday in the same week, which is what makes a
  // December date belong to week 1 of the following year.
  thursday.setUTCDate(thursday.getUTCDate() + 4 - isoWeekday(thursday));
  const january1 = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((thursday.getTime() - january1.getTime()) / DAY_MS + 1) / 7);
  return `${thursday.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
};

/** The Monday of `isoWeek`, as `YYYY-MM-DD`. */
export const mondayOf = (isoWeek: IsoWeekId): CivilDate => {
  const match = /^(\d{4})-W(\d{2})$/.exec(isoWeek);
  if (!match) throw new Error(`${isoWeek} is not an ISO week identifier such as 2026-W07`);
  const year = Number(match[1]);
  const week = Number(match[2]);
  // January 4 is in ISO week 1 of its year, always and by definition, so week 1's Monday is
  // derivable from it without a table.
  const january4 = new Date(Date.UTC(year, 0, 4));
  const firstMonday = new Date(january4.getTime() - (isoWeekday(january4) - 1) * DAY_MS);
  return asCivilDate(new Date(firstMonday.getTime() + (week - 1) * 7 * DAY_MS));
};

/** One date inside `isoWeek`, named by its ISO weekday. */
export const dateIn = (isoWeek: IsoWeekId, weekday: number): CivilDate =>
  asCivilDate(new Date(asUtcMidnight(mondayOf(isoWeek)).getTime() + (weekday - MONDAY) * DAY_MS));

/** The ISO week `weeks` after `isoWeek`, negative for before. */
export const isoWeekShift = (isoWeek: IsoWeekId, weeks: number): IsoWeekId =>
  isoWeekOf(asCivilDate(new Date(asUtcMidnight(mondayOf(isoWeek)).getTime() + weeks * 7 * DAY_MS)));

/** `date` shifted by whole days, as `YYYY-MM-DD`. */
export const dateShift = (date: CivilDate, days: number): CivilDate =>
  asCivilDate(new Date(asUtcMidnight(date).getTime() + days * DAY_MS));

/** A wall time on a civil date, as an instant in `zone`. */
export const instantAt = (date: CivilDate, wallTime: string, zone: string): string => {
  // Two probes and a correction: the offset a zone is at on a given date is not knowable without
  // asking, and asking with the wrong offset can land in the previous or next day. Starting from
  // the UTC reading and correcting by the difference converges in one step everywhere except
  // inside a DST gap, which no scenario here places a block in.
  const naive = new Date(`${date}T${wallTime}Z`);
  const offsetMs = naive.getTime() - asZoned(naive, zone).getTime();
  return new Date(naive.getTime() + offsetMs).toISOString();
};

/** `at` read as if its wall clock were `zone`'s, which is what makes the offset measurable. */
const asZoned = (at: Date, zone: string): Date => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(at);
  const read = (type: string): string => parts.find((part) => part.type === type)?.value ?? "00";
  return new Date(
    `${read("year")}-${read("month")}-${read("day")}T${read("hour")}:${read("minute")}:${read("second")}Z`,
  );
};
