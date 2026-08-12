/* THE WEEK SCREEN'S WIRE VALUES, AS FACTORIES TYPED AGAINST THE GENERATED CLIENT.
 *
 * EVERY FACTORY'S RETURN TYPE IS WHAT THE HOOK HANDS BACK, not a shape written beside the test. That is the whole
 * point of this file: a hand-built object satisfies a test and proves nothing, because the api may answer with
 * different members entirely. Typing the fixture against `WeekView` makes a renamed or dropped field a compile
 * error, and it caught two shapes this screen's first test file had invented -- an Area with `targetShare` and
 * `floorMinutesPerWeek`, which the api spells `budgetPercent` and `floorHours`, and a `reviewCadence` of `weekly`,
 * which is not one of the two the enum holds.
 *
 * BLOCK IDS ARE FULL SHA-256 HEX, because the api's are: a block id is a digest of the week and the binding it
 * holds. A fixture keyed `b1` would pass every test here and hide that the id is opaque, which is what makes a pin
 * name its block in the body rather than in the path.
 *
 * ONE HOME PER SCREEN RATHER THAN ONE PER PRODUCT, which is the split ticket 1132 records. Today has its own
 * factories for a day and for Areas, and this file has its own, because two agents editing one shared fixture
 * module in the same wave is a worse outcome than two files that each state what their own screen reads. */

import { http, HttpResponse } from "msw";

import { apiServer } from "../../../testing/apiServer";
import { jsonHandler, readyz } from "../../../testing/apiStub";
import type { Areas } from "../../../api/hooks/useAreas";
import type { Settings } from "../../../api/hooks/useSettings";
import type { Operation } from "../../../api/events";
import type { PlanDocument, WeekReadings, WeekView } from "../../../api/hooks/useWeek";
import type {
  PromotionCandidate,
  RaisedItem,
  SessionRetro,
  WeeklySession,
} from "../../../api/hooks/useWeeklySession";
import type { components } from "../../../api/schema";

type Block = components["schemas"]["BlockResponse"];
type Verdict = components["schemas"]["VerdictResponse"];
type Shortfall = components["schemas"]["ShortfallResponse"];
type Tradeoff = components["schemas"]["TradeoffResponse"];
type Adjustment = components["schemas"]["AdjustmentResponse"];
type Conflict = components["schemas"]["ConflictResponse"];
type Pin = components["schemas"]["PinResponse"];
type Proposal = components["schemas"]["ProposalDiffResponse"];
type BlockChange = components["schemas"]["BlockChangeResponse"];
type Pinned = components["schemas"]["PinnedResponse"];
type Approved = components["schemas"]["WeekApprovedResponse"];
type Span = components["schemas"]["WireSpan"];
type Reason = components["schemas"]["ReasonResponse"];

export const ISO_WEEK = "2026-W07";
export const ZONE = "Europe/London";
export const DATES = [
  "2026-02-09",
  "2026-02-10",
  "2026-02-11",
  "2026-02-12",
  "2026-02-13",
  "2026-02-14",
  "2026-02-15",
] as const;

export const AREA_CAREER = "3f6b2c9d-1a77-4a1b-9a5f-8a2e4a1b9a5f";
export const AREA_FITNESS = "3f6b2c9d-1a77-4a1b-9a5f-8a2e4a1b0002";
export const TASK_ID = "5c9e0d4f-6a12-4f3a-8b21-7d2b1a904c6e";
export const ROUTINE_ID = "5c9e0d4f-6a12-4f3a-8b21-7d2b1a904c70";
export const ANCHOR_ID = "5c9e0d4f-6a12-4f3a-8b21-7d2b1a904c71";
export const OPERATION_ID = "0f9b2c1e-0000-4000-8000-000000000001";
export const SUCCESSOR_ID = "0f9b2c1e-0000-4000-8000-000000000002";

export const BLOCK_LEETCODE = "a1".repeat(32);
export const BLOCK_APPLICATION = "b2".repeat(32);
export const BLOCK_GYM = "c3".repeat(32);
export const BLOCK_SLIVER = "d4".repeat(32);

export const LEETCODE = "Leetcode \u00b7 Graphs";
export const APPLICATION = "36 South Application";
export const GYM = "Gym";
export const SLIVER = "Wake Up";

