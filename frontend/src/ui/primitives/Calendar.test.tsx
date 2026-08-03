/* The month grid, mounted directly and left open.
 *
 * The date picker is the only consumer today and it CLOSES its popover on select, so the grid unmounts with
 * its cursor and reopening puts the tab stop on the chosen day through `selected`. Everything about the
 * cursor surviving a choice is therefore invisible through that consumer, which is what this harness exists
 * for: it holds the grid open across a click and an arrow key, the way a screen that renders a calendar
 * inline will.
 *
 * A day is found by its label rather than by its role, because Testing Library computes a role from the
 * element alone and reports `cell` for a `td` that HTML's own mapping makes a `gridcell` inside
 * `table[role="grid"]`. `dayLabel` is the component's own formatter, so the handle cannot drift from what a
 * screen reader hears. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Calendar } from "./Calendar";
import { dayLabel, type CalendarMonth } from "./month";

const MARCH = { year: 2025, month: 3 } satisfies CalendarMonth;
const TODAY = "2025-03-11";

function renderCalendar(props: Partial<Parameters<typeof Calendar>[0]> = {}) {
  const onSelect = vi.fn<(iso: string) => void>();
  const onMonthChange = vi.fn<(next: CalendarMonth) => void>();
  const result = render(
    <Calendar
      month={MARCH}
      onMonthChange={onMonthChange}
      selected={null}
      onSelect={onSelect}
      today={TODAY}
      label="Deadline"
      {...props}
    />,
  );
  return { onSelect, onMonthChange, ...result };
}

const day = (iso: string): HTMLElement => screen.getByLabelText(dayLabel(iso));

/** The month's one tab stop, which is the only cell a reader can reach with Tab. */
function tabStop(): string | null {
  return (
    document.querySelector('[role="grid"] td[tabindex="0"]')?.getAttribute("aria-label") ?? null
  );
}

describe("the month's one tab stop", () => {
  it("starts on today, so entering the grid lands somewhere meaningful", () => {
    renderCalendar();

    expect(tabStop()).toBe(dayLabel(TODAY));
  });

  it("prefers the chosen day to today, because that is the value being edited", () => {
    renderCalendar({ selected: "2025-03-20" });

    expect(tabStop()).toBe(dayLabel("2025-03-20"));
  });

  /* THE CURSOR FOLLOWS A CLICK, not the arrow keys alone. Without this the stop stayed on the last day an
   * arrow key reached, so tabbing out and shift-tabbing back in re-entered the grid on a day the reader had
   * not picked. */
  it("follows a click, so tabbing back in returns to the day the reader picked", async () => {
    const { onSelect } = renderCalendar();

    await userEvent.click(day("2025-03-06"));

    expect(onSelect).toHaveBeenCalledWith("2025-03-06");
    expect(tabStop()).toBe(dayLabel("2025-03-06"));
  });

  it("follows the later of an arrow move and a click, in either order", async () => {
    renderCalendar();

    day(TODAY).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(tabStop()).toBe(dayLabel("2025-03-18"));

    await userEvent.click(day("2025-03-04"));
    expect(tabStop()).toBe(dayLabel("2025-03-04"));
  });

  it("follows a keyboard activation, which chooses the day the cursor is already on", async () => {
    const { onSelect } = renderCalendar();

    day(TODAY).focus();
    await userEvent.keyboard("{ArrowRight}{Enter}");

    expect(onSelect).toHaveBeenCalledWith("2025-03-12");
    expect(tabStop()).toBe(dayLabel("2025-03-12"));
  });
});

describe("the cursor's focus", () => {
  it("lands on the cell the arrow key moved to, so the grid is navigable by keyboard alone", async () => {
    renderCalendar();

    day(TODAY).focus();
    await userEvent.keyboard("{ArrowRight}");

    expect(document.activeElement).toBe(day("2025-03-12"));
  });

  /* Paging away and back must not steal focus from the button that paged: the effect is keyed on the cursor,
   * so a render that changes the month moves nothing. */
  it("stays on the month-step button across a page away and back", async () => {
    const { rerender } = renderCalendar();
    const next = screen.getByRole("button", { name: "Next month" });

    await userEvent.click(next);
    rerender(
      <Calendar
        month={{ year: 2025, month: 4 }}
        onMonthChange={vi.fn<(next: CalendarMonth) => void>()}
        selected={null}
        onSelect={vi.fn<(iso: string) => void>()}
        today={TODAY}
        label="Deadline"
      />,
    );

    expect(document.activeElement).toBe(next);
  });
});
