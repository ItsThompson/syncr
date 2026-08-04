/* The week pattern's draft, and the one body it can become.
 *
 * A PARTIAL MAPPING IS NOT A PATTERN. A weekday with no day type materializes nothing at all, so there is no
 * per-weekday merge rule to express and the api replaces the mapping whole. This module answers with the body
 * only when all seven weekdays name a day type, and otherwise names the weekdays still to choose, so the
 * control refuses the submit rather than sending six sevenths of a pattern.
 *
 * NOTHING HERE EXPRESSES A CADENCE, and there is nowhere it could: cadence lives on a habit, which is why the
 * api refuses a cadence member on every template shape. The screen states that beside the control, because an
 * absence a reader cannot see reads as a missing feature.
 *
 * Pure: no React, no client, no DOM. */

import { WEEKDAY_KEYS, type Weekday } from "./labels";
import type { WeekPattern, WeekPatternBody } from "../../api/hooks/useWeekPattern";

/** The day type each weekday names, or null while it names none. */
export type PatternDraft = Readonly<Record<Weekday, string | null>>;

export const EMPTY_PATTERN_DRAFT: PatternDraft = {
  monday: null,
  tuesday: null,
  wednesday: null,
  thursday: null,
  friday: null,
  saturday: null,
  sunday: null,
};

/** The declared pattern as a draft, or an empty draft when none is declared. */
export function patternDraftFrom(pattern: WeekPattern | null): PatternDraft {
  if (pattern === null) return EMPTY_PATTERN_DRAFT;
  return {
    monday: pattern.monday,
    tuesday: pattern.tuesday,
    wednesday: pattern.wednesday,
    thursday: pattern.thursday,
    friday: pattern.friday,
    saturday: pattern.saturday,
    sunday: pattern.sunday,
  };
}

/** The weekdays that still name no day type, in week order. */
export function unmappedWeekdays(draft: PatternDraft): readonly Weekday[] {
  return WEEKDAY_KEYS.filter((weekday) => draft[weekday] === null);
}

/** The whole mapping, or null while any weekday names no day type. */
export function patternBodyFrom(draft: PatternDraft): WeekPatternBody | null {
  const { monday, tuesday, wednesday, thursday, friday, saturday, sunday } = draft;
  if (
    monday === null ||
    tuesday === null ||
    wednesday === null ||
    thursday === null ||
    friday === null ||
    saturday === null ||
    sunday === null
  ) {
    return null;
  }
  return { monday, tuesday, wednesday, thursday, friday, saturday, sunday };
}
