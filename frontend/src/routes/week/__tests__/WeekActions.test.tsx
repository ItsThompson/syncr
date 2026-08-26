/* THE BAND, AS A COMPONENT, AND THE ONE CONTROL IT DOES NOT OWN.
 *
 * WHAT IS HERE AND NOT AT ROUTE LEVEL. Everything else this band draws is asserted through the screen, where the served
 * payload is the input and the whole line is the observable: `WeekRoute.test.tsx` holds the counts, `panels.test.tsx`
 * the two controls, `designSheetFigures.test.ts` the approve rule. What those cases cannot reach is the state where the
 * grid has reported nothing, because on the screen the grid always has: it reports before the first paint, from the
 * height it measured or from the reference display's.
 *
 * THAT STATE IS THE WHOLE POINT OF THE PROP BEING NULLABLE. The zoom segment is drawn from the grid's report, and this
 * band holds no range of its own to fall back on: a segment composed from a guessed range would offer levels the grid
 * never measured. So with no answer yet it draws no segment, and the cases below are what stop that branch from being
 * decoration a later edit can fill in. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ZoomLevel } from "../../../ui/domain";
import { zoomLevels } from "../../../ui/domain/week-grid/zoom";
import { WeekActions } from "../components/WeekActions";

/** The range a 626px grid reports, which is what the band is given here. */
const REFERENCE_LEVELS = zoomLevels(626);

function renderBand(options: {
  readonly drawnHours: number | null;
  readonly reportedLevels?: readonly ZoomLevel[] | null;
}) {
  const onPickHours = vi.fn<(hours: number) => void>();
  render(
    <MemoryRouter>
      <WeekActions
        blockCount={91}
        drawnHours={options.drawnHours}
        hasProposal
        onApprove={() => {}}
        onPickHours={onPickHours}
        onResolveNow={() => {}}
        reportedLevels={
          options.reportedLevels === undefined ? REFERENCE_LEVELS : options.reportedLevels
        }
        sessionHref="/week?week=2026-W07&mode=session"
        unconfirmedDays={5}
      />
    </MemoryRouter>,
  );
  return { onPickHours };
}

describe("the band's zoom segment", () => {
  it("offers the grid's reported range, with the drawn level pressed", () => {
    renderBand({ drawnHours: 16 });

    const group = screen.getByRole("group", { name: "Visible hours" });
    const pressed = group.querySelectorAll('[aria-pressed="true"]');

    expect(group.querySelectorAll("button")).toHaveLength(19);
    expect(pressed).toHaveLength(1);
    expect(pressed[0].textContent).toBe("16h");
  });

  /* THE KEYSTROKE IS ADVERTISED BESIDE THE CONTROL, which is the pattern the day band and the backlog band set:
   * the hint sits beside what it works, never inside it. */
  it("advertises z beside the control", () => {
    renderBand({ drawnHours: 16 });

    expect(screen.getByText("z")).toBeInTheDocument();
  });

  it("picks through to the hook, so a click proposes exactly what `z` does", async () => {
    const user = userEvent.setup();
    const { onPickHours } = renderBand({ drawnHours: 16 });

    await user.click(screen.getByRole("button", { name: /^9h/ }));

    expect(onPickHours).toHaveBeenCalledWith(9);
  });

  it("states no level at all before the grid has reported one, and still states the counts", () => {
    renderBand({ drawnHours: null, reportedLevels: null });

    expect(screen.queryByRole("group", { name: "Visible hours" })).not.toBeInTheDocument();
    expect(screen.queryByText("z")).not.toBeInTheDocument();
    expect(screen.getByText(/91 blocks/)).toBeInTheDocument();
    expect(screen.getByText(/5 days unconfirmed/)).toBeInTheDocument();
  });

  /* The counts are asserted alongside as well, because a band that rendered nothing at all would satisfy an
   * absence on its own and would be a different defect. */
});
