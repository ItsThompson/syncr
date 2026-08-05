/* How this screen's figures and words read.
 *
 * Every case here is a boundary the wire can actually produce: a state with a figure and a state without
 * one, a presumption before and after the day was answered for, and a day the reader is no longer living. */

import { describe, expect, it } from "vitest";

import {
  AHEAD_TITLE,
  BEHIND_TITLE,
  backfillLabel,
  backfillReading,
  bandReading,
  clockRange,
  confirmationReading,
  dateReading,
  dayStanding,
  minutesRead,
  stateReading,
} from "../labels";
import { DATE, ZONE, buildDay, buildOutcome, buildRow } from "./fixtures";

const CONFIRMED_AT = "2026-02-09T20:41:00+00:00";

describe("the section titles", () => {
  it("say what each run of rows is", () => {
    expect(BEHIND_TITLE).toBe("Recorded \u00B7 before now");
    expect(AHEAD_TITLE).toBe("Ahead \u00B7 presumed until you say otherwise");
  });
});

describe("minutesRead", () => {
  it("counts minutes, which is what a ledger's duration column compares", () => {
    expect(minutesRead(210)).toBe("210m");
    expect(minutesRead(30)).toBe("30m");
    expect(minutesRead(0)).toBe("0m");
  });

  it("truncates a fraction rather than rendering one the wire cannot hold", () => {
    expect(minutesRead(45.7)).toBe("45m");
  });
});

describe("clockRange", () => {
  it("reads both ends in the zone it was given", () => {
    expect(clockRange(buildRow().interval, ZONE)).toBe("13:30\u201317:00");
    expect(clockRange(buildRow().interval, "Pacific/Kiritimati")).toBe("03:30\u201307:00");
  });
});

describe("stateReading", () => {
  it("reads a row with nothing said about it by the run it sits in", () => {
    expect(stateReading(buildRow(), "behind", ZONE)).toBe("presumed");
    expect(stateReading(buildRow(), "ahead", ZONE)).toBe("planned");
  });

  it("reads a recorded presumption as recorded, which is what confirming a day does to it", () => {
    const row = buildRow({
      outcome: buildOutcome({ state: "presumed", confirmedAt: CONFIRMED_AT }),
    });

    expect(stateReading(row, "behind", ZONE)).toBe("recorded");
  });

  it("reads a presumption recorded on an unconfirmed day as presumed", () => {
    const row = buildRow({ outcome: buildOutcome({ state: "presumed" }) });

    expect(stateReading(row, "behind", ZONE)).toBe("presumed");
  });

  it("names the state for the three that carry no figure", () => {
    for (const state of ["skipped", "completed"] as const) {
      expect(stateReading(buildRow({ outcome: buildOutcome({ state }) }), "behind", ZONE)).toBe(
        state,
      );
    }
  });

  it("shows a partial's own minutes beside the planned figure", () => {
    const row = buildRow({ outcome: buildOutcome({ state: "partial", actualMinutes: 145 }) });

    expect(stateReading(row, "behind", ZONE)).toBe("partial \u00B7 145m of 210m planned");
  });

  it("shows the interval a moved block really ran in, in the day's zone", () => {
    const row = buildRow({
      outcome: buildOutcome({
        state: "moved",
        actualInterval: { start: `${DATE}T18:00:00+00:00`, end: `${DATE}T19:30:00+00:00` },
      }),
    });

    expect(stateReading(row, "behind", ZONE)).toBe("moved \u00B7 ran 18:00\u201319:30");
  });

  /* A figure the state does not carry cannot be rendered, so the state alone is what reads. The api refuses
     the pairing, and a row that arrived with one anyway would say only what it is sure of. */
  it("falls back to the state where the figure the state names is missing", () => {
    const row = buildRow({ outcome: buildOutcome({ state: "partial", actualMinutes: null }) });

    expect(stateReading(row, "behind", ZONE)).toBe("partial");
  });
});

describe("the day's own readings", () => {
  it("says the date as a reader says it", () => {
    expect(dateReading(buildDay())).toBe("Monday, 9 February 2026");
  });

  it("says when the day was confirmed, in the day's own zone", () => {
    expect(confirmationReading(buildDay({ confirmedAt: CONFIRMED_AT }))).toBe("20:41");
  });

  it("says that a day has not been confirmed rather than leaving the cell empty", () => {
    expect(confirmationReading(buildDay())).toBe("not yet");
  });

  it("bands the date, the clock it was drawn at, and the zone both are read in", () => {
    expect(bandReading(buildDay(), `${DATE}T20:41:00+00:00`)).toBe(
      "Monday, 9 February 2026 \u00B7 20:41 \u00B7 Europe/London",
    );
  });
});

describe("the backfill's words", () => {
  it("states how many days the control would settle", () => {
    expect(backfillLabel(3)).toBe("Backfill 3 days");
    expect(backfillLabel(1)).toBe("Backfill 1 day");
  });

  it("states what a backfill settled, in the api's own figures", () => {
    expect(backfillReading(3, 41)).toBe("3 days confirmed, 41 blocks recorded.");
    expect(backfillReading(1, 1)).toBe("1 day confirmed, 1 block recorded.");
  });
});

describe("dayStanding", () => {
  it("says nothing while the reader is living the day on screen", () => {
    expect(dayStanding(buildDay(), `${DATE}T20:41:00+00:00`)).toBeNull();
  });

  /* A tab left open past local midnight holds the date it was opened on, and the reader can act on that
     only if they are told. */
  it("says the day has ended once now is past its span", () => {
    const standing = dayStanding(buildDay(), "2026-02-10T00:30:00+00:00");

    expect(standing).toContain("This day ended at 00:00 in Europe/London");
  });

  /* A host a date ahead of the tenant's home zone asks for a day that has not begun there. */
  it("says the day has not begun when now is before its span", () => {
    const standing = dayStanding(buildDay(), "2026-02-08T23:30:00+00:00");

    expect(standing).toContain("This day begins at 00:00 in Europe/London");
  });

  it("says nothing for an instant it cannot read", () => {
    expect(dayStanding(buildDay(), "not an instant")).toBeNull();
  });
});
