/* THE ZOOM CLAMP, AGAINST THE THREE DISPLAYS THE DESIGN RECORD MEASURED.
 *
 * The clamp is the one figure in the geometry that was settled by a ledger rather than derived from a rule, so the
 * three rows are the test: a 13 inch display caps at 16 hours, a 16 inch at 22, and a 27 inch at the full 24. A
 * formula that produced 15, 21 and 24 would satisfy every other property here and still be wrong. */

import { describe, expect, it } from "vitest";

import { ZOOM_MAX_HOURS, ZOOM_MIN_HOURS } from "../metrics";
import { MODAL_DURATION_MINUTES, clampVisibleHours, zoomCap, zoomLevels } from "../zoom";

/** The three display rows of the design record, with the grid height each yields. */
const DISPLAYS = [
  { label: "13 inch, 1440x900", gridHeightPx: 626, cap: 16 },
  { label: "16 inch, 1728x1117", gridHeightPx: 836, cap: 22 },
  { label: "27 inch, 2560x1440", gridHeightPx: 1136, cap: 24 },
] as const;

describe("the cap the modal block puts on the range", () => {
  it.each(DISPLAYS)("caps a $label display at $cap hours", ({ gridHeightPx, cap }) => {
    expect(zoomCap(gridHeightPx)).toBe(cap);
  });

  it("is computed from the MODAL thirty minutes, not from the shortest fifteen", () => {
    /* Clamping on fifteen minutes would halve the range on the reference display: the same arithmetic against a
     * fifteen-minute block yields 8 where the modal duration yields 16. */
    const modal = zoomCap(626);
    const shortest = Math.floor((626 * 15) / (19 * 60));

    expect(modal).toBe(16);
    expect(shortest).toBe(8);
  });

  it("never offers less than the floor, even on a display too short for the modal block", () => {
    expect(zoomCap(100)).toBe(ZOOM_MIN_HOURS);
  });

  it("never offers more than the ceiling, however tall the display", () => {
    expect(zoomCap(4000)).toBe(ZOOM_MAX_HOURS);
  });

  it("keeps a thirty-minute block at or above the label floor at its own cap", () => {
    for (const { gridHeightPx, cap } of DISPLAYS) {
      const heightPx = (gridHeightPx / (cap * 60)) * MODAL_DURATION_MINUTES;

      expect(heightPx).toBeGreaterThanOrEqual(19);
    }
  });

  it("would put a thirty-minute block BELOW the floor one level past the cap", () => {
    for (const { gridHeightPx, cap } of DISPLAYS.filter((row) => row.cap < ZOOM_MAX_HOURS)) {
      const heightPx = (gridHeightPx / ((cap + 1) * 60)) * MODAL_DURATION_MINUTES;

      expect(heightPx).toBeLessThan(19);
    }
  });
});

describe("the levels the range offers", () => {
  it("offers the whole range at every display size, so the reader sees how deep it goes", () => {
    const levels = zoomLevels(626);

    expect(levels.map((level) => level.hours)).toEqual(
      Array.from({ length: ZOOM_MAX_HOURS - ZOOM_MIN_HOURS + 1 }, (_, i) => ZOOM_MIN_HOURS + i),
    );
  });

  it("marks a level past the cap UNAVAILABLE WITH A REASON rather than hiding it", () => {
    const levels = zoomLevels(626);
    const beyond = levels.filter((level) => !level.isAvailable);

    expect(beyond.map((level) => level.hours)).toEqual([17, 18, 19, 20, 21, 22, 23, 24]);
    for (const level of beyond) expect(level.unavailableReason).not.toBeNull();
  });

  it("states no reason for a level it offers, so a reason means exactly one thing", () => {
    for (const level of zoomLevels(1136)) {
      expect(level.isAvailable).toBe(true);
      expect(level.unavailableReason).toBeNull();
    }
  });

  it("names the thirty-minute block in the reason, which is what the clamp protects", () => {
    const beyond = zoomLevels(626).find((level) => !level.isAvailable);

    expect(beyond?.unavailableReason).toContain(String(MODAL_DURATION_MINUTES));
  });
});

describe("the setting brought inside the range", () => {
  it("leaves a setting the display can offer alone", () => {
    expect(clampVisibleHours(12, 626)).toBe(12);
  });

  it("brings a setting past the cap down to it, rather than refusing to render", () => {
    expect(clampVisibleHours(24, 626)).toBe(16);
  });

  it("brings a setting below the floor up to it", () => {
    expect(clampVisibleHours(2, 626)).toBe(ZOOM_MIN_HOURS);
  });

  it("keeps a wide display's own deeper setting, which is what the per-display cap is for", () => {
    expect(clampVisibleHours(22, 836)).toBe(22);
    expect(clampVisibleHours(22, 626)).toBe(16);
  });
});
