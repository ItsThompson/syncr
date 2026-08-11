/* The wire values this screen renders, as factories.
 *
 * FACTORIES RATHER THAN LITERALS, because the same habit appears in a table test, an editor test and a route
 * test, and three copies of it drift: the day one of them gains a field the others do not, the test that still
 * passes is the one asserting the least. Each factory produces a valid value and takes the overrides the case
 * is actually about, so a test reads as the one thing it varies.
 *
 * The identifiers are UUIDs because the api's are, and a select's value carries one: a fixture keyed `habit-1`
 * would pass every test here and hide nothing useful. */

import type { Anchor } from "../../../api/hooks/useAnchors";
import type { AnchorType } from "../../../api/hooks/useAnchorTypes";
import type { Area, Areas, Ramp } from "../../../api/hooks/useAreas";
import type { CalendarSource } from "../../../api/hooks/useCalendarSources";
import type { Habit } from "../../../api/hooks/useHabits";
import type { Routine } from "../../../api/hooks/useRoutines";
import type {
  DayShape,
  DayShapeSummary,
  DayType,
  TemplateEntry,
} from "../../../api/hooks/useTemplates";
import type { WeekPattern } from "../../../api/hooks/useWeekPattern";
import type { Problem } from "../../../contract";

export const AREA_CAREER = "3f1b7a3c-0001-4c8e-9a11-0000000000a1";
export const AREA_FITNESS = "3f1b7a3c-0002-4c8e-9a11-0000000000a2";
export const DAY_TYPE_WEEKDAY = "3f1b7a3c-0003-4c8e-9a11-0000000000d1";
export const DAY_TYPE_WEEKEND = "3f1b7a3c-0004-4c8e-9a11-0000000000d2";
export const SHAPE_WEEKDAY = "3f1b7a3c-0005-4c8e-9a11-0000000000s1";
export const ROUTINE_WAKE = "3f1b7a3c-0006-4c8e-9a11-0000000000r1";
export const HABIT_GYM = "3f1b7a3c-0007-4c8e-9a11-0000000000h1";
export const HABIT_ANKI = "3f1b7a3c-0008-4c8e-9a11-0000000000h2";
export const TYPE_INTERVIEW = "3f1b7a3c-0009-4c8e-9a11-0000000000t1";
export const TYPE_LECTURE = "3f1b7a3c-0010-4c8e-9a11-0000000000t2";
export const SOURCE_TIMETABLE = "3f1b7a3c-0011-4c8e-9a11-0000000000c1";

export function buildArea(overrides: Partial<Area> = {}): Area {
  return {
    id: AREA_CAREER,
    parentId: null,
    name: "Career",
    pigmentIndex: 0,
    budgetPercent: 25,
    floorHours: null,
    ...overrides,
  };
}

export function buildRamp(overrides: Partial<Ramp> = {}): Ramp {
  /* `statement` is `string | null` on the wire and null is what the api sends until two Areas share a step, so
   * the default is the null: a fixture that omitted it would make a surface's own null handling a no-op. */
  return {
    pigmentCount: 12,
    pigmentsInUse: 2,
    areasSharingAPigment: 0,
    statement: null,
    ...overrides,
  };
}

export function buildAreas(overrides: Partial<Areas> = {}): Areas {
  return {
    areas: [buildArea(), buildArea({ id: AREA_FITNESS, name: "Fitness", pigmentIndex: 7 })],
    ramp: buildRamp(),
    ...overrides,
  };
}

export function buildDayType(overrides: Partial<DayType> = {}): DayType {
  return { id: DAY_TYPE_WEEKDAY, name: "Weekday", ...overrides };
}

export function buildShapeSummary(overrides: Partial<DayShapeSummary> = {}): DayShapeSummary {
  return {
    id: SHAPE_WEEKDAY,
    dayTypeId: DAY_TYPE_WEEKDAY,
    name: "Weekday",
    entryCount: 2,
    ...overrides,
  };
}

export function buildEntry(overrides: Partial<TemplateEntry> = {}): TemplateEntry {
  return {
    id: "3f1b7a3c-0012-4c8e-9a11-0000000000e1",
    kind: "concrete",
    targetTime: "05:00",
    durationMinutes: 15,
    flexBandMinutes: 30,
    areaId: null,
    bindingTarget: "routine",
    bindingRef: ROUTINE_WAKE,
    ...overrides,
  };
}

export function buildShape(overrides: Partial<DayShape> = {}): DayShape {
  return {
    id: SHAPE_WEEKDAY,
    dayTypeId: DAY_TYPE_WEEKDAY,
    name: "Weekday",
    entries: [
      buildEntry(),
      buildEntry({
        id: "3f1b7a3c-0013-4c8e-9a11-0000000000e2",
        kind: "slot",
        targetTime: "07:00",
        durationMinutes: 150,
        flexBandMinutes: 30,
        areaId: AREA_CAREER,
        bindingTarget: null,
        bindingRef: null,
      }),
    ],
    ...overrides,
  };
}

export function buildRoutine(overrides: Partial<Routine> = {}): Routine {
  return {
    id: ROUTINE_WAKE,
    title: "Wake Up",
    targetTime: "05:00",
    durationMinutes: 15,
    minDurationMinutes: 15,
    flexBandMinutes: 30,
    ...overrides,
  };
}

/* The two derivation sentences are the api's OWN, copied from `syncr_domain/cursor.py` and
 * `syncr_domain/debt.py`. A fixture that invented them would let this screen restate what the api already said
 * with nothing to notice it: the wording is the thing being rendered, so it is not a fixture's to choose. */
