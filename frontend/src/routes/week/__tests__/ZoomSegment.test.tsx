/* THE BAND'S ZOOM SEGMENT, AS A CONTROL OVER THE RANGE THE GRID REPORTED.
 *
 * THE SEGMENT IS THE REPORT'S READER. The grid answers with the whole 6..24 range, each level marked with
 * whether this display can draw it; what this control owes that answer is every level rendered as a segment,
 * the unavailable ones disabled and carrying their OWN reason in their accessible name rather than a generic
 * string, because a reason computed per level and announced as one sentence for all of them is the same dead
 * output a segment without reasons would be.
 *
 * THE PICKED LEVEL IS THE DRAWN ONE. The band passes the grid's own answer, not the level the reader asked
 * for, so a pressed 16 over a display whose cap is 16 is the truth and a pressed 20 would be the falsehood
 * the reading replaced.
 *
 * A PICK IS A PROPOSAL, NOT A WRITE. Clicking an available level proposes it to the grid exactly one press
 * of `z` does, and clicking is impossible on an unavailable level: it is disabled, which is what its reason
 * explains. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ZOOM_MAX_HOURS, ZOOM_MIN_HOURS, type ZoomLevel } from "../../../ui/domain";
import { zoomLevels } from "../../../ui/domain/week-grid/zoom";
import { ZoomSegment } from "../components/ZoomSegment";

/** The range a 626px grid reports: everything to 16 available, 17 and past unavailable with a reason. */
const REFERENCE_LEVELS: readonly ZoomLevel[] = zoomLevels(626);

function renderSegment(levels: readonly ZoomLevel[] = REFERENCE_LEVELS) {
  const onPick = vi.fn<(hours: number) => void>();
  render(<ZoomSegment levels={levels} onPick={onPick} pickedHours={16} />);
  return { group: screen.getByRole("group", { name: "Visible hours" }), onPick };
}

const segmentOf = (hours: number): HTMLElement =>
  screen.getByRole("button", { name: new RegExp(`^${hours}h`) });

describe("the levels the segment offers", () => {
  it("offers the whole reported range, 6 to 24, whatever this display can draw", () => {
    renderSegment();

    const hours = screen
      .getAllByRole("button")
      .map((segment) => Number.parseInt(segment.textContent ?? "", 10));

    expect(hours).toEqual(
      Array.from({ length: ZOOM_MAX_HOURS - ZOOM_MIN_HOURS + 1 }, (_, i) => ZOOM_MIN_HOURS + i),
    );
  });

  it("disables every level past this display's cap", () => {
    renderSegment();

    for (let hours = 17; hours <= 24; hours += 1) {
      expect(segmentOf(hours)).toBeDisabled();
    }
    for (let hours = ZOOM_MIN_HOURS; hours <= 16; hours += 1) {
      expect(segmentOf(hours)).toBeEnabled();
    }
  });

  /* THE REASON IS PER-LEVEL AND IT IS THE LEVEL'S OWN. Each disabled segment's accessible name opens with
   * its hours and closes with the words the report gave that level, so the per-level output the domain
   * computes reaches a reader instead of dying in a field nothing renders. Asserted against the report's own
   * strings rather than a copy of them, because the claim is the wiring, not the wording. */
  it("carries each unavailable level's OWN reason in its accessible name", () => {
    renderSegment();

    for (const level of REFERENCE_LEVELS.filter((each) => !each.isAvailable)) {
      expect(level.unavailableReason).not.toBeNull();
      expect(segmentOf(level.hours)).toHaveAccessibleName(
        `${level.hours}h \u00b7 ${level.unavailableReason}`,
      );
    }
  });

  it("states no reason beside a level it offers", () => {
    renderSegment();

    expect(segmentOf(12)).toHaveAccessibleName("12h");
  });
});

describe("the level the segment marks as drawn", () => {
  it("marks the level it is given with aria-pressed, and no other", () => {
    renderSegment();

    const pressed = screen
      .getAllByRole("button")
      .filter((segment) => segment.getAttribute("aria-pressed") === "true");

    expect(pressed.map((segment) => segment.textContent)).toEqual(["16h"]);
  });

  it("marks a different level when given one, so the mark is not this control's own", () => {
    render(<ZoomSegment levels={REFERENCE_LEVELS} onPick={() => {}} pickedHours={6} />);

    const pressed = screen
      .getAllByRole("button")
      .filter((segment) => segment.getAttribute("aria-pressed") === "true");

    expect(pressed.map((segment) => segment.textContent)).toEqual(["6h"]);
  });
});

describe("picking a level", () => {
  it("proposes the level's hours, the way `z` proposes one", async () => {
    const user = userEvent.setup();
    const { onPick } = renderSegment();

    await user.click(segmentOf(9));

    expect(onPick).toHaveBeenCalledWith(9);
  });

  it("offers nothing to pick on an unavailable level, which its reason explains", async () => {
    const user = userEvent.setup();
    const { onPick } = renderSegment();

    await user.click(segmentOf(20));

    expect(onPick).not.toHaveBeenCalled();
  });
});
