/* The wire values this screen renders, as factories.
 *
 * FACTORIES RATHER THAN LITERALS, because one task appears in a treatment test, a sort test and three network
 * tests, and five copies drift: the one that gains a field the others do not is the one still passing while
 * asserting the least. Each factory produces a valid value and takes the overrides the case is about.
 *
 * `atRisk` DEFAULTS TO FALSE AND IS NEVER DERIVED HERE. It is the server's determination, so a fixture that
 * computed it from the deadline would make the screen's own reading of the field a no-op and would be the second
 * arithmetic `US-TASK-03` exists to forbid.
 *
 * ONE HOME PER TICKET RATHER THAN ONE PER PRODUCT, which is what ticket 1132 records: two agents creating one
 * shared fixture module in the same wave is worse than two files that each state what their screen reads. */

import type { Area, Areas, Ramp } from "../../../api/hooks/useAreas";
import type { Backlog, BacklogHeader, BacklogTask } from "../../../api/hooks/useBacklog";
import type { Settings } from "../../../api/hooks/useSettings";
import type { Problem } from "../../../contract";

export const ZONE = "Europe/London";

export const AREA_CAREER = "3f1b7a3c-0001-4c8e-9a11-0000000000a1";
export const AREA_FITNESS = "3f1b7a3c-0002-4c8e-9a11-0000000000a2";

export const TASK_ORDINARY = "7c2d1a10-0001-4a3b-8b21-000000000001";
export const TASK_AT_RISK = "7c2d1a10-0002-4a3b-8b21-000000000002";
export const TASK_OVERDUE = "7c2d1a10-0003-4a3b-8b21-000000000003";

/* A Thursday inside `2026-W07`, and the instant the screen is drawn at in every test that pins one. So a
   deadline before it is overdue and one after it is not, whatever day the suite runs on. */
export const NOW_MS = Date.parse("2026-02-12T09:00:00Z");
export const YESTERDAY = "2026-02-11T23:59:00Z";
export const TOMORROW = "2026-02-13T23:59:00Z";

export function buildArea(overrides: Partial<Area> = {}): Area {
  return {
    id: AREA_CAREER,
    parentId: null,
    name: "Career",
    pigmentIndex: 0,
    budgetPercent: 60,
    floorHours: null,
    ...overrides,
  };
}

export function buildRamp(overrides: Partial<Ramp> = {}): Ramp {
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
    areas: [
      buildArea(),
      buildArea({ id: AREA_FITNESS, name: "Fitness", pigmentIndex: 1, budgetPercent: 40 }),
    ],
    ramp: buildRamp(),
    ...overrides,
  };
}

export function buildTask(overrides: Partial<BacklogTask> = {}): BacklogTask {
  return {
    id: TASK_ORDINARY,
    areaId: AREA_CAREER,
    projectId: null,
    title: "Read one paper",
    estimateMinutes: 60,
    recordedMinutes: 0,
    remainingMinutes: 60,
    deadline: null,
    priority: "normal",
    minChunkMinutes: 15,
    splittable: true,
    status: "open",
    completedAt: null,
    eligibleForSolving: true,
    atRisk: false,
    ...overrides,
  };
}

export function buildHeader(overrides: Partial<BacklogHeader> = {}): BacklogHeader {
  return { openCount: 1, atRiskCount: 0, ...overrides };
}

export function buildBacklog(overrides: Partial<Backlog> = {}): Backlog {
  return { header: buildHeader(), tasks: [buildTask()], ...overrides };
}

/**
 * The three treatments in one list: an ordinary row, one the verdict marks, and one whose deadline has passed.
 *
 * The overdue one is ALSO marked, because that is what the api answers for it: capacity is clipped to now, so a
 * task with a passed deadline and work left has no capacity before it and the verdict names it too. A fixture
 * that marked only the middle row would make the composed treatment untestable.
 */
export function buildThreeTreatments(): Backlog {
  return {
    header: buildHeader({ openCount: 3, atRiskCount: 2 }),
    tasks: [
      buildTask(),
      buildTask({
        id: TASK_AT_RISK,
        title: "Kontron take-home",
        deadline: TOMORROW,
        atRisk: true,
        estimateMinutes: 2400,
        remainingMinutes: 2400,
      }),
      buildTask({
        id: TASK_OVERDUE,
        title: "Renew the visa",
        deadline: YESTERDAY,
        atRisk: true,
        estimateMinutes: 120,
        remainingMinutes: 120,
      }),
    ],
  };
}

export function buildSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    homeZone: ZONE,
    activeZone: ZONE,
    activeZoneDate: "2026-02-12",
    dayStart: "06:00",
    dayEnd: "23:00",
    visibleHours: 16,
    reviewCadence: "quarterly",
    ...overrides,
  };
}

export function buildProblem(overrides: Partial<Problem> = {}): Problem {
  return {
    type: "syncr:validation-failed",
    title: "Validation failed",
    status: 422,
    detail: "One or more members were refused.",
    ...overrides,
  };
}
