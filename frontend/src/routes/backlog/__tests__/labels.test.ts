/* THE READINGS, AND THE STANDING, over the cases the screen's own rendering cannot separate.
 *
 * A DEADLINE IS READ IN THE READER'S ZONE, so the same instant reads as two dates for two readers. That is the
 * whole reason the zone is a parameter, and it is asserted over an instant that lands on different days either
 * side of the date line rather than over a comfortable mid-afternoon one.
 *
 * AT RISK IS READ AND OVERDUE IS COMPUTED. The asymmetry is the substance of `US-TASK-03`: the marking is the
 * week verdict's determination and a comparison here would be a second arithmetic, while whether a deadline has
 * passed is a clock and nothing more. */

import { describe, expect, it } from "vitest";

import { NOW_MS, TOMORROW, YESTERDAY, buildHeader, buildTask } from "./fixtures";
import {
  NOTHING,
  chunkReading,
  deadlineReading,
  footerReading,
  headerReading,
  minutesReading,
} from "../labels";
import { isOverdue, standingOf } from "../standing";

describe("the band's sentence", () => {
  it("states both figures when something is at risk", () => {
    expect(headerReading(buildHeader({ openCount: 9, atRiskCount: 4 }))).toBe("9 open · 4 at risk");
  });

  it("says only the open count when nothing is, so a zero is not a claim about risk", () => {
    expect(headerReading(buildHeader({ openCount: 9, atRiskCount: 0 }))).toBe("9 open");
  });
});

describe("the footer's sentence", () => {
  it("counts the rows drawn rather than the backlog, and agrees with itself in the singular", () => {
    expect(footerReading(0)).toBe("0 rows");
    expect(footerReading(1)).toBe("1 row");
    expect(footerReading(12)).toBe("12 rows");
  });
});

describe("a deadline cell", () => {
  it("reads the instant in the reader's own zone", () => {
    /* 23:00 UTC on the 12th is the 13th at 08:00 in Tokyo and still the 12th in London. A cell formatted in the
       host's zone would put the deadline on the wrong day for one of the two readers. */
    const instant = "2026-02-12T23:00:00Z";

    expect(deadlineReading(instant, "Europe/London")).toBe("2026-02-12 23:00");
    expect(deadlineReading(instant, "Asia/Tokyo")).toBe("2026-02-13 08:00");
  });

  it("says nothing for a task with no deadline, rather than inventing one", () => {
    expect(deadlineReading(null, "Europe/London")).toBe(NOTHING);
  });

  it("says nothing for a zone the runtime does not know, rather than a wrong day", () => {
    expect(deadlineReading("2026-02-12T23:00:00Z", "Not/AZone")).toBe(NOTHING);
  });
});

describe("a duration cell", () => {
  it("counts minutes under an hour and hours above it", () => {
    expect(minutesReading(45)).toBe("45m");
    expect(minutesReading(60)).toBe("1h");
    expect(minutesReading(90)).toBe("1h 30m");
    expect(minutesReading(2400)).toBe("40h");
  });
});

describe("the physics cell", () => {
  it("names the floor a split may leave", () => {
    expect(chunkReading(buildTask({ splittable: true, minChunkMinutes: 45 }))).toBe("≥ 45m");
  });

  /* An atomic task's stored minimum is kept but unread, because its only placement is the whole estimate. A cell
     that showed the figure would offer a reader a number the solver does not use. */
  it("says atomic rather than a figure the solver does not read", () => {
    expect(chunkReading(buildTask({ splittable: false, minChunkMinutes: 45 }))).toBe("atomic");
  });
});

describe("whether a row is overdue", () => {
  it("is the deadline against the instant given, and nothing else", () => {
    expect(isOverdue(buildTask({ deadline: YESTERDAY }), NOW_MS)).toBe(true);
    expect(isOverdue(buildTask({ deadline: TOMORROW }), NOW_MS)).toBe(false);
  });

  it("is false for a task with no deadline, which cannot be late for anything", () => {
    expect(isOverdue(buildTask({ deadline: null }), NOW_MS)).toBe(false);
  });

  it("is false for a deadline that is not an instant, rather than reading as the epoch", () => {
    expect(isOverdue(buildTask({ deadline: "not an instant" }), NOW_MS)).toBe(false);
  });
});

describe("the standing a row carries", () => {
  /* THE MARKING IS READ. Both rows here are due at the same instant and both carry the same work; what separates
     them is the field the api sent. A rule deriving it from the deadline could not tell them apart. */
  it("takes at risk from the response and never derives it", () => {
    const marked = buildTask({ deadline: TOMORROW, atRisk: true });
    const fine = buildTask({ deadline: TOMORROW, atRisk: false });

    expect(standingOf(marked, NOW_MS).isAtRisk).toBe(true);
    expect(standingOf(fine, NOW_MS).isAtRisk).toBe(false);
  });

  it("carries both where both hold, because a passed deadline has no capacity before it", () => {
    const standing = standingOf(buildTask({ deadline: YESTERDAY, atRisk: true }), NOW_MS);

    expect(standing).toEqual({ isOverdue: true, isAtRisk: true });
  });

  it("carries neither on a task that has left the backlog, because nothing is owed on it", () => {
    for (const status of ["completed", "dropped"] as const) {
      expect(standingOf(buildTask({ deadline: YESTERDAY, atRisk: true, status }), NOW_MS)).toEqual(
        {},
      );
    }
  });
});
