/* A wall time in a named zone, as the instant the api stores.
 *
 * An off-plan period is declared as `Friday 14:00 to Monday 09:00`, which is two wall times, and the api takes
 * two instants. Something has to resolve one into the other, and the resolution is not arithmetic on a fixed
 * offset: the offset in force depends on the date, and twice a year it changes inside a single day.
 *
 * THE RULE IS THE DOMAIN'S RULE, RESTATED HERE BECAUSE THE CLIENT IS THE ONE COMPOSING THE INSTANT.
 * `syncr_domain.zones` resolves a zoned wall time with `fold=0`, which PEP 495 defines as the offset in
 * effect before a transition. Two consequences follow, and this module reproduces both:
 *
 *   A time that occurs twice takes the EARLIER of the two instants.
 *   A time that does not exist SHIFTS FORWARD by the gap, so 01:30 in a one-hour gap resolves to 02:30.
 *
 * Reproducing rather than asking the api is deliberate: the two ends of an off-plan period are typed together
 * and the reader has to see what they resolved to before sending them, and a round trip per keystroke would
 * make a form depend on the network to render its own summary. What guards the duplicate against drift is that
 * both rules are asserted here against the same two kinds of transition the domain's own tests use.
 *
 * A SHIFTED TIME IS REPORTED RATHER THAN CORRECTED. `wasShifted` is what lets a form say `01:30 does not
 * exist on this date, so this reads 02:30`, which is the whole reason to resolve client-side at all.
 *
 * `Intl` IS THE ZONE DATABASE. Rendering an instant in a zone and reading the parts back is what makes an
 * offset knowable without shipping a copy of tzdata: the browser and Node both carry one, and a zone the
 * runtime does not know is reported rather than guessed at.
 *
 * A TIME ARRIVES AS MINUTES SINCE MIDNIGHT, not as `HH:MM`. Parsing and snapping a clock field is the kit's
 * `parseClock` and `snapClock`, and this module is below the kit: a copy of that parser here would be a second
 * definition of what a clock time is, and an import of the kit from `lib` would put the two layers the wrong
 * way round. */

/** Minutes in an hour, named so the offset arithmetic reads as arithmetic rather than as a constant. */
const MINUTES_IN_HOUR = 60;
const MILLISECONDS_IN_MINUTE = 60_000;
const MINUTES_IN_DAY = 24 * MINUTES_IN_HOUR;

/* How far either side of a local day the offsets in play are looked for.
 *
 * A zone is at most fourteen hours from UTC, so a probe this far from the wall time read as UTC is on the far
 * side of any transition falling on that local day, and no zone transitions twice within two days. Probing
 * rather than deriving is what finds the SECOND offset of an ambiguous hour: on a fall-back date the wall time
 * read as UTC can already sit past the transition, so both derived candidates carry the later offset and the
 * earlier one, which is the answer, is never built. */
const PROBE_MILLISECONDS = 26 * MINUTES_IN_HOUR * MILLISECONDS_IN_MINUTE;

/** A wall time on a date, read in a zone. No offset: the zone and the date are what supply one. */
export interface WallMoment {
  /** `YYYY-MM-DD`. */
  readonly date: string;
  /** Minutes since midnight, which is what the kit's clock parser answers with. */
  readonly minutes: number;
  /** An IANA zone identifier. */
  readonly zone: string;
}

/** What a wall moment resolved to, and whether the zone moved it. */
export interface ResolvedInstant {
  /** RFC 3339 with an explicit offset, which is the only spelling of an instant this api takes. */
  readonly instant: string;
  /** The wall time the instant really lands on, which differs from the one asked for inside a gap. */
  readonly wallTime: string;
  /** The local date the instant really lands on. */
  readonly wallDate: string;
  /** True when the time asked for does not exist on that date, so it moved forward by the gap. */
  readonly wasShifted: boolean;
}

/** The zone's own reading of an instant: the wall clock it shows, and how far that is from UTC. */
interface ZoneReading {
  /** The wall time as if it were UTC, so two wall times can be compared as numbers. */
  readonly asUtcMilliseconds: number;
  readonly offsetMinutes: number;
  readonly date: string;
  readonly time: string;
}

const FORMATTERS = new Map<string, Intl.DateTimeFormat>();

/* One formatter per zone, kept because constructing one is the expensive half and a form resolves the same
 * zone on every keystroke. `h23` rather than `hour12: false`, which reports midnight as hour 24 on some ICU
 * builds and would put the arithmetic a day out for exactly the transition Havana has at midnight. */
function formatterFor(zone: string): Intl.DateTimeFormat {
  const held = FORMATTERS.get(zone);
  if (held !== undefined) return held;
  const made = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  FORMATTERS.set(zone, made);
  return made;
}

