/* The wire values the settings and setup screens render, as factories.
 *
 * FACTORIES RATHER THAN LITERALS, because the same source appears in a table test, a notice test and a route test,
 * and three copies of it drift: the day one of them gains a field the others do not, the test that still passes is
 * the one asserting the least. Each factory produces a valid value and takes the overrides the case is about.
 *
 * THE IDENTIFIERS ARE UUIDS BECAUSE THE API'S ARE, and a select's value carries one: a fixture keyed `source-1`
 * would pass every test here and hide nothing useful.
 *
 * THE DEFAULTS ARE THE UNINTERESTING CASE. A source that synced successfully, no rejections, no travel, no off-plan
 * and a sleep routine that is inelastic. Every case below says what it varies. */

import type {
  CalendarSource,
  GoogleConnection,
  GoogleConsent,
} from "../../../api/hooks/useCalendarSources";
import type { OffPlanPeriod } from "../../../api/hooks/useOffPlan";
import type { Routine } from "../../../api/hooks/useRoutines";
import type { Settings, TravelOverride } from "../../../api/hooks/useSettings";

export const SOURCE_TIMETABLE = "8a1d5f20-0001-4b7e-9c31-0000000000c1";
export const SOURCE_PERSONAL = "8a1d5f20-0002-4b7e-9c31-0000000000c2";
export const SOURCE_PLAN = "8a1d5f20-0003-4b7e-9c31-0000000000c3";
export const OVERRIDE_BARCELONA = "8a1d5f20-0004-4b7e-9c31-0000000000v1";
export const PERIOD_LONG_WEEKEND = "8a1d5f20-0005-4b7e-9c31-0000000000p1";
export const ROUTINE_SLEEP = "8a1d5f20-0006-4b7e-9c31-0000000000r1";
export const ROUTINE_LUNCH = "8a1d5f20-0007-4b7e-9c31-0000000000r2";
export const ROUTINE_NAP = "8a1d5f20-0008-4b7e-9c31-0000000000r3";

/** The instant every relative reading in these tests is taken against. */
export const NOW = Date.parse("2026-08-05T09:00:00Z");

export function buildSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    visibleHours: 12,
    dayStart: "07:00:00",
    dayEnd: "23:00:00",
    reviewCadence: "on_demand",
    homeZone: "Europe/London",
    activeZone: "Europe/London",
    activeZoneDate: "2026-08-05",
    ...overrides,
  };
}

export function buildTravelOverride(overrides: Partial<TravelOverride> = {}): TravelOverride {
  return {
    id: OVERRIDE_BARCELONA,
    startDate: "2026-09-01",
    endDate: "2026-09-08",
    zone: "Europe/Madrid",
    ...overrides,
  };
}

export function buildSyncState(
  overrides: Partial<CalendarSource["syncState"]> = {},
): CalendarSource["syncState"] {
  return {
    eventsRead: 250,
    rejectedCount: 0,
    rejections: [],
    lastAttemptAt: "2026-08-05T08:30:00Z",
    lastSuccessAt: "2026-08-05T08:30:00Z",
    lastError: null,
    resyncReason: null,
    attempts: 1,
    ...overrides,
  };
}

export function buildSource(overrides: Partial<CalendarSource> = {}): CalendarSource {
  return {
    id: SOURCE_TIMETABLE,
    provider: "ics",
    role: "anchor-source",
    displayName: "Timetable",
    externalId: "https://example.edu/timetable.ics",
    included: true,
    state: "ok",
    anchorCount: 42,
    syncState: buildSyncState(),
    horizonDays: null,
    writeTarget: null,
    ...overrides,
  };
}