export function span(start: string, end: string): Span {
  return { start, end };
}

/** An instant on the week's own Monday, in the fixture's zone, which runs at UTC+0 in February. */
export function monday(time: string): string {
  return `2026-02-09T${time}:00+00:00`;
}

export function tuesday(time: string): string {
  return `2026-02-10T${time}:00+00:00`;
}

export const SETTINGS: Settings = {
  homeZone: ZONE,
  activeZone: ZONE,
  activeZoneDate: DATES[0],
  dayStart: "06:00",
  dayEnd: "22:00",
  visibleHours: 12,
  reviewCadence: "quarterly",
};

export function buildAreas(): Areas {
  return {
    areas: [
      {
        id: AREA_CAREER,
        name: "Career",
        pigmentIndex: 0,
        parentId: null,
        budgetPercent: 25,
        floorHours: null,
      },
      {
        id: AREA_FITNESS,
        name: "Fitness",
        pigmentIndex: 1,
        parentId: null,
        budgetPercent: 10,
        floorHours: 5,
      },
    ],
    ramp: { pigmentCount: 12, pigmentsInUse: 2, areasSharingAPigment: 0, statement: null },
  };
}

export function buildReason(clauses: Reason["clauses"] = []): Reason {
  return { clauses };
}

export function buildBlock(overrides: Partial<Block> = {}): Block {
  return {
    id: BLOCK_LEETCODE,
    title: LEETCODE,
    areaId: AREA_CAREER,
    origin: "task",
    binding: { kind: "task", entityId: TASK_ID, occurrenceKey: "2026-02-09", splitIndex: null },
    interval: span(monday("09:00"), monday("10:30")),
    pinned: false,
    splitCount: null,
    supersededPlacement: null,
    objectiveDelta: null,
    reason: buildReason(),
    ...overrides,
  };
}

export function buildShortfall(overrides: Partial<Shortfall> = {}): Shortfall {
  return {
    kind: "deadline_capacity",
    minutes: 80,
    against: ["F&F Past Papers"],
    honoring: ["Fitness floor 5h"],
    deadline: "2026-02-13T09:00:00+00:00",
    areaId: AREA_CAREER,
    ...overrides,
  };
}

export function buildTradeoff(overrides: Partial<Tradeoff> = {}): Tradeoff {
  return {
    kind: "accept_partial",
    label: "Accept partial delivery on F&F Past Papers",
    targetId: TASK_ID,
    deltaMinutes: 80,
    ...overrides,
  };
}

export function buildVerdict(overrides: Partial<Verdict> = {}): Verdict {
  return {
    feasible: false,
    capacityIsSufficient: false,
    provenance: "probe",
    computedAt: monday("09:00"),
    inputVersion: 4,
    discretionaryMinutes: 3126,
    shortfalls: [buildShortfall()],
    tradeoffs: [buildTradeoff()],
    ...overrides,
  };
}

export function buildAdjustment(overrides: Partial<Adjustment> = {}): Adjustment {
  return {
    id: "7a1c4e02-0000-4000-8000-000000000001",
    isoWeek: ISO_WEEK,
    kind: "breach_floor",
    targetId: AREA_FITNESS,
    reductions: {},
    deltaMinutes: 80,
    createdAt: monday("08:00"),
    createdByOperationId: OPERATION_ID,
    ...overrides,
  };
}

export function buildOperation(overrides: Partial<Operation> = {}): Operation {
  return {
    id: OPERATION_ID,
    kind: "solve",
    status: "pending",
    target: { isoWeek: ISO_WEEK, sourceId: null },
    inputVersion: null,
    scheduledFor: monday("09:00"),
    startedAt: null,
    finishedAt: null,
    resultRevisionId: null,
    supersededBy: null,
    attempt: 1,
    error: null,
    statement: "A solve is due, and the plan on screen is the last one that landed.",
    ...overrides,
  };
}

