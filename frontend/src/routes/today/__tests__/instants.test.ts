/* Wall time and instants, across the two dates a year the naive mapping breaks.
 *
 * REAL ZONES AND REAL DATES, never a mocked offset, which is what `05-time-and-intervals.md`'s D3 asks of
 * the transition rules. Europe/London gives both cases: 01:30 does not exist on 29 March 2026 and occurs
 * twice on 25 October 2026. Pacific/Kiritimati is here because +14 puts the same instant on a different
 * date from the host's, which is the case a helper reading the host's zone renders wrongly. */

import { describe, expect, it } from "vitest";

import { clockIn, instantAt } from "../instants";

const LONDON = "Europe/London";
const KIRITIMATI = "Pacific/Kiritimati";

describe("clockIn", () => {
  it("reads an instant in the zone it was given, not in the host's", () => {
    expect(clockIn("2026-02-09T13:30:00+00:00", LONDON)).toBe("13:30");
    expect(clockIn("2026-02-09T13:30:00+00:00", KIRITIMATI)).toBe("03:30");
  });

  it("reads a summer instant at the zone's summer offset", () => {
    expect(clockIn("2026-07-01T13:30:00+00:00", LONDON)).toBe("14:30");
  });

  it("pads to two digits either side, so a column of times aligns", () => {
    expect(clockIn("2026-02-09T09:05:00+00:00", LONDON)).toBe("09:05");
    expect(clockIn("2026-02-09T00:00:00+00:00", LONDON)).toBe("00:00");
  });

  it("hands back text it cannot read rather than a plausible time", () => {
    expect(clockIn("not an instant", LONDON)).toBe("not an instant");
  });
});

describe("instantAt", () => {
  it("resolves a wall time under the offset in force on the day", () => {
    expect(instantAt("2026-02-09", "13:30", LONDON)).toBe("2026-02-09T13:30:00.000Z");
    expect(instantAt("2026-07-01", "13:30", LONDON)).toBe("2026-07-01T12:30:00.000Z");
  });

  it("resolves in the zone it was given rather than the host's", () => {
    expect(instantAt("2026-02-09", "13:30", KIRITIMATI)).toBe("2026-02-08T23:30:00.000Z");
  });

  /* SPRING FORWARD. London's clocks jump 01:00 to 02:00 on 29 March 2026, so 01:30 does not exist. The
     domain rule shifts forward by the gap: the instant is the one 01:30 would have been, which reads as
     02:30 local. */
  it("shifts a local time that does not exist forward by the length of the gap", () => {
    const resolved = instantAt("2026-03-29", "01:30", LONDON);

    expect(resolved).toBe("2026-03-29T01:30:00.000Z");
    expect(clockIn(resolved ?? "", LONDON)).toBe("02:30");
  });

  /* FALL BACK. London's clocks repeat 01:00 to 02:00 on 25 October 2026, so 01:30 happens twice. The
     domain rule takes the first occurrence, which is the pre-transition offset. */
  it("takes the earlier offset for a local time that occurs twice", () => {
    const resolved = instantAt("2026-10-25", "01:30", LONDON);

    expect(resolved).toBe("2026-10-25T00:30:00.000Z");
    expect(clockIn(resolved ?? "", LONDON)).toBe("01:30");
  });

  it("round-trips a wall time either side of both transitions", () => {
    for (const [date, clock] of [
      ["2026-03-29", "00:30"],
      ["2026-03-29", "03:30"],
      ["2026-10-25", "00:30"],
      ["2026-10-25", "03:30"],
    ]) {
      expect(clockIn(instantAt(date, clock, LONDON) ?? "", LONDON)).toBe(clock);
    }
  });

  it("answers null for a date or a clock it cannot read, so nothing is sent", () => {
    expect(instantAt("2026-2-9", "13:30", LONDON)).toBeNull();
    expect(instantAt("2026-02-09", "1:30", LONDON)).toBeNull();
    expect(instantAt("2026-02-09", "", LONDON)).toBeNull();
  });
});