/** The source holding the role, with the reading whose statement is the destructive sentence. */
export function buildWriteTarget(overrides: Partial<CalendarSource> = {}): CalendarSource {
  return buildSource({
    id: SOURCE_PLAN,
    provider: "google",
    role: "write-target",
    displayName: "syncr · plan",
    externalId: "syncr-plan@group.calendar.google.com",
    anchorCount: 0,
    horizonDays: 14,
    writeTarget: {
      calendarName: "syncr · plan",
      horizonDays: 14,
      reconciliation: "destructive",
      statement:
        "syncr owns this calendar over the next 14 days. Anything it did not write inside that window is " +
        "removed, and an event you edit in a calendar client is overwritten on the next write.",
    },
    ...overrides,
  });
}

export function buildConnection(overrides: Partial<GoogleConnection> = {}): GoogleConnection {
  return {
    configured: true,
    connected: false,
    grantedScopes: [],
    connectedAt: null,
    lastRefreshAt: null,
    notices: [],
    ...overrides,
  };
}

export function buildConsent(overrides: Partial<GoogleConsent> = {}): GoogleConsent {
  return {
    authorizationUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=signed",
    scopes: [
      {
        scope: "https://www.googleapis.com/auth/calendar.readonly",
        statement: "Read the events on the calendars you choose, so they become commitments.",
      },
    ],
    calendarsRead: [{ displayName: "Personal", included: true }],
    statement: "syncr will read one calendar on this account.",
    ...overrides,
  };
}

/**
 * The write target's expiry, as the api raises it: one condition at two volumes with a shared identity root.
 *
 * `stillWorks` carries two capabilities because the type requires at least one and the story requires the notice to
 * say that reading anchors still works while writing does not.
 */
export function buildExpiryNotices(): GoogleConnection["notices"] {
  const shared = {
    pigment: "oxide" as const,
    title: "The plan is not reaching your calendar",
    detail:
      "Writes have been failing for 4 days. Google's authorization for syncr expired and has to be granted " +
      "again.",
    unavailable: ["Writing the plan to your Google calendar"],
    stillWorks: [
      "Reading your calendars, so the plan is still built around them",
      "Every other part of syncr, including solving and the week you see",
    ],
    since: "2026-08-01T09:00:00Z",
    action: { label: "Reconnect Google", href: "/settings" },
  };
  return [
    {
      ...shared,
      id: "google.write-target-expired.banner",
      volume: "banner",
      scope: null,
      isWholeProductDown: false,
    },
    {
      ...shared,
      id: "google.write-target-expired.panel",
      volume: "panel",
      scope: { screen: "settings" },
      isWholeProductDown: false,
    },
  ];
}

export function buildOffPlanPeriod(overrides: Partial<OffPlanPeriod> = {}): OffPlanPeriod {
  return {
    id: PERIOD_LONG_WEEKEND,
    start: "2026-08-07T13:00:00Z",
    end: "2026-08-10T08:00:00Z",
    keepFrame: false,
    label: "Barcelona",
    ...overrides,
  };
}

export function buildRoutine(overrides: Partial<Routine> = {}): Routine {
  return {
    id: ROUTINE_SLEEP,
    title: "Sleep",
    targetTime: "23:00:00",
    durationMinutes: 480,
    minDurationMinutes: 480,
    flexBandMinutes: 60,
    ...overrides,
  };
}

export function buildLunch(overrides: Partial<Routine> = {}): Routine {
  return buildRoutine({
    id: ROUTINE_LUNCH,
    title: "Lunch",
    targetTime: "13:00:00",
    durationMinutes: 45,
    minDurationMinutes: 45,
    ...overrides,
  });
}

/**
 * A second routine sharing the first's title, which the contract states is legitimate: a morning and an evening
 * `Shower` are both real. It differs from the first by its target time, which is what a reader tells them apart by.
 */
export function buildNap(overrides: Partial<Routine> = {}): Routine {
  return buildRoutine({
    id: ROUTINE_NAP,
    title: "Sleep",
    targetTime: "14:00:00",
    durationMinutes: 30,
    minDurationMinutes: 30,
    ...overrides,
  });
}
