/* THE BAND, AS A COMPONENT, AND THE ONE FIGURE IT DOES NOT OWN.
 *
 * WHAT IS HERE AND NOT AT ROUTE LEVEL. Everything else this band draws is asserted through the screen, where the served
 * payload is the input and the whole line is the observable: `WeekRoute.test.tsx` holds the counts, `panels.test.tsx`
 * the two controls, `designSheetFigures.test.ts` the approve rule. What those cases cannot reach is the state where the
 * grid has reported nothing, because on the screen the grid always has: it reports before the first paint, from the
 * height it measured or from the reference display's.
 *
 * THAT STATE IS THE WHOLE POINT OF THE PROP BEING NULLABLE. The zoom reading is the grid's answer, and this band holds
 * no figure of its own to fall back on: the level the reader asked for is exactly the figure that made the band state a
 * level the grid was not drawing. So with no answer yet it states no level, and the two cases below are what stop that
 * branch from being decoration a later edit can fill in. */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { WeekActions } from "../components/WeekActions";

/* The band draws a real `Link` to the session, which needs a router: a raw `href` would reload a screen already in
 * memory, so the component cannot be rendered without one. */
function renderBand(drawnHours: number | null) {
  return render(
    <MemoryRouter>
      <WeekActions
        blockCount={91}
        drawnHours={drawnHours}
        hasProposal
        onApprove={() => {}}
        onResolveNow={() => {}}
        sessionHref="/week?week=2026-W07&mode=session"
        unconfirmedDays={5}
      />
    </MemoryRouter>,
  );
}

describe("the band's zoom reading", () => {
  it("states the level it is given, and the key that cycles it", () => {
    renderBand(16);

    expect(screen.getByText(/16h visible/)).toBeInTheDocument();
    expect(screen.getByText("z")).toBeInTheDocument();
  });

  it("states a different level when given one, so the figure is not this band's own", () => {
    renderBand(9);

    expect(screen.getByText(/9h visible/)).toBeInTheDocument();
  });

  /* The counts are asserted here as well as the absence, because a band that rendered nothing at all would satisfy an
   * absence on its own and would be a different defect. */
  it("states no level at all before the grid has reported one, and still states the counts", () => {
    renderBand(null);

    expect(screen.queryByText(/h visible/)).not.toBeInTheDocument();
    expect(screen.queryByText("z")).not.toBeInTheDocument();
    expect(screen.getByText(/91 blocks/)).toBeInTheDocument();
    expect(screen.getByText(/5 days unconfirmed/)).toBeInTheDocument();
  });
});
