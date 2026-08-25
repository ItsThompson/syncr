/* Representative payloads for the Areas screen, built from the wire types so a contract change breaks here.
 *
 * BUILT AROUND THE FIGURES THE SPEC ARGUES ABOUT, not around round numbers. The default week holds 6720
 * discretionary minutes, which is 112 hours: a 168-hour week that sleeps for 56. That is the figure ticket 1310
 * measured and the one the review reports where the budget route reports the whole span, so a fixture using
 * 10080 would quietly assert the wrong thing.
 *
 * THE DEFAULT SHARES SUM TO EXACTLY 100, because that is the case US-AREA-03 exists for: the vacancy is not zero
 * and the boundary is the default rather than a special test. */

import type { Area, Areas, Ramp } from "../../../api/hooks/useAreas";
import type {
  BudgetProposal,
  BudgetReview,
  ReviewCategory,
  ReviewDayCounts,
  ReviewTrendWeek,
} from "../../../api/hooks/useBudgetReview";
import type { Preference, PreferenceSet } from "../../../api/hooks/usePreferences";

export const PERIOD = "2026-W07";
export const DISCRETIONARY_MINUTES = 6720;
export const CAREER = "11111111-1111-4111-8111-111111111111";
export const STUDY = "22222222-2222-4222-8222-222222222222";
export const RUNNING = "33333333-3333-4333-8333-333333333333";

export function buildArea(overrides: Partial<Area> = {}): Area {
  return {
    id: CAREER,
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
    ...overrides,
  };
}

/** Two Areas whose shares sum to exactly 100, one of them declaring a floor. */
export function buildAreas(overrides: Partial<Areas> = {}): Areas {
  return {
    areas: [
      buildArea(),
      buildArea({
        id: STUDY,
        name: "Study",
        pigmentIndex: 4,
        budgetPercent: 40,
        floorHours: 5,
      }),
    ],
    ramp: buildRamp(),
    ...overrides,
  };
}

/** Thirteen declared Areas, as rows predating the cap would read: every step held, none shared. */
export function buildThirteenAreas(): Areas {
  return {
    areas: Array.from({ length: 13 }, (_, index) =>
      buildArea({
        id: `aaaaaaaa-0000-4000-8000-${String(index).padStart(12, "0")}`,
        name: `Area ${index + 1}`,
        pigmentIndex: index % 12,
        budgetPercent: null,
      }),
    ),
    ramp: buildRamp({ pigmentsInUse: 12 }),
  };
}

export function buildDayCounts(overrides: Partial<ReviewDayCounts> = {}): ReviewDayCounts {
  return { confirmed: 5, unconfirmed: 2, offPlan: 0, statement: null, ...overrides };
}

export function buildCategory(overrides: Partial<ReviewCategory> = {}): ReviewCategory {
  return { areaId: CAREER, targetMinutes: 4032, actualMinutes: 1092, ...overrides };
}

/** Career, Study, and the vacancy, whose three actuals tile the 6720-minute denominator. */
export function buildCategories(): ReviewCategory[] {
  return [
    buildCategory(),
    buildCategory({ areaId: STUDY, targetMinutes: 2688, actualMinutes: 736 }),
    buildCategory({ areaId: null, targetMinutes: 0, actualMinutes: 4892 }),
  ];
}

export function buildTrendWeek(overrides: Partial<ReviewTrendWeek> = {}): ReviewTrendWeek {
  return {
    period: PERIOD,
    slices: buildCategories(),
    days: buildDayCounts(),
    ...overrides,
  };
}

export function buildProposal(overrides: Partial<BudgetProposal> = {}): BudgetProposal {
  return {
    confirmedWeeks: 3,
    requiredWeeks: 13,
    shares: [],
    statement:
      "A proposal needs 13 fully confirmed weeks and 3 exist, so this review shows the gap between " +
      "actual and target only.",
    ...overrides,
  };
}

/** A proposal at the gate, with a row per Area and one for the vacancy. */
export function buildReadyProposal(): BudgetProposal {
  return buildProposal({
    confirmedWeeks: 13,
    shares: [
      {
        areaId: CAREER,
        declaredPercent: 60,
        observedPercent: 27.3,
        proposedPercent: 44,
        basis: "sustained_under",
        statement: "Sustained under target across the confirmed weeks.",
      },
      {
        areaId: STUDY,
        declaredPercent: 40,
        observedPercent: 18.4,
        proposedPercent: 40,
        basis: "floor_holds_it",
        statement:
          "Unchanged: this Area declares a floor, and the floor is what holds its time rather than " +
          "the share.",
      },
      {
        areaId: null,
        declaredPercent: 0,
        observedPercent: 54.3,
        proposedPercent: 27,
        basis: "sustained_over",
        statement: "Sustained over target across the confirmed weeks.",
      },
    ],
    statement:
      "Derived from 13 fully confirmed weeks, moving each target half the way to what actually " +
      "happened. syncr never re-cuts the budget on its own.",
  });
}

export function buildReview(overrides: Partial<BudgetReview> = {}): BudgetReview {
  return {
    period: PERIOD,
    span: { start: "2026-02-09T00:00:00Z", end: "2026-02-16T00:00:00Z" },
    discretionaryMinutes: DISCRETIONARY_MINUTES,
    unallocatedMinutes: 4892,
    oversubscriptionMinutes: 0,
    offPlanMinutes: 0,
    offPlanStatement: null,
    statement: null,
    days: buildDayCounts(),
    quarterDays: buildDayCounts({ confirmed: 21, unconfirmed: 4 }),
    categories: buildCategories(),
    trend: [buildTrendWeek({ period: "2026-W06" }), buildTrendWeek()],
    proposal: buildProposal(),
    ...overrides,
  };
}

export function buildPreference(overrides: Partial<Preference> = {}): Preference {
  return {
    owner: { kind: "area", id: CAREER },
    declared: {
      windows: [{ start: "05:30:00", end: "07:00:00" }],
      strength: "strong",
      preferredDurationMinutes: 90,
      maxPerDayMinutes: 180,
    },
    effective: {
      source: { kind: "area", id: CAREER },
      windows: [{ start: "05:30:00", end: "07:00:00" }],
      strength: "strong",
      preferredDurationMinutes: 90,
      statement: "Set on this area: 05:30-07:00, strong, ideally 90 minutes at a time.",
    },
    ...overrides,
  };
}

/** A preference declaring nothing, which is what an Area that has authored none answers with. */
export function buildNoPreference(areaId: string): Preference {
  return {
    owner: { kind: "area", id: areaId },
    declared: null,
    effective: null,
  };
}

export function buildPreferences(): PreferenceSet {
  return { [CAREER]: buildPreference(), [STUDY]: buildNoPreference(STUDY) };
}
