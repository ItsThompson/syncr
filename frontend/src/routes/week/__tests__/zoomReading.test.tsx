/* THE BAND'S ZOOM READING, ASSERTED AGAINST WHAT THE GRID ACTUALLY DRAWS.
 *
 * TWO FIGURES, ONE OBSERVABLE EACH, AND THE ASSERTION IS THAT THEY AGREE. The reading is the band's rendered text and
 * the drawing is a column's canvas height, which is the extent's minutes at the pixels per minute the grid derived. A
 * case that compared the band's number against the same clamp the band's own source calls could not fail: it would be
 * one expression asserted against itself. So the drawn figure here is computed from the reference grid height and the
 * hours independently, and the band is required to state that same figure.
 *
 * THE PROPOSAL AND THE DRAWING DIFFER ON PURPOSE. 20 is inside the range the setting offers and outside the range a
 * 626px grid can draw, which is the whole of the disagreement: at 20 a thirty-minute block would be 15.6px, under the
 * 19px its title needs. A display that could draw 20 would make every case here pass without the reading being wired
 * to anything.
 *
 * NOTHING IS LAID OUT IN A HEADLESS DOM, so the grid's measurement falls back to the reference display's 626px grid
 * and the cap is that display's own 16. That fallback is what makes these cases readable without a browser; the
 * measured-height cases live beside the grid, in `ui/domain/week-grid/__tests__/zoomReport.test.tsx`. */

import { renderHook, screen } from "@testing-library/react";
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

/** The band's own line, which is where the zoom reading is rendered. */
async function bandLine(): Promise<string> {
  return (await screen.findByText(/h visible/)).textContent ?? "";
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

  it(`reads ${DRAWN_HOURS}h visible where a stored ${PROPOSED_HOURS} draws at ${DRAWN_HOURS}`, async () => {
    const { container } = await renderWeekStoring(PROPOSED_HOURS);

    expect(canvasPxOf(container)).toBeCloseTo(canvasPxAt(DRAWN_HOURS), 1);
    expect(canvasPxOf(container)).not.toBeCloseTo(canvasPxAt(PROPOSED_HOURS), 1);
    expect(await bandLine()).toContain(`${DRAWN_HOURS}h visible`);
    expect(await bandLine()).not.toContain(`${PROPOSED_HOURS}h visible`);
  });

  /* THE WRAP IS WHAT PROVES THE PRESSES LANDED, and it is here because the two figures this case is about are
   * indistinguishable on this display: a press that proposes 20 and a press the screen never saw both leave the band
   * reading 16. The ladder is 6, 9, 12, 16, 20, 24 and it wraps, so from the fixture's stored 12 exactly four presses
   * read 6: three would leave 24 and five would leave 9. So the last assertion is what makes the middle two mean that
   * the screen proposed a level this grid refuses, rather than that nothing happened. */
  it(`reads ${DRAWN_HOURS}h visible while z cycles past what this grid can draw`, async () => {
    const { container } = await renderWeekStoring(SETTINGS.visibleHours);

    await press();
    expect(await bandLine()).toContain(`${DRAWN_HOURS}h visible`);

    await press();
    expect(await bandLine()).toContain(`${DRAWN_HOURS}h visible`);
    expect(await bandLine()).not.toContain(`${PROPOSED_HOURS}h visible`);
    expect(canvasPxOf(container)).toBeCloseTo(canvasPxAt(DRAWN_HOURS), 1);

    await press();
    expect(await bandLine()).toContain(`${DRAWN_HOURS}h visible`);

    await press();
    expect(await bandLine()).toContain(`${ZOOM_MIN_HOURS}h visible`);
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
});
