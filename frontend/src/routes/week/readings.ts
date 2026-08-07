/* HOW AN INSTANT READS ON THIS SCREEN, IN THE WEEK'S OWN ZONE.
 *
 * THE ZONE IS A PARAMETER AND NEVER THE HOST'S. Rendering is single-zone: every time on the Week screen reads in the
 * zone the week's own days were resolved in, which the payload states per date. A reader east of their own plan would
 * otherwise see a Friday deadline reported as Saturday, which is the class of defect the zone map exists to prevent.
 *
 * `Intl` IS THE READER RATHER THAN A HAND-ROLLED OFFSET, because these are readings and not arithmetic: nothing here
 * feeds a comparison or a write. The two places that DO resolve a wall time back to an instant -- the drag and the
 * Today ledger's moved control -- do the offset arithmetic explicitly, and neither goes through this module. */

const WEEKDAY_AND_TIME = {
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
} as const;
const WEEKDAY_AND_DATE = { weekday: "short", day: "2-digit", month: "short" } as const;

/**
 * The readings and lookups every word on this screen is composed from.
 *
 * ONE CONTEXT FOR THE WHOLE SCREEN rather than one per narrowing. The verdict's deadline, a clause's rejected window
 * and the detail panel's `when` row are all instants read in one zone, and an Area's name is needed by a floor clause
 * and by nothing else: two context types would let two surfaces read one week in two zones.
 */
export interface WeekReadingsContext {
  /** The zone every reading here is taken in, which is the week's own head zone. */
  readonly zone: string;
  /** `Fri 09:00`. */
  readonly instant: (iso: string) => string;
  /** `Sun 09 Feb`. */
  readonly date: (iso: string) => string;
  /** `Fri 09:00 to 10:30`. */
  readonly span: (startIso: string, endIso: string) => string;
  /** An Area's name by id, or null where the plan names one no longer declared. */
  readonly areaName: (areaId: string) => string | null;
}

/** The context for a week read in one zone, with the Area names a floor clause needs. */
export function readingsIn(
  zone: string,
  areaNames: ReadonlyMap<string, string>,
): WeekReadingsContext {
  return {
    zone,
    instant: (iso) => instantReading(iso, zone),
    date: (iso) => dateReading(iso, zone),
    span: (start, end) => spanReading(start, end, zone),
    areaName: (areaId) => areaNames.get(areaId) ?? null,
  };
}

/** `Fri 09:00` for an instant, read in the stated zone. */
export function instantReading(iso: string, zone: string): string {
  return format(iso, zone, WEEKDAY_AND_TIME);
}

/** `Sun 09 Feb` for an instant, read in the stated zone. */
export function dateReading(iso: string, zone: string): string {
  return format(iso, zone, WEEKDAY_AND_DATE);
}

/** `09:00` for an instant, read in the stated zone: the form a time inside a known day takes. */
export function clockReading(iso: string, zone: string): string {
  return format(iso, zone, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

/** `09:00 to 10:30` for a span inside one day, and `Fri 09:00 to Sat 01:00` where it crosses one. */
export function spanReading(startIso: string, endIso: string, zone: string): string {
  const from = instantReading(startIso, zone);
  const to = instantReading(endIso, zone);
  const sameDay = from.slice(0, 3) === to.slice(0, 3);
  return sameDay ? `${from} to ${clockReading(endIso, zone)}` : `${from} to ${to}`;
}

/**
 * The reading, or the instant itself where the zone is one this platform does not know.
 *
 * An unknown zone is a fact about the payload rather than a reason to fail: the screen still has to draw, and an ISO
 * instant is worse to read but is not wrong. A zone that reaches here has already been through the settings screen's
 * own validation.
 */
function format(iso: string, zone: string, options: Intl.DateTimeFormatOptions): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat("en-GB", { ...options, timeZone: zone }).format(at);
  } catch {
    return iso;
  }
}
