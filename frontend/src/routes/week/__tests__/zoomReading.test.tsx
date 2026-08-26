/* THE BAND'S ZOOM SEGMENT, ASSERTED AGAINST WHAT THE GRID ACTUALLY DRAWS.
 *
 * TWO FIGURES, ONE OBSERVABLE EACH, AND THE ASSERTION IS THAT THEY AGREE. The segment's pressed level is the band's
 * rendering and the drawing is a column's canvas height, which is the extent's minutes at the pixels per minute the grid
 * derived. A case that compared the pressed figure against the same clamp the band's own source calls could not fail: it
 * would be one expression asserted against itself. So the drawn figure here is computed from the reference grid height
 * and the hours independently, and the band is required to mark that same level.
 *
 * THE PROPOSAL AND THE DRAWING DIFFER ON PURPOSE. 20 is inside the range the setting offers and outside the range a
 * 626px grid can draw, which is the whole of the disagreement: at 20 a thirty-minute block would be 15.6px, under the
 * 19px its title needs. A display that could draw 20 would make every case here pass without the reading being wired
 * to anything.
 *
 * NOTHING IS LAID OUT IN A HEADLESS DOM, so the grid's measurement falls back to the reference display's 626px grid
 * and the cap is that display's own 16. That fallback is what makes these cases readable without a browser; the
 * measured-height cases live beside the grid, in `ui/domain/week-grid/__tests__/zoomReport.test.tsx`. */

