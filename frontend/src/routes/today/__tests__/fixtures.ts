/* The wire values this screen renders, as factories.
 *
 * FACTORIES RATHER THAN LITERALS, because one day appears in a projection test, three component tests and
 * two network tests, and six copies of it drift: the day one of them gains a field the others do not, the
 * test that still passes is the one asserting the least. Each factory produces a valid value and takes the
 * overrides the case is about, so a test reads as the one thing it varies.
 *
 * BLOCK IDS ARE FULL SHA-256 HEX, because the api's are: a block id is a digest of the week and the
 * content it holds. A fixture keyed `block-1` would pass every test here and hide that the id is opaque,
 * which is the reason the recording body has to name the week separately.
 *
 * ONE HOME PER TICKET RATHER THAN ONE PER PRODUCT. The templates screen has its own factories for Areas
 * and this file has its own for the same reason ticket 1132 records: two agents creating one shared
 * fixture module in the same wave is a worse outcome than two files that each state what their screen
 * reads. */

import type { Areas, Ramp } from "../../../api/hooks/useAreas";
import type { Area } from "../../../api/hooks/useAreas";
import type { Backfill, Day, DayRow, Outcome } from "../../../api/hooks/useDay";
import type { Problem } from "../../../contract";

/** Monday of `2026-W07`, which is the date every fixture here is a day of. */
export const DATE = "2026-02-09";
export const ISO_WEEK = "2026-W07";
export const ZONE = "Europe/London";

export const AREA_CAREER = "3f1b7a3c-0001-4c8e-9a11-0000000000a1";
export const AREA_FITNESS = "3f1b7a3c-0002-4c8e-9a11-0000000000a2";

export const BLOCK_SLEEP = "a1".repeat(32);
export const BLOCK_GYM = "b2".repeat(32);
export const BLOCK_LEETCODE = "c3".repeat(32);
export const BLOCK_TRANSIT = "d4".repeat(32);

export function buildArea(overrides: Partial<Area> = {}): Area {
  return {
    id: AREA_CAREER,
    parentId: null,
    name: "Career",
    pigmentIndex: 0,
    budgetPercent: 25,
    floorHours: null,
    defaultPreferenceId: null,
    ...overrides,
  };
}

export function buildRamp(overrides: Partial<Ramp> = {}): Ramp {
  /* Null until two Areas hold one step, which is what the api sends: a fixture defaulting it to a
     sentence would make a surface's own null handling a no-op. */
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

export function buildOutcome(overrides: Partial<Outcome> = {}): Outcome {
  return {
    blockId: BLOCK_GYM,
    state: "skipped",
    actualMinutes: null,
    actualInterval: null,
    occurredAt: `${DATE}T07:00:00+00:00`,
    confirmedAt: null,
    ...overrides,
  };
}

export function buildRow(overrides: Partial<DayRow> = {}): DayRow {
  return {
    blockId: BLOCK_LEETCODE,
    interval: { start: `${DATE}T13:30:00+00:00`, end: `${DATE}T17:00:00+00:00` },
    durationMinutes: 210,
    areaId: AREA_CAREER,
    areaName: "Career",
    title: "Leetcode",
    origin: "task",
    outcome: null,
    ...overrides,
  };
}

/** The frame block that begins the day and carries no Area, so the Area column is legitimately empty. */
export function buildSleepRow(overrides: Partial<DayRow> = {}): DayRow {
  return buildRow({
    blockId: BLOCK_SLEEP,
    interval: { start: `${DATE}T00:00:00+00:00`, end: `${DATE}T07:00:00+00:00` },
    durationMinutes: 420,
    areaId: null,
    areaName: null,
    title: "Sleep",
    origin: "frame",
    ...overrides,
  });
}

export function buildGymRow(overrides: Partial<DayRow> = {}): DayRow {
  return buildRow({
    blockId: BLOCK_GYM,
    interval: { start: `${DATE}T07:00:00+00:00`, end: `${DATE}T08:00:00+00:00` },
    durationMinutes: 60,
    areaId: AREA_FITNESS,
    areaName: "Fitness",
    title: "Gym \u00B7 Chest & Back",
    origin: "habit",
    ...overrides,
  });
}

/** A transit block, which is a block like any other: it carries an Area and takes an outcome. */
export function buildTransitRow(overrides: Partial<DayRow> = {}): DayRow {
  return buildRow({
    blockId: BLOCK_TRANSIT,
    interval: { start: `${DATE}T17:30:00+00:00`, end: `${DATE}T18:00:00+00:00` },
    durationMinutes: 30,
    areaId: AREA_CAREER,
    areaName: "Career",
    title: "Go Home",
    origin: "transit",
    ...overrides,
  });
}

/**
 * A day with two rows behind now and two ahead of it, and nothing said about any of them.
 *
 * The figures are the ones the api derives, so a test that changes the rows states the figures it expects
 * rather than inheriting a pair that no longer describes them.
 */
export function buildDay(overrides: Partial<Day> = {}): Day {
  return {
    date: DATE,
    zone: ZONE,
    span: { start: `${DATE}T00:00:00+00:00`, end: "2026-02-10T00:00:00+00:00" },
    blockCount: 4,
    presumedCount: 4,
    confirmedAt: null,
    unconfirmedDays: 3,
    behind: [buildSleepRow(), buildGymRow()],
    ahead: [buildRow(), buildTransitRow()],
    ...overrides,
  };
}

export function buildEmptyDay(overrides: Partial<Day> = {}): Day {
  return buildDay({ blockCount: 0, presumedCount: 0, behind: [], ahead: [], ...overrides });
}

export function buildBackfill(overrides: Partial<Backfill> = {}): Backfill {
  return { confirmedDays: 3, blocksRecorded: 41, unconfirmedDays: 0, ...overrides };
}

/** The refusal a `partial` with no minutes carries, in the shape the api's error contract sends. */
export function buildOutcomeRejection(overrides: Partial<Problem> = {}): Problem {
  return {
    type: "syncr:validation-failed",
    title: "Validation failed",
    status: 422,
    detail:
      "That outcome was not accepted: a partial outcome states how many minutes it really took. " +
      "Nothing was changed, and the block still reads as it did.",
    errors: [{ field: "state", message: "requires actualMinutes" }],
    ...overrides,
  };
}
