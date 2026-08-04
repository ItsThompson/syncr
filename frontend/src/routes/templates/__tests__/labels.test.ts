/* How this screen's figures and words read, at their boundaries.
 *
 * The interesting cases are the ones a rendering would not show: a span of zero, a flex band under one step, a
 * cadence whose number is the other kind's, a match rule naming nothing, and an instant whose DATE depends on
 * the zone it is read in. */

import { describe, expect, it } from "vitest";

import {
  POST_SCOPE_LABELS,
  WEEKDAY_KEYS,
  cadenceLabel,
  flexLabel,
  habitDurationLabel,
  instantLabel,
  matchLabel,
  minutesLabel,
  typeProvenanceLabel,
  weekdayLabel,
} from "../labels";
import { WEEKDAY_NAMES } from "../../../ui/primitives";
import { buildAnchorType, buildHabit } from "./fixtures";

describe("minutesLabel", () => {
  it.each([
    [0, "0m"],
    [15, "15m"],
    [45, "45m"],
    [60, "1h"],
    [75, "1h 15m"],
    [150, "2h 30m"],
    [360, "6h"],
    [480, "8h"],
    [840, "14h"],
    [1440, "24h"],
  ])("reads %i minutes as %s", (minutes, expected) => {
    expect(minutesLabel(minutes)).toBe(expected);
  });

  /* A figure this screen cannot explain must not be read as its own opposite: the wire's spans start at zero,
   * so a negative is a fault and it says so with a sign rather than silently becoming positive. */
  it("keeps a negative's sign, in the minus sign rather than a hyphen", () => {
    expect(minutesLabel(-90)).toBe("\u22121h 30m");
    expect(minutesLabel(-90)).not.toContain("-");
  });

  it("truncates a fraction rather than rendering one", () => {
    expect(minutesLabel(90.7)).toBe("1h 30m");
  });
});

describe("flexLabel", () => {
  /* Every placement lands on the quarter hour, so a band under one step permits no shift at all. Rendering
   * `±5m` would promise a shift that cannot happen. */
  it.each([
    [0, "fixed"],
    [5, "fixed"],
    [14, "fixed"],
  ])("reads a band of %i as fixed, because it permits no shift", (minutes, expected) => {
    expect(flexLabel(minutes)).toBe(expected);
  });

  it.each([
    [15, "\u00B115m"],
    [30, "\u00B130m"],
    [720, "\u00B112h"],
  ])("reads a band of %i as a shift either way", (minutes, expected) => {
    expect(flexLabel(minutes)).toBe(expected);
  });
});

describe("cadenceLabel", () => {
  it("reads a weekly count", () => {
    expect(cadenceLabel({ kind: "times_per_week", timesPerWeek: 4, approxDays: null })).toBe(
      "4 / wk",
    );
  });

  it("reads a daily cadence, which carries no number", () => {
    expect(cadenceLabel({ kind: "daily", timesPerWeek: null, approxDays: null })).toBe("daily");
  });

  it("reads an approximate interval in days", () => {
    expect(cadenceLabel({ kind: "every_approx_days", timesPerWeek: null, approxDays: 7 })).toBe(
      "~7d",
    );
  });

  /* The api refuses the number a kind does not use, so this shape is unreachable from a real response. It is
   * pinned because the alternative is rendering `undefined` in a table cell. */
  it("does not read the other kind's number when its own is absent", () => {
    expect(cadenceLabel({ kind: "times_per_week", timesPerWeek: null, approxDays: 7 })).toBe(
      "0 / wk",
    );
  });
});

describe("habitDurationLabel", () => {
  it("states one figure when the duration is fixed", () => {
    expect(habitDurationLabel(buildHabit({ minDurationMinutes: 60, maxDurationMinutes: 60 }))).toBe(
      "1h",
    );
  });

  it("states the range when the duration is elastic", () => {
    expect(habitDurationLabel(buildHabit({ minDurationMinutes: 30, maxDurationMinutes: 90 }))).toBe(
      "30m\u20131h 30m",
    );
  });
});