import { act, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { jsonHandler } from "../../../testing/apiStub";
import { renderAt, withFreshCache } from "../../../testing/renderRoute";
import { GRID_H_PX, ZOOM_MIN_HOURS } from "../../../ui/domain";
import { useWeekScreenInteraction } from "../hooks/useWeekScreenInteraction";
import { ISO_WEEK, SETTINGS, WEEK_PATH, buildWeekView, installWeekReads } from "./fixtures";
import type { ReactNode } from "react";

/** The level the reader stores or cycles to, which this display cannot draw. */
const PROPOSED_HOURS = 20;

/** The level a 626px grid draws instead, which is what the band has to state. */
const DRAWN_HOURS = 16;

/* The axis the fixture's own week yields: the declared bounds run 06:00 to 22:00 and no block lies outside them. */
const EXTENT_MINUTES = 16 * 60;

/** The canvas height a column takes at a given zoom, from the reference grid and nothing the screen reports. */
function canvasPxAt(hours: number): number {
  return EXTENT_MINUTES * (GRID_H_PX / (hours * 60));
}

/** The hours on the segment's one pressed level, which is where the drawn figure is rendered. */
async function pickedHours(): Promise<string> {
  const group = await screen.findByRole("group", { name: "Visible hours" });
  return group.querySelector('[aria-pressed="true"]')?.textContent ?? "";
}

/** The one canvas a column draws, in pixels, which is where the level the grid actually drew is observable. */
function canvasPxOf(container: Element): number {
  const canvas = container.querySelector(".week-day__canvas");
  return Number.parseFloat((canvas as HTMLElement).style.height);
}

const press = () => userEvent.keyboard("z");

async function renderWeekStoring(visibleHours: number) {
  installWeekReads(buildWeekView());
  apiServer.use(
    jsonHandler("/api/v1/settings", { status: 200, body: { ...SETTINGS, visibleHours } }),
  );
  const rendered = renderAt(WEEK_PATH);
  await screen.findByText("MON 09");
  return rendered;
}

describe("the band states the level the grid draws", () => {
  it("has a proposal the reference display cannot draw, which is the premise of every case here", () => {
    expect(
      PROPOSED_HOURS,
      "a proposal the grid could draw would make these cases vacuous",
    ).not.toBe(DRAWN_HOURS);
    expect(canvasPxAt(PROPOSED_HOURS)).not.toBeCloseTo(canvasPxAt(DRAWN_HOURS), 1);
  });

  it(`marks ${DRAWN_HOURS}h as drawn where a stored ${PROPOSED_HOURS} draws at ${DRAWN_HOURS}`, async () => {
    const { container } = await renderWeekStoring(PROPOSED_HOURS);

    expect(canvasPxOf(container)).toBeCloseTo(canvasPxAt(DRAWN_HOURS), 1);
    expect(canvasPxOf(container)).not.toBeCloseTo(canvasPxAt(PROPOSED_HOURS), 1);
    expect(await pickedHours()).toBe(`${DRAWN_HOURS}h`);
  });

  /* THE VISIT IS HOURLY THROUGH THE AVAILABLE LEVELS ONLY, and it wraps past the top. From the fixture's stored 12
   * every level to the cap 16 is available, so four presses climb it hour by hour and the fifth wraps to the floor;
   * nothing along the way reports a level this display cannot draw, which is what `never 20h` asserts against the one
   * figure the band renders. The canvas assertion at the end is what makes the last press mean a wrapped proposal the
   * grid answered, rather than a press the screen never saw. */
  it("climbs the available levels hourly from the stored one, then wraps to the floor", async () => {
    const { container } = await renderWeekStoring(SETTINGS.visibleHours);

    await press();
    expect(await pickedHours()).toBe("13h");

    await press();
    expect(await pickedHours()).toBe("14h");

    await press();
    expect(await pickedHours()).toBe("15h");

    await press();
    expect(await pickedHours()).toBe("16h");

    /* The fifth press wraps: every level past the cap is unavailable, so the walk lands on the floor rather
     * than on one of them, and `never 20h` is what makes that mean a skipped refusal instead of a quiet press. */
    await press();
    const wrapped = await pickedHours();
    expect(wrapped).toBe(`${ZOOM_MIN_HOURS}h`);
    expect(wrapped).not.toBe(`${PROPOSED_HOURS}h`);
    expect(canvasPxOf(container)).toBeCloseTo(canvasPxAt(ZOOM_MIN_HOURS), 1);
  });

  /* THE TICKET'S OWN CASE, AT ITS OWN SEAM: the cap is where the range stops, so from it one press skips every level
   * past the cap -- none available, each carrying its own refusal -- and lands on the floor. Nineteen levels in the
   * report, sixteen available, and the walk still terminates because the wrap is part of the walk. */
  it("wraps from the cap straight to the floor, never reporting a level past the cap", async () => {
    const { container } = await renderWeekStoring(DRAWN_HOURS);

    await press();

    expect(await pickedHours()).toBe(`${ZOOM_MIN_HOURS}h`);
    expect(canvasPxOf(container)).toBeCloseTo(canvasPxAt(ZOOM_MIN_HOURS), 1);
  });
});

/* WHERE THE ANSWER BECOMES A RENDERING DECISION, held one layer below the screen because the screen cannot reach this
 * state: on the screen the grid reports before the first paint, so a reader never meets a band with no answer yet.
 *
 * The hook is rendered with no grid at all, which is the same condition the first render is in. What is asserted is
 * that the level the reader asked for does NOT stand in for the level a grid has not yet drawn. That substitution is
 * the defect this ticket closed, and it is the edit the missing cell most invites: the figure nearest to hand is the
 * proposal, and one call site filling it in is all it takes to bring the falsehood back. */
/* The hook navigates, reads through SWR, and subscribes to the stream, so it needs a router and a cache of its own.
 * Declared outside the case, because a wrapper rebuilt per render remounts the tree under it. */
function HookHost({ children }: { readonly children: ReactNode }) {
  return <MemoryRouter>{withFreshCache(<>{children}</>)}</MemoryRouter>;
}

describe("the level the screen states before a grid has drawn one", () => {
  it("is no level, rather than the level the reader asked for", () => {
    installWeekReads(buildWeekView());
    const { result } = renderHook(
      () =>
        useWeekScreenInteraction({
          isoWeek: ISO_WEEK,
          days: [],
          view: null,
          today: "2026-02-09",
          visibleHours: PROPOSED_HOURS,
        }),
      { wrapper: HookHost },
    );

    expect(result.current.drawnHours).toBeNull();
    expect(result.current.proposedHours).toBe(PROPOSED_HOURS);
  });

  /* A PRESS BEFORE THE FIRST ANSWER HAS NOTHING TO WALK, so it proposes nothing rather than reading levels off a
   * report the grid never made. Dispatched by hand rather than through userEvent, so the dispatch is synchronous
   * inside the assertion: what this case pins is the proposal surviving the press, which the walk's own cases
   * hold directly against the guard in `zoomWalk.test.ts`. */
  it("leaves the proposal alone when z lands before any grid has reported", () => {
    installWeekReads(buildWeekView());
    const { result } = renderHook(
      () =>
        useWeekScreenInteraction({
          isoWeek: ISO_WEEK,
          days: [],
          view: null,
          today: "2026-02-09",
          visibleHours: PROPOSED_HOURS,
        }),
      { wrapper: HookHost },
    );

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "z" }));
    });

    expect(result.current.proposedHours).toBe(PROPOSED_HOURS);
    expect(result.current.reportedLevels).toBeNull();
  });
});