/** True when the runtime's zone database knows this identifier, so a stored zone can be reported. */
export function isKnownZone(zone: string): boolean {
  try {
    formatterFor(zone).format(0);
    return true;
  } catch {
    /* Nothing to evict: an unknown `timeZone` throws in the constructor, so `formatterFor` never cached one. */
    return false;
  }
}

function readingAt(zone: string, milliseconds: number): ZoneReading {
  const found: Record<string, string> = {};
  for (const part of formatterFor(zone).formatToParts(milliseconds)) found[part.type] = part.value;
  const asUtcMilliseconds = Date.UTC(
    Number(found.year),
    Number(found.month) - 1,
    Number(found.day),
    Number(found.hour),
    Number(found.minute),
    Number(found.second),
  );
  return {
    asUtcMilliseconds,
    offsetMinutes: Math.round((asUtcMilliseconds - milliseconds) / MILLISECONDS_IN_MINUTE),
    date: `${found.year}-${found.month}-${found.day}`,
    time: `${found.hour}:${found.minute}`,
  };
}

/** `+01:00`, `-05:00`, `+05:45`, or `Z` at zero, which is RFC 3339's own spelling for it. */
export function formatOffset(offsetMinutes: number): string {
  if (offsetMinutes === 0) return "Z";
  const sign = offsetMinutes < 0 ? "-" : "+";
  const total = Math.abs(offsetMinutes);
  const hours = String(Math.floor(total / MINUTES_IN_HOUR)).padStart(2, "0");
  const minutes = String(total % MINUTES_IN_HOUR).padStart(2, "0");
  return `${sign}${hours}:${minutes}`;
}

/** The date and the clock time a stored instant reads as in a zone, which is how a list renders one. */
export function wallOf(instant: string, zone: string): { date: string; time: string } | null {
  const milliseconds = Date.parse(instant);
  if (Number.isNaN(milliseconds) || !isKnownZone(zone)) return null;
  const reading = readingAt(zone, milliseconds);
  return { date: reading.date, time: reading.time };
}

/** The offset in force in a zone on a stated instant, in minutes. Null when either is unreadable. */
export function offsetMinutesAt(instant: string, zone: string): number | null {
  const milliseconds = Date.parse(instant);
  if (Number.isNaN(milliseconds) || !isKnownZone(zone)) return null;
  return readingAt(zone, milliseconds).offsetMinutes;
}

/** `YYYY-MM-DD` as three numbers, or null when the text is not one. */
function parseDate(text: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text.trim());
  if (match === null) return null;
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year: Number(match[1]), month, day };
}

/**
 * The instant a wall time in a zone names, or null when the date, the minutes or the zone is not one.
 *
 * One candidate is built per offset in play around that local day, and each is checked by rendering it back: an
 * instant is the answer only if the zone shows the wall time that was asked for. Where two hold, the time
 * occurs twice and the earlier instant is the answer. Where none holds, the time is inside a gap, and the
 * smallest offset in play is used, which is the one in force before the transition and is what shifts the
 * result forward by the gap.
 */
export function zonedInstant({ date, minutes, zone }: WallMoment): ResolvedInstant | null {
  const parsed = parseDate(date);
  if (parsed === null || !Number.isInteger(minutes)) return null;
  if (minutes < 0 || minutes >= MINUTES_IN_DAY || !isKnownZone(zone)) return null;

  const asUtc = Date.UTC(
    parsed.year,
    parsed.month - 1,
    parsed.day,
    Math.floor(minutes / MINUTES_IN_HOUR),
    minutes % MINUTES_IN_HOUR,
  );

  const offsets = new Set(
    [asUtc - PROBE_MILLISECONDS, asUtc, asUtc + PROBE_MILLISECONDS].map(
      (probe) => readingAt(zone, probe).offsetMinutes,
    ),
  );
  const holds = [...offsets]
    .map((offset) => asUtc - offset * MILLISECONDS_IN_MINUTE)
    .filter((candidate) => readingAt(zone, candidate).asUtcMilliseconds === asUtc);

  if (holds.length > 0) return resolvedAt(zone, Math.min(...holds), false);
  const beforeTransition = Math.min(...offsets);
  return resolvedAt(zone, asUtc - beforeTransition * MILLISECONDS_IN_MINUTE, true);
}

function resolvedAt(zone: string, milliseconds: number, wasShifted: boolean): ResolvedInstant {
  const reading = readingAt(zone, milliseconds);
  return {
    instant: `${reading.date}T${reading.time}:00${formatOffset(reading.offsetMinutes)}`,
    wallDate: reading.date,
    wallTime: reading.time,
    wasShifted,
  };
}

/** The local date in a zone at a stated instant, which is what a date field's `today` is. */
export function todayIn(zone: string, now: number): string {
  if (!isKnownZone(zone)) return "";
  return readingAt(zone, now).date;
}