const CURSOR_STATEMENT =
  "On Legs because Chest & Back was confirmed complete. Derived from the outcome log, so there is " +
  "no control to set it: correct the day on Today and this re-derives.";

const DEBT_STATEMENT = "2 of 8 owed.";

export function buildHabit(overrides: Partial<Habit> = {}): Habit {
  return {
    id: HABIT_GYM,
    areaId: AREA_FITNESS,
    title: "Gym",
    cadence: { kind: "times_per_week", timesPerWeek: 4, approxDays: null },
    minDurationMinutes: 60,
    maxDurationMinutes: 60,
    missPolicy: "debt",
    bindingSource: "rotation",
    variants: ["Legs", "Chest & Back"],
    debtCapPeriods: 2,
    cursor: {
      index: 0,
      variant: "Legs",
      confirmedCompletions: 3,
      previousVariant: "Chest & Back",
      advancedAt: "2026-08-01T18:00:00+00:00",
      statement: CURSOR_STATEMENT,
    },
    debt: {
      outstanding: 2,
      cap: 8,
      misses: 2,
      forgivenAtCap: 0,
      raisedInWeeklySession: false,
      statement: DEBT_STATEMENT,
    },
    ...overrides,
  };
}

/** A habit whose content never varies, which is the case that shows no cursor at all. */
export function buildFixedHabit(overrides: Partial<Habit> = {}): Habit {
  return buildHabit({
    id: HABIT_ANKI,
    title: "Anki",
    areaId: AREA_CAREER,
    cadence: { kind: "daily", timesPerWeek: null, approxDays: null },
    bindingSource: "fixed",
    variants: [],
    cursor: null,
    ...overrides,
  });
}

export function buildAnchorType(overrides: Partial<AnchorType> = {}): AnchorType {
  return {
    id: TYPE_INTERVIEW,
    name: "Interview",
    ruleOrder: 0,
    matchTitleContains: "Interview",
    matchSourceId: null,
    prepLeadMinutes: 360,
    prepDurationMinutes: 30,
    prepAreaId: AREA_CAREER,
    transitLeadMinutes: 30,
    transitDurationMinutes: 30,
    returnTransitMinutes: 30,
    transitAreaId: AREA_CAREER,
    postBufferMinutes: 75,
    postScope: "areas",
    forbiddenAreaIds: [AREA_CAREER],
    casts: { prep: true, outboundTransit: true, returnTransit: true, recovery: true },
    ...overrides,
  };
}

/** The rendered sheet's `Lecture`: transit and no prep, which the prep-collision rule must accept. */
export function buildLectureType(overrides: Partial<AnchorType> = {}): AnchorType {
  return buildAnchorType({
    id: TYPE_LECTURE,
    name: "Lecture",
    ruleOrder: 1,
    matchTitleContains: null,
    matchSourceId: SOURCE_TIMETABLE,
    prepLeadMinutes: 0,
    prepDurationMinutes: 0,
    prepAreaId: null,
    transitLeadMinutes: null,
    postBufferMinutes: 0,
    postScope: "none",
    forbiddenAreaIds: [],
    casts: { prep: false, outboundTransit: true, returnTransit: true, recovery: false },
    ...overrides,
  });
}

export function buildAnchor(overrides: Partial<Anchor> = {}): Anchor {
  return {
    id: "3f1b7a3c-0014-4c8e-9a11-0000000000n1",
    sourceId: SOURCE_TIMETABLE,
    sourceName: "Timetable",
    readOnly: true,
    readOnlyStatement: "Timetable owns this commitment. syncr never edits or deletes one.",
    seriesUid: null,
    title: "Kontron Placement Interview",
    startsAt: "2026-08-10T09:07:00+00:00",
    endsAt: "2026-08-10T09:45:00+00:00",
    anchorTypeId: TYPE_INTERVIEW,
    anchorTypeName: "Interview",
    typeSource: "rule",
    possiblyStale: false,
    casts: { prep: true, outboundTransit: true, returnTransit: true, recovery: true },
    ...overrides,
  };
}

export function buildSource(overrides: Partial<CalendarSource> = {}): CalendarSource {
  return {
    id: SOURCE_TIMETABLE,
    provider: "ics",
    role: "anchor-source",
    displayName: "Timetable",
    externalId: "https://example.test/timetable.ics",
    included: true,
    state: "ok",
    anchorCount: 12,
    syncState: {
      attempts: 1,
      eventsRead: 12,
      lastAttemptAt: "2026-08-04T06:00:00+00:00",
      lastSuccessAt: "2026-08-04T06:00:00+00:00",
      lastError: null,
      rejectedCount: 0,
      rejections: [],
    },
    ...overrides,
  };
}

export function buildWeekPattern(overrides: Partial<WeekPattern> = {}): WeekPattern {
  return {
    monday: DAY_TYPE_WEEKDAY,
    tuesday: DAY_TYPE_WEEKDAY,
    wednesday: DAY_TYPE_WEEKDAY,
    thursday: DAY_TYPE_WEEKDAY,
    friday: DAY_TYPE_WEEKDAY,
    saturday: DAY_TYPE_WEEKEND,
    sunday: DAY_TYPE_WEEKEND,
    ...overrides,
  };
}

/** The refusal the prep-lead collision produces, as the api states it. */
export function buildPrepCollision(): Problem {
  return {
    type: "syncr:validation-failed",
    title: "Validation failed",
    status: 422,
    detail:
      "A prep lead of 15 minutes leaves prep running when the outbound leg leaves. Nothing was " +
      "changed and every other anchor type still reads as it did.",
    errors: [
      {
        field: "prepLeadMinutes",
        message:
          "must be at least 60, which is prepDurationMinutes (30) plus the transit lead (30)",
      },
    ],
  };
}
