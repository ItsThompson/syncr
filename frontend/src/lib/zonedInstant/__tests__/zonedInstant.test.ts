/* The two DST rules, the odd offsets, and the cases where there is no answer.
 *
 * Every expectation here is a claim about a real transition rather than about the arithmetic: the London and
 * Havana dates are the ones `syncr_domain.zones` states its rules against, and Lord Howe is here because its
 * gap is thirty minutes rather than an hour, which is the case a formula written in whole hours passes anyway. */

import { describe, expect, it } from "vitest";

import {
  formatOffset,
  isKnownZone,
  offsetMinutesAt,
  todayIn,
  wallOf,
  zonedInstant,
} from "../zonedInstant";

const LONDON = "Europe/London";
const KATHMANDU = "Asia/Kathmandu";
const LORD_HOWE = "Australia/Lord_Howe";
const HAVANA = "America/Havana";

describe("an unambiguous wall time", () => {
  it("takes the offset in force on its own date", () => {
    expect(zonedInstant({ date: "2026-08-07", minutes: 14 * 60, zone: LONDON })).toEqual({
      instant: "2026-08-07T14:00:00+01:00",
      wallDate: "2026-08-07",
      wallTime: "14:00",
      wasShifted: false,
    });
  });

  it("takes the winter offset in winter, so the offset is read and not assumed", () => {
    expect(zonedInstant({ date: "2026-01-09", minutes: 9 * 60, zone: LONDON })?.instant).toBe(
      "2026-01-09T09:00:00Z",
    );
  });

  it("spells zero as Z, which is RFC 3339's own spelling", () => {
    expect(zonedInstant({ date: "2026-03-01", minutes: 0, zone: "UTC" })?.instant).toBe(
      "2026-03-01T00:00:00Z",
    );
  });

  it("carries a forty-five-minute offset, which whole-hour arithmetic would lose", () => {
    expect(zonedInstant({ date: "2026-05-04", minutes: 6 * 60 + 30, zone: KATHMANDU })).toEqual({
      instant: "2026-05-04T06:30:00+05:45",
      wallDate: "2026-05-04",
      wallTime: "06:30",
      wasShifted: false,
    });
  });

  it("carries a thirty-minute offset", () => {
    expect(zonedInstant({ date: "2026-05-04", minutes: 9 * 60, zone: LORD_HOWE })?.instant).toBe(
      "2026-05-04T09:00:00+10:30",
    );
  });

  it("resolves midnight, which is a day boundary rather than an absent value", () => {
    expect(zonedInstant({ date: "2026-08-07", minutes: 0, zone: LONDON })?.instant).toBe(
      "2026-08-07T00:00:00+01:00",
    );
  });

  it("resolves the last quarter hour of the day", () => {
    expect(zonedInstant({ date: "2026-08-07", minutes: 23 * 60 + 45, zone: LONDON })?.instant).toBe(
      "2026-08-07T23:45:00+01:00",
    );
  });
});

describe("a wall time that does not exist", () => {
  /* London moves to BST at 01:00 GMT on 2026-03-29, so 01:00 to 01:59 local does not happen. `fold=0` uses
   * the offset in force before the transition, which lands the instant an hour later on the clock. */
  it("shifts forward by the gap, which is the domain's stated rule", () => {
    const resolved = zonedInstant({ date: "2026-03-29", minutes: 60 + 30, zone: LONDON });
    expect(resolved).toEqual({
      instant: "2026-03-29T02:30:00+01:00",
      wallDate: "2026-03-29",
      wallTime: "02:30",
      wasShifted: true,
    });
  });

  it("shifts by thirty minutes where the gap is thirty minutes", () => {
    /* Lord Howe moves from +10:30 to +11:00 at 02:00 local on 2026-10-04, so 02:00 to 02:29 is absent and
     * 02:15 lands at 02:45. The whole point of the case: a shift is the gap's length, not an hour. */
    const resolved = zonedInstant({ date: "2026-10-04", minutes: 2 * 60 + 15, zone: LORD_HOWE });
    expect(resolved?.wasShifted).toBe(true);
    expect(resolved?.wallTime).toBe("02:45");
    expect(resolved?.instant).toBe("2026-10-04T02:45:00+11:00");
  });

  it("reports the shift, so a form can say the time asked for does not exist", () => {
    const asked = zonedInstant({ date: "2026-03-29", minutes: 60, zone: LONDON });
    expect(asked?.wasShifted).toBe(true);
    expect(asked?.wallTime).not.toBe("01:00");
  });
});