export function buildPin(overrides: Partial<Pin> = {}): Pin {
  return {
    id: "9b3d5f01-0000-4000-8000-000000000001",
    isoWeek: ISO_WEEK,
    blockId: BLOCK_LEETCODE,
    interval: span(monday("13:00"), monday("14:30")),
    supersededPlacement: span(monday("09:00"), monday("10:30")),
    objectiveDelta: 0.18,
    weightSetVersion: 3,
    createdAt: monday("08:30"),
    ...overrides,
  };
}

export function buildConflict(overrides: Partial<Conflict> = {}): Conflict {
  return {
    id: "c0ffee01-0000-4000-8000-000000000001",
    isoWeek: ISO_WEEK,
    anchorId: ANCHOR_ID,
    blockId: BLOCK_LEETCODE,
    binding: { kind: "task", entityId: TASK_ID, occurrenceKey: "2026-02-09", splitIndex: null },
    overlap: span(monday("09:30"), monday("10:00")),
    detectedAt: monday("08:00"),
    resolvedAt: null,
    resolution: null,
    ...overrides,
  };
}

export function buildBlockChange(overrides: Partial<BlockChange> = {}): BlockChange {
  return {
    blockId: BLOCK_LEETCODE,
    binding: { kind: "task", entityId: TASK_ID, occurrenceKey: "2026-02-09", splitIndex: null },
    title: LEETCODE,
    areaId: AREA_CAREER,
    reason: buildReason(),
    before: span(monday("09:00"), monday("10:30")),
    after: span(monday("13:00"), monday("14:30")),
    ...overrides,
  };
}

export function buildProposal(overrides: Partial<Proposal> = {}): Proposal {
  return { added: [], removed: [], moved: [buildBlockChange()], ...overrides };
}

export function buildReadings(overrides: Partial<WeekReadings> = {}): WeekReadings {
  return {
    scheduledMinutes: 4848,
    discretionaryMinutes: 3126,
    unallocatedMinutes: 1104,
    oversubscriptionMinutes: 0,
    unconfirmedDays: 0,
    offPlanMinutes: 0,
    blockCount: 91,
    planCurrency: "current",
    ...overrides,
  };
}

export function buildPlan(overrides: Partial<PlanDocument> = {}): PlanDocument {
  return {
    isoWeek: ISO_WEEK,
    zoneByDate: Object.fromEntries(DATES.map((date) => [date, ZONE])),
    blocks: [
      buildBlock(),
      buildBlock({
        id: BLOCK_APPLICATION,
        title: APPLICATION,
        interval: span(tuesday("19:00"), tuesday("19:30")),
      }),
    ],
    forbiddenWindows: [
      {
        interval: span(monday("16:45"), monday("18:00")),
        kind: "recovery",
        scope: "all",
        forbiddenAreaIds: [],
        label: "recovery \u00b7 Kontron Interview",
        anchorId: ANCHOR_ID,
      },
    ],
    emptySlots: [
      {
        interval: span("2026-02-11T14:00:00+00:00", "2026-02-11T15:00:00+00:00"),
        areaId: AREA_CAREER,
        reason: "no_eligible_content",
      },
    ],
    adjustments: [],
    ...overrides,
  };
}

export const EMPTY_WEEK_FACTS: NonNullable<WeekView["emptyWeek"]> = {
  coversThisWeek: false,
  horizonDays: 14,
  horizonThrough: "2026-02-01",
  missingInputs: [],
  statement: "This week is beyond your 14-day planning horizon, which reaches 1 February.",
};

export function buildWeekView(overrides: Partial<WeekView> = {}): WeekView {
  return {
    isoWeek: ISO_WEEK,
    span: span("2026-02-09T00:00:00+00:00", "2026-02-16T00:00:00+00:00"),
    zoneByDate: Object.fromEntries(DATES.map((date) => [date, ZONE])),
    live: buildPlan(),
    emptyReason: null,
    emptyWeek: null,
    readings: buildReadings(),
    offPlan: [],
    operation: null,
    inputVersion: 4,
    adjustments: [],
    candidateAdjustment: null,
    conflicts: [],
    pins: [],
    proposal: null,
    verdict: null,
    ...overrides,
  };
}

/** What `POST /weeks/{isoWeek}/pins` answers with: the pin, the recomputed verdict, and the solve it asked for. */
export function buildPinned(overrides: Partial<Pinned> = {}): Pinned {
  return {
    pin: buildPin(),
    verdict: buildVerdict({ inputVersion: 5 }),
    operation: buildOperation(),
    ...overrides,
  };
}

