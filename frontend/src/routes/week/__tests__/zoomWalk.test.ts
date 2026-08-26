/* THE WALK `z` TAKES, HELD AGAINST THE REPORT IT WALKS.
 *
 * The walk is a pure function of the report and the level the screen holds, so its cases are direct: what it
 * answers for each shape of report, and what it refuses to answer where there is nothing to walk. The screen-level
 * cases in `zoomReading.test.tsx` hold the same walk against what the grid actually draws; what they cannot reach
 * is a press before any grid has reported, which is the first case below.
 *
 * THE REPORT'S SHAPES COME FROM THE DOMAIN, not from literals: the reference display's range (cap 16) is built by
 * `zoomLevels`, the same source the band's segment renders, so these cases cannot drift from what a real report
 * carries. */

import { describe, expect, it } from "vitest";

import type { ZoomReport } from "../../../ui/domain";
import { zoomLevels } from "../../../ui/domain/week-grid/zoom";
import { nextAvailableHours } from "../zoomWalk";

const REFERENCE_REPORT: ZoomReport = { hours: 12, levels: zoomLevels(626) };

describe("the walk through the reported range", () => {
  it("answers the next hour when every level up the range is available", () => {
    expect(nextAvailableHours(REFERENCE_REPORT, 12)).toBe(13);
    expect(nextAvailableHours(REFERENCE_REPORT, 15)).toBe(16);
  });

  /* THE TICKET'S OWN CASE: past the cap every level carries its own refusal, so the walk skips all of them and
   * wraps to the floor rather than proposing one of them. */
  it("wraps from the cap straight to the floor, never answering a level past the cap", () => {
    expect(nextAvailableHours(REFERENCE_REPORT, 16)).toBe(6);
    expect(nextAvailableHours(REFERENCE_REPORT, 20)).toBe(6);
  });

  it("is no walk at all before any grid has reported", () => {
    expect(nextAvailableHours(null, 12)).toBeNull();
  });

  it("survives a report that offers nothing, though the floor makes one unreachable", () => {
    expect(nextAvailableHours({ hours: 6, levels: [] }, 6)).toBeNull();
  });

  it("starts at the range's own ends for a current outside it, never off the edge", () => {
    expect(nextAvailableHours(REFERENCE_REPORT, 3)).toBe(7);
    expect(nextAvailableHours(REFERENCE_REPORT, 30)).toBe(7);
  });
});