describe("matchLabel", () => {
  it("names the title substring", () => {
    expect(matchLabel(buildAnchorType(), null)).toBe("title has \u201CInterview\u201D");
  });

  it("names the source by name rather than by identifier", () => {
    const type = buildAnchorType({ matchTitleContains: null, matchSourceId: "any" });
    expect(matchLabel(type, "Timetable")).toBe("source = Timetable");
  });

  it("says so when a rule names a source this tenant no longer has", () => {
    const type = buildAnchorType({ matchTitleContains: null, matchSourceId: "gone" });
    expect(matchLabel(type, null)).toBe("source = a source you no longer have");
  });

  it("joins both clauses when a rule carries both", () => {
    const type = buildAnchorType({ matchSourceId: "any" });
    expect(matchLabel(type, "Timetable")).toBe(
      "title has \u201CInterview\u201D \u00B7 source = Timetable",
    );
  });

  /* A rule with no clause matches everything, and an empty cell in a first-match-wins list reads as an
   * unfinished row rather than as the catch-all sitting above everything below it. */
  it("says a rule with no clause matches any commitment", () => {
    const type = buildAnchorType({ matchTitleContains: null, matchSourceId: null });
    expect(matchLabel(type, null)).toBe("any commitment");
  });
});

describe("typeProvenanceLabel", () => {
  it("tells a retype apart from a rule match, in words", () => {
    expect(typeProvenanceLabel("override")).toBe("retyped by you, on the series");
    expect(typeProvenanceLabel("rule")).toBe("rule match");
    expect(typeProvenanceLabel("override")).not.toBe(typeProvenanceLabel("rule"));
  });

  it("says an unmatched commitment matched nothing", () => {
    expect(typeProvenanceLabel("unmatched")).toBe("nothing matched");
  });
});

describe("the weekday members", () => {
  /* The wire's member names and the kit's Monday-first list are two statements of one order, so they are
   * checked against each other: transposing two keys makes one of them disagree with its own name. */
  it("names the same weekday the kit's list does, at every position", () => {
    expect(WEEKDAY_KEYS).toHaveLength(WEEKDAY_NAMES.length);
    for (const [index, key] of WEEKDAY_KEYS.entries()) {
      expect(key).toBe(WEEKDAY_NAMES[index].toLowerCase());
    }
  });

  it("labels a weekday with the kit's own name", () => {
    expect(weekdayLabel("saturday")).toBe("Saturday");
  });
});

describe("the recovery scope's words", () => {
  it("reads as the three-way choice the control offers", () => {
    expect(POST_SCOPE_LABELS.none).toBe("nothing");
    expect(POST_SCOPE_LABELS.all).toBe("everything");
    expect(POST_SCOPE_LABELS.areas).toBe("these Areas");
  });
});

describe("instantLabel", () => {
  it("renders the clock time of the zone it is given", () => {
    const label = instantLabel("2026-08-10T09:07:00+00:00", "UTC");
    expect(label).toContain("09:07");
    expect(label).toContain("10 Aug");
  });

  /* The zone is a parameter because it changes the DATE, not only the clock: 23:30 UTC is the next day in
   * Auckland, and a helper that took the host's zone would render one that is right for the machine. */
  it("puts the same instant on a different date in a zone far enough east", () => {
    const utc = instantLabel("2026-08-10T23:30:00+00:00", "UTC");
    const auckland = instantLabel("2026-08-10T23:30:00+00:00", "Pacific/Auckland");

    expect(utc).toContain("10 Aug");
    expect(auckland).toContain("11 Aug");
  });

  /* A zone whose offset changes across the year would read an hour out if the formatter were handed a fixed
   * offset instead of the zone. Both of these are London instants, six months apart. */
  it("reads a zoned instant across a daylight-saving transition", () => {
    expect(instantLabel("2026-01-15T12:00:00+00:00", "Europe/London")).toContain("12:00");
    expect(instantLabel("2026-07-15T12:00:00+00:00", "Europe/London")).toContain("13:00");
  });

  it("hands back an unparseable instant unchanged rather than rendering an invalid date", () => {
    expect(instantLabel("not an instant", "UTC")).toBe("not an instant");
  });

  it("renders midnight in the 24-hour clock rather than as 24:00", () => {
    expect(instantLabel("2026-08-10T00:00:00+00:00", "UTC")).toContain("00:00");
  });
});