/**
 * What `POST /weeks/{isoWeek}/approve` answers with.
 *
 * `projection` is an OPERATION and not nullable, which matters: the approval hands it to the operation hook, and a
 * fixture answering null crashes that hook on a shape the api cannot produce. Typing this against the generated schema
 * is what makes such a fixture a compile error instead of an unhandled rejection.
 */
export function buildApproved(overrides: Partial<Approved> = {}): Approved {
  return {
    revisionId: "8c2d0e01-0000-4000-8000-000000000001",
    isoWeek: ISO_WEEK,
    reason: "user_approved",
    approvedAt: monday("09:00"),
    inputVersion: 6,
    solvedAgainstVersion: 4,
    adjustment: null,
    projection: buildOperation({ kind: "projection" }),
    ...overrides,
  };
}

export interface WeekReads {
  /** How many times the week itself was read, which is how one refetch is told from two. */
  readonly weekReads: () => number;
  /** Every week identifier the screen asked for, in order, which is how `[`, `]` and `T` are observed. */
  readonly weeksRead: () => string[];
  /** The view the next read answers with, so a test can land a solve's result. */
  readonly serve: (view: WeekView) => void;
}

/**
 * The three reads the Week screen makes, answered with what the test gave them.
 *
 * EVERY WEEK IS ANSWERED, not only the one the test names, because the api serves every week and the screen navigates:
 * `[`, `]` and `T` change the week in the URL, and a handler bound to one identifier would turn a navigation into an
 * unhandled request. A neighbouring week is served the same plan under its own identifier, which is enough for a
 * navigation to be observable and is never a claim about what that week holds.
 */
export function installWeekReads(view: WeekView): WeekReads {
  let served = view;
  const asked: string[] = [];

  apiServer.use(
    readyz(),
    jsonHandler("/api/v1/settings", { status: 200, body: SETTINGS }),
    jsonHandler("/api/v1/areas", { status: 200, body: buildAreas() }),
    http.get(`${window.location.origin}/api/v1/weeks/:isoWeek`, ({ params }) => {
      const isoWeek = String(params.isoWeek);
      asked.push(isoWeek);
      return HttpResponse.json(isoWeek === served.isoWeek ? served : { ...served, isoWeek });
    }),
  );

  return {
    weekReads: () => asked.filter((isoWeek) => isoWeek === view.isoWeek).length,
    weeksRead: () => [...asked],
    serve: (next) => {
      served = next;
    },
  };
}

export const WEEK_PATH = `/week?week=${ISO_WEEK}`;

/**
 * The whole line the week band draws, which is what both screens that draw it are asserted against.
 *
 * WHOLE RATHER THAN A SUBSTRING, because a figure is a substring of every figure that ends in it: an assertion
 * looking only for `5 days unconfirmed` accepts a rendered `15 days unconfirmed`, and one looking only for
 * `1 day unconfirmed` accepts `11 day unconfirmed`. An equality also refuses a clause added beside the served
 * one. The zoom reading is this file's own settings fixture, and the trailing `z` is the key hint inside the
 * same paragraph.
 */
export function wholeBandLine(blockCount: number, unconfirmedReading: string): string {
  return `${blockCount} blocks · ${unconfirmedReading} · ${SETTINGS.visibleHours}h visible z`;
}

/* THE WEEKLY SESSION IS A MODE OF THAT SAME ROUTE, at that same week: `?mode=session`. Both parameters, because the
 * session is about a specific week and a link carrying only the mode would open on whichever week today falls in. */
export const SESSION_PATH = `/week?week=${ISO_WEEK}&mode=session`;

export const REVIEWED_WEEK = "2026-W06";

export function buildRaisedItem(overrides: Partial<RaisedItem> = {}): RaisedItem {
  return {
    key: "chronic_skip:habit:gym",
    kind: "chronic_skip",
    title: GYM,
    statement:
      "Proposed and skipped in 6 weeks running. syncr has not changed its priority and will not: " +
      "reschedule it, cut its scope, or drop it.",
    ...overrides,
  };
}

