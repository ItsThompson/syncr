/* THE TWO DAYLIGHT-SAVING WEEKS, MIRRORED FROM THE DOMAIN'S OWN FIXTURE.
 *
 * `syncr_domain.fixtures.dst_weeks` is the one set of dates every DST claim in this system is made against, so the
 * grid's claims are made against the same set rather than against dates chosen here. Interval, zone, grid and
 * projector tests all read it, which is what stops one layer asserting a 23-hour day on a date another layer thinks
 * is 24.
 *
 * IT IS PYTHON AND THIS IS TYPESCRIPT, so the figures are a second spelling. `__tests__/dstWeeks.test.ts` reads the
 * Python file and requires every literal below to equal the one it mirrors, which is the same shape the snap
 * constant and the theme's breakpoint literals are pinned by: the duplicate is made incapable of drifting rather
 * than avoided, because avoiding it is not available across that boundary.
 *
 * Each week carries three spans and each exercises a different edge. THE WEEK SPAN is 167 or 169 hours. THE LOCAL
 * TRANSITION DAY is 23 or 25 hours, which is what the axis must stay proportional across. THE SUNDAY-NIGHT FRAME
 * starts inside the week and ends inside the next one, so it is the span that proves the boundary rule. */

/** One week holding a transition, with the figures the domain asserts about it. */
export interface DstWeek {
  readonly label: string;
  readonly zone: string;
  readonly isoWeek: string;
  /** The seven local dates, Monday first. */
  readonly dates: readonly string[];
  readonly transitionDate: string;
  readonly spanStart: string;
  readonly spanEnd: string;
  readonly spanMinutes: number;
  readonly transitionDayStart: string;
  readonly transitionDayEnd: string;
  readonly transitionDayMinutes: number;
  readonly sundayNightFrameStart: string;
  readonly sundayNightFrameEnd: string;
}

export const LONDON = "Europe/London";

const MINUTES_IN_HOUR = 60;

/** 01:00 GMT jumps to 02:00 BST, so the week and the day each lose an hour. */
export const SPRING_FORWARD: DstWeek = {
  label: "spring_forward",
  zone: LONDON,
  isoWeek: "2026-W13",
  dates: [
    "2026-03-23",
    "2026-03-24",
    "2026-03-25",
    "2026-03-26",
    "2026-03-27",
    "2026-03-28",
    "2026-03-29",
  ],
  transitionDate: "2026-03-29",
  spanStart: "2026-03-23T00:00:00Z",
  spanEnd: "2026-03-29T23:00:00Z",
  spanMinutes: 167 * MINUTES_IN_HOUR,
  transitionDayStart: "2026-03-29T00:00:00Z",
  transitionDayEnd: "2026-03-29T23:00:00Z",
  transitionDayMinutes: 23 * MINUTES_IN_HOUR,
  sundayNightFrameStart: "2026-03-29T22:00:00Z",
  sundayNightFrameEnd: "2026-03-30T06:00:00Z",
};

/** 02:00 BST repeats as 01:00 GMT, so the week and the day each gain an hour. */
export const FALL_BACK: DstWeek = {
  label: "fall_back",
  zone: LONDON,
  isoWeek: "2026-W43",
  dates: [
    "2026-10-19",
    "2026-10-20",
    "2026-10-21",
    "2026-10-22",
    "2026-10-23",
    "2026-10-24",
    "2026-10-25",
  ],
  transitionDate: "2026-10-25",
  spanStart: "2026-10-18T23:00:00Z",
  spanEnd: "2026-10-26T00:00:00Z",
  spanMinutes: 169 * MINUTES_IN_HOUR,
  transitionDayStart: "2026-10-24T23:00:00Z",
  transitionDayEnd: "2026-10-26T00:00:00Z",
  transitionDayMinutes: 25 * MINUTES_IN_HOUR,
  sundayNightFrameStart: "2026-10-25T23:00:00Z",
  sundayNightFrameEnd: "2026-10-26T07:00:00Z",
};

export const DST_WEEKS: readonly DstWeek[] = [SPRING_FORWARD, FALL_BACK];

/** The week's zone map as the wire sends it: every date keyed to the zone in force on it. */
export function zoneByDateOf(week: DstWeek): Record<string, string> {
  return Object.fromEntries(week.dates.map((date) => [date, week.zone]));
}
