/* The week pattern's draft: seven weekdays, and the one body that is a pattern.
 *
 * A partial mapping is the case worth every one of these: six weekdays is not six sevenths of a pattern, it is
 * not a pattern, because the seventh would materialize nothing at all. */

import { describe, expect, it } from "vitest";

import {
  EMPTY_PATTERN_DRAFT,
  patternBodyFrom,
  patternDraftFrom,
  unmappedWeekdays,
} from "../patternDraft";
import { DAY_TYPE_WEEKDAY, DAY_TYPE_WEEKEND, buildWeekPattern } from "./fixtures";

describe("the draft a declared pattern makes", () => {
  it("carries every weekday's day type", () => {
    expect(patternDraftFrom(buildWeekPattern())).toEqual({
      monday: DAY_TYPE_WEEKDAY,
      tuesday: DAY_TYPE_WEEKDAY,
      wednesday: DAY_TYPE_WEEKDAY,
      thursday: DAY_TYPE_WEEKDAY,
      friday: DAY_TYPE_WEEKDAY,
      saturday: DAY_TYPE_WEEKEND,
      sunday: DAY_TYPE_WEEKEND,
    });
  });

  /* A 404 is the api's answer before a pattern is declared, so `null` is a first-run state rather than a
   * failure, and the form starts empty from it. */
  it("is empty when no pattern is declared", () => {
    expect(patternDraftFrom(null)).toEqual(EMPTY_PATTERN_DRAFT);
    expect(unmappedWeekdays(patternDraftFrom(null))).toHaveLength(7);
  });
});

describe("the body a draft makes", () => {
  it("is the whole mapping once every weekday names a day type", () => {
    expect(patternBodyFrom(patternDraftFrom(buildWeekPattern()))).toEqual(buildWeekPattern());
  });

  it.each(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"] as const)(
    "is null while %s names no day type",
    (weekday) => {
      const draft = { ...patternDraftFrom(buildWeekPattern()), [weekday]: null };

      expect(patternBodyFrom(draft)).toBeNull();
      expect(unmappedWeekdays(draft)).toEqual([weekday]);
    },
  );

  it("names the weekdays still to choose, in week order", () => {
    const draft = { ...patternDraftFrom(buildWeekPattern()), sunday: null, tuesday: null };

    expect(unmappedWeekdays(draft)).toEqual(["tuesday", "sunday"]);
  });

  it("is null for an empty draft", () => {
    expect(patternBodyFrom(EMPTY_PATTERN_DRAFT)).toBeNull();
  });
});