/* THE DEFAULT CANDIDATE IS ONE THE TEMPLATE CANNOT ABSORB, because that is what a task pattern is: a day shape's
 * entry holds a routine or a habit, so a repeated pin of a task is a real pattern with nothing to move, and the api
 * sends the reason. A fixture with a null refusal on a task would be a shape production cannot produce.
 *
 * `id` IS THE GROUP THE RULE FOUND, rendered as the api renders it: the kind, the content, the ISO weekday and the
 * minute of the day. It is what the accept and the decline routes address, and the panel keys its rows on it. */
export function buildPromotionCandidate(
  overrides: Partial<PromotionCandidate> = {},
): PromotionCandidate {
  return {
    id: `task.${TASK_ID}.2.780`,
    entityId: TASK_ID,
    kind: "task",
    title: LEETCODE,
    weekday: 2,
    localTime: "13:00",
    consecutiveWeeks: 4,
    weeks: ["2026-W03", "2026-W04", "2026-W05", REVIEWED_WEEK],
    acceptRefusal:
      `A day shape's entry holds a routine or a habit, and ${LEETCODE} is finite work your backlog ` +
      "places against its deadline, so your template has nothing to absorb this pattern into. " +
      "Nothing was changed.",
    ...overrides,
  };
}

/* A PATTERN THE TEMPLATE CAN ABSORB: the block came from an entry of a day shape, so the entry is what a promotion
 * moves and the api sends no refusal. The one shape the accept control is drawn for. */
export const PROMOTED_ENTRY_ID = "6d1f5d8e-0c2a-4f7b-9f1e-2b7a5c3d4e5f";

export function buildAbsorbablePromotion(
  overrides: Partial<PromotionCandidate> = {},
): PromotionCandidate {
  return buildPromotionCandidate({
    id: `template_entry.${PROMOTED_ENTRY_ID}.2.780`,
    entityId: PROMOTED_ENTRY_ID,
    kind: "template_entry",
    title: GYM,
    acceptRefusal: null,
    ...overrides,
  });
}

export function buildRetro(overrides: Partial<SessionRetro> = {}): SessionRetro {
  return {
    period: REVIEWED_WEEK,
    span: span("2026-02-02T00:00:00+00:00", "2026-02-09T00:00:00+00:00"),
    discretionaryMinutes: 6720,
    days: { confirmed: 5, unconfirmed: 1, offPlan: 1, statement: null },
    offPlanMinutes: 1440,
    offPlanStatement: null,
    statement:
      "5 confirmed days and 1 unconfirmed, and 1 declared off-plan. Only the confirmed days " +
      "contribute to the figures below.",
    categories: [
      { areaId: AREA_CAREER, targetMinutes: 3360, actualMinutes: 2400 },
      { areaId: AREA_FITNESS, targetMinutes: 1680, actualMinutes: 1800 },
      { areaId: null, targetMinutes: 1680, actualMinutes: 2520 },
    ],
    ...overrides,
  };
}

export function buildSession(overrides: Partial<WeeklySession> = {}): WeeklySession {
  return {
    isoWeek: ISO_WEEK,
    span: span(monday("00:00"), "2026-02-16T00:00:00+00:00"),
    inputVersion: 4,
    retro: buildRetro(),
    raised: [buildRaisedItem()],
    verdict: buildVerdict(),
    concessions: [],
    promotions: [buildPromotionCandidate()],
    promotionStatement:
      "syncr noticed these patterns and has changed nothing. A promotion edits your template only " +
      "when you accept it, and declining one does not raise it again for a while.",
    ...overrides,
  };
}

/**
 * The session's own read, added to whatever the week reads already answer.
 *
 * Every week is answered for the reason the week read is: the mode navigates with `[` and `]` like the screen does, and
 * a handler bound to one identifier would turn a navigation into an unhandled request.
 */
export function installSessionRead(session: WeeklySession): void {
  apiServer.use(
    http.get(`${window.location.origin}/api/v1/reviews/week/:isoWeek`, ({ params }) => {
      const isoWeek = String(params.isoWeek);
      return HttpResponse.json(isoWeek === session.isoWeek ? session : { ...session, isoWeek });
    }),
  );
}
