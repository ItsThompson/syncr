/* Which travel override covers a date, and the one case the zone comparison gets wrong.
 *
 * THE SAME-ZONE OVERRIDE IS THE WHOLE REASON THIS MODULE EXISTS. Every other case agrees with
 * `activeZone !== homeZone`, so a test suite that omitted it would pass against the proxy this replaced. */

import { describe, expect, it } from "vitest";

import { overrideCovering } from "../travel";
import { buildTravelOverride } from "./fixtures";

const BARCELONA = buildTravelOverride({ startDate: "2026-09-01", endDate: "2026-09-08" });

describe("the override covering a date", () => {
  it("finds one whose range contains the date", () => {
    expect(overrideCovering([BARCELONA], "2026-09-04")?.id).toBe(BARCELONA.id);
  });

  /* Both dates are inclusive, which is the api's own contract, so both ends are covered. */
  it("covers the first and the last date of the range", () => {
    expect(overrideCovering([BARCELONA], "2026-09-01")).not.toBeNull();
    expect(overrideCovering([BARCELONA], "2026-09-08")).not.toBeNull();
  });

  it("does not cover the day either side of the range", () => {
    expect(overrideCovering([BARCELONA], "2026-08-31")).toBeNull();
    expect(overrideCovering([BARCELONA], "2026-09-09")).toBeNull();
  });

  it("answers null where nothing is declared", () => {
    expect(overrideCovering([], "2026-09-04")).toBeNull();
  });

  it("answers null for a date it cannot read, rather than matching everything", () => {
    expect(overrideCovering([BARCELONA], "")).toBeNull();
  });

  it("picks the one that covers the date out of several that do not", () => {
    const trip = buildTravelOverride({
      id: "8a1d5f20-0009-4b7e-9c31-0000000000v9",
      startDate: "2026-10-01",
      endDate: "2026-10-03",
      zone: "Asia/Tokyo",
    });

    expect(overrideCovering([BARCELONA, trip], "2026-10-02")?.zone).toBe("Asia/Tokyo");
  });

  /* THE CASE THE PROXY GETS WRONG. The api refuses an overlapping pair and an unknown zone, and refuses neither a
   * range whose zone is the one already in force. Such an override is a real declaration, and comparing the active
   * zone against the home zone reports that nothing covers the date while this does. */
  it("finds an override that names the home zone, which the zone comparison cannot see", () => {
    const sameZone = buildTravelOverride({ zone: "Europe/London" });

    expect(overrideCovering([sameZone], "2026-09-04")?.zone).toBe("Europe/London");
  });

  it("crosses a month and a year boundary, because a range is compared and not parsed", () => {
    const newYear = buildTravelOverride({ startDate: "2026-12-28", endDate: "2027-01-04" });

    expect(overrideCovering([newYear], "2026-12-31")).not.toBeNull();
    expect(overrideCovering([newYear], "2027-01-01")).not.toBeNull();
    expect(overrideCovering([newYear], "2027-01-05")).toBeNull();
  });
});