describe("a wall time that occurs twice", () => {
  /* London returns to GMT at 02:00 BST on 2026-10-25, so 01:00 to 01:59 local happens twice. `fold=0` takes
   * the earlier offset, which is the earlier of the two instants. */
  it("takes the earlier instant, which is the earlier offset", () => {
    expect(zonedInstant({ date: "2026-10-25", minutes: 60 + 30, zone: LONDON })).toEqual({
      instant: "2026-10-25T01:30:00+01:00",
      wallDate: "2026-10-25",
      wallTime: "01:30",
      wasShifted: false,
    });
  });

  it("does not report a shift, because the time it was asked for exists", () => {
    expect(zonedInstant({ date: "2026-10-25", minutes: 60 + 30, zone: LONDON })?.wasShifted).toBe(
      false,
    );
  });

  it("resolves a midnight transition, where the ambiguous hour is the first of the day", () => {
    /* Havana returns to CST at 01:00 local on 2026-11-01, so 00:00 to 00:59 happens twice: the case an
     * `hour12: false` formatter reporting midnight as hour 24 would put a day out. */
    const resolved = zonedInstant({ date: "2026-11-01", minutes: 30, zone: HAVANA });
    expect(resolved?.wallDate).toBe("2026-11-01");
    expect(resolved?.instant).toBe("2026-11-01T00:30:00-04:00");
  });
});

describe("what has no answer", () => {
  it("refuses a zone the runtime's database does not know", () => {
    expect(zonedInstant({ date: "2026-08-07", minutes: 0, zone: "Mars/Olympus" })).toBeNull();
    expect(isKnownZone("Mars/Olympus")).toBe(false);
    expect(isKnownZone(LONDON)).toBe(true);
  });

  it("refuses a date that is not a date", () => {
    expect(zonedInstant({ date: "07/08/2026", minutes: 0, zone: LONDON })).toBeNull();
    expect(zonedInstant({ date: "2026-13-01", minutes: 0, zone: LONDON })).toBeNull();
  });

  it("refuses minutes outside a day, and a fraction of a minute", () => {
    expect(zonedInstant({ date: "2026-08-07", minutes: 24 * 60, zone: LONDON })).toBeNull();
    expect(zonedInstant({ date: "2026-08-07", minutes: -1, zone: LONDON })).toBeNull();
    expect(zonedInstant({ date: "2026-08-07", minutes: 90.5, zone: LONDON })).toBeNull();
  });
});

describe("reading an instant back", () => {
  it("renders it in the zone asked for, one zone at a time", () => {
    expect(wallOf("2026-08-07T13:00:00Z", LONDON)).toEqual({ date: "2026-08-07", time: "14:00" });
    expect(wallOf("2026-08-07T13:00:00Z", KATHMANDU)).toEqual({
      date: "2026-08-07",
      time: "18:45",
    });
  });

  it("crosses the date line rather than clamping to the instant's own date", () => {
    expect(wallOf("2026-08-07T23:00:00Z", "Pacific/Auckland")).toEqual({
      date: "2026-08-08",
      time: "11:00",
    });
  });

  it("answers null for text that is not an instant, and for a zone that is not one", () => {
    expect(wallOf("not an instant", LONDON)).toBeNull();
    expect(wallOf("2026-08-07T13:00:00Z", "Mars/Olympus")).toBeNull();
  });

  it("states the offset in force at an instant, which is what a zone panel renders", () => {
    expect(offsetMinutesAt("2026-08-07T13:00:00Z", LONDON)).toBe(60);
    expect(offsetMinutesAt("2026-01-09T13:00:00Z", LONDON)).toBe(0);
    expect(offsetMinutesAt("2026-08-07T13:00:00Z", KATHMANDU)).toBe(345);
    expect(offsetMinutesAt("2026-08-07T13:00:00Z", "Mars/Olympus")).toBeNull();
  });
});

describe("the offset as text", () => {
  it("spells zero as Z and signs everything else", () => {
    expect(formatOffset(0)).toBe("Z");
    expect(formatOffset(60)).toBe("+01:00");
    expect(formatOffset(-300)).toBe("-05:00");
    expect(formatOffset(345)).toBe("+05:45");
    expect(formatOffset(630)).toBe("+10:30");
    expect(formatOffset(-570)).toBe("-09:30");
  });
});

describe("today in a zone", () => {
  it("is the zone's own date, not the runtime's", () => {
    const instant = Date.parse("2026-08-07T23:30:00Z");
    expect(todayIn("Pacific/Auckland", instant)).toBe("2026-08-08");
    expect(todayIn(LONDON, instant)).toBe("2026-08-08");
    expect(todayIn("America/Los_Angeles", instant)).toBe("2026-08-07");
  });

  it("is empty for a zone the runtime does not know, so a field starts unset rather than wrong", () => {
    expect(todayIn("Mars/Olympus", 0)).toBe("");
  });
});
