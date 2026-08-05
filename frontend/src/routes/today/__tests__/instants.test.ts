/* Wall time and instants, across the two dates a year the naive mapping breaks.
 *
 * REAL ZONES AND REAL DATES, never a mocked offset, which is what `05-time-and-intervals.md`'s D3 asks of
 * the transition rules. Europe/London gives both cases: 01:30 does not exist on 29 March 2026 and occurs
 * twice on 25 October 2026. Pacific/Kiritimati is here because +14 puts the same instant on a different
 * date from the host's, which is the case a helper reading the host's zone renders wrongly. */

import { beforeAll, afterAll, describe, expect, it, vi } from "vitest";

import { clockIn, hostDateOf, instantAt } from "../instants";

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

describe("hostDateOf", () => {
  /* THE ZONE IS PINNED FOR THIS ONE CLAIM, because the claim is about the host's zone and the suite has to
     be able to make it on any machine. Under Paris, 23:30 on the 8th in UTC is already the 9th locally, so a
     derivation reading the date off `toISOString` answers with the day before: the day the reader has
     already finished.

     `stubEnv` rather than reading the value and putting it back: a host with no `TZ` set would be restored
     to the string "undefined", which is a zone nothing resolves. */
  beforeAll(() => {
    vi.stubEnv("TZ", "Europe/Paris");
  });
  afterAll(() => {
    vi.unstubAllEnvs();
  });

  it("takes the host's own calendar date rather than the date in UTC", () => {
    expect(hostDateOf(new Date("2026-02-08T23:30:00Z"))).toBe("2026-02-09");
  });

  it("pads a single-digit month and day, so the date is the one the api addresses", () => {
    expect(hostDateOf(new Date("2026-01-05T12:00:00Z"))).toBe("2026-01-05");
  });
});

/* Declared after the pinned block, so it runs after it: the zone is restored through the runner rather than
   by writing a remembered value back, because a host with no `TZ` set would be restored to the string
   "undefined" and every later date in this file would resolve in a zone nothing knows. */
describe("after the zone was pinned", () => {
  it("leaves the host's own zone rather than a value it invented", () => {
    expect(process.env.TZ).not.toBe("undefined");
  });

  it("reads an instant in the zone it is given, as it did before", () => {
    expect(clockIn("2026-02-09T13:30:00+00:00", LONDON)).toBe("13:30");
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
