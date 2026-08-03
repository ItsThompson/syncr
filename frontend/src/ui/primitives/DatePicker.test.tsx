/* The date picker and its month grid.
 *
 * TODAY ARRIVES AS A PROP, so these tests pin a date rather than a clock. That is not only convenience: today
 * depends on the reader's home zone or their travel override, which the domain layer knows and a control cannot.
 * February 2025 is the reference week's month, which is what `docs/design/components.html` renders.
 *
 * TODAY IS `aria-current="date"` RATHER THAN `data-today`, which is where this departs from the sheet: the closed
 * state vocabulary is closed, and ARIA already models the state, so minting a variant would put one idea in two
 * forms. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { DatePicker } from "./DatePicker";
import { dayLabel } from "./month";

const TODAY = "2025-02-11";

function renderPicker(props: Partial<Parameters<typeof DatePicker>[0]> = {}) {
  const onValueChange = vi.fn<(next: string) => void>();
  const result = render(
    <DatePicker
      value="2025-02-19"
      onValueChange={onValueChange}
      today={TODAY}
      label="Deadline"
      {...props}
    />,
  );
  return { onValueChange, ...result };
}

async function openCalendar(): Promise<void> {
  await userEvent.click(screen.getByRole("button", { name: /choose from a calendar/ }));
}

/* A day is found by its label rather than by its role. The cell IS a gridcell in a browser, where HTML's own
 * mapping reads a `td` inside a `table[role="grid"]` that way, but Testing Library computes a role from the
 * element alone and reports `cell`. The label is the stable handle, and the grid semantics are asserted once
 * below rather than in every case.
 *
 * The label itself is the formatted date, because a cell's visible text is the day of the month alone and an
 * ISO string read aloud is a run of digits. `dayLabel` is the component's own formatter, so a test cannot
 * drift from what a screen reader hears. */
function day(iso: string): HTMLElement {
  return screen.getByLabelText(dayLabel(iso));
}

describe("the date field", () => {
  it("is typeable, which is the primary way in for a keyboard-first product", async () => {
    const { onValueChange } = renderPicker({ value: "" });

    await userEvent.type(screen.getByLabelText("Deadline"), "2");

    expect(onValueChange).toHaveBeenCalledWith("2");
  });

  it("shows the ISO form, so a reader can see the whole value in the box", () => {
    renderPicker();

    expect(screen.getByLabelText("Deadline")).toHaveValue("2025-02-19");
  });

  it("says what shape it wants rather than leaving a reader to guess", () => {
    renderPicker({ value: "" });

    expect(screen.getByLabelText("Deadline")).toHaveAttribute("placeholder", "YYYY-MM-DD");
  });

  it("marks invalid with aria-invalid", () => {
    renderPicker({ isInvalid: true });

    expect(screen.getByLabelText("Deadline")).toHaveAttribute("aria-invalid", "true");
  });

  it("opens the calendar from its own control rather than from the text box", async () => {
    renderPicker();

    expect(screen.queryByRole("grid")).toBeNull();
    await openCalendar();

    expect(screen.getByRole("grid", { name: "Deadline" })).toBeInTheDocument();
  });

  it("disables the trigger with the field, so half a control cannot stay live", () => {
    renderPicker({ isDisabled: true });

    expect(screen.getByRole("button", { name: /choose from a calendar/ })).toBeDisabled();
  });

  it("carries the same typographic mark the select uses", () => {
    const { container } = renderPicker();

    expect(container.querySelector(".glyph--select-arrow")).not.toBeNull();
  });
});

describe("the month grid", () => {
  it("is a grid whose cells are table cells, which is the pattern a date picker takes", async () => {
    renderPicker();
    await openCalendar();

    const grid = screen.getByRole("grid", { name: "Deadline" });
    const cell = day("2025-02-19");

    expect(grid.tagName).toBe("TABLE");
    expect(cell.tagName).toBe("TD");
    expect(grid.contains(cell)).toBe(true);
  });

  it("opens on the month of the chosen date", async () => {
    renderPicker();
    await openCalendar();

    expect(screen.getByText("February 2025")).toBeInTheDocument();
  });

  it("opens on today's month when nothing is chosen", async () => {
    renderPicker({ value: "" });
    await openCalendar();

    expect(screen.getByText("February 2025")).toBeInTheDocument();
  });

  it("marks the chosen day with aria-selected", async () => {
    renderPicker();
    await openCalendar();

    expect(day("2025-02-19")).toHaveAttribute("aria-selected", "true");
  });

  it("marks today with aria-current, which is the state ARIA already models", async () => {
    renderPicker();
    await openCalendar();

    expect(day(TODAY)).toHaveAttribute("aria-current", "date");
  });

  it("hands the caller the day that was clicked and closes", async () => {
    const { onValueChange } = renderPicker();
    await openCalendar();

    await userEvent.click(day("2025-02-14"));

    expect(onValueChange).toHaveBeenCalledWith("2025-02-14");
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it("moves a month at a time from its own two controls", async () => {
    renderPicker();
    await openCalendar();

    await userEvent.click(screen.getByRole("button", { name: "Next month" }));

    expect(screen.getByText("March 2025")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));

    expect(screen.getByText("January 2025")).toBeInTheDocument();
  });

  it("takes one tab stop for the whole month, which is what the arrow keys are for", async () => {
    renderPicker();
    await openCalendar();

    const stops = screen
      .getAllByRole("cell")
      .filter((cell) => cell.getAttribute("tabindex") === "0");

    expect(stops).toHaveLength(1);
    expect(stops[0]).toHaveAttribute("aria-label", dayLabel("2025-02-19"));
  });

  /* March 2025 starts on a Saturday, so the grid's first CELL is Monday 24 February. A tab stop there puts
   * the reader in the previous month while the header reads March, and the arrow keys then move from a day
   * they cannot see is current. */
  it("keeps the tab stop inside the month on show, not on the grid's first cell", async () => {
    renderPicker();
    await openCalendar();

    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    const stops = screen
      .getAllByRole("cell")
      .filter((cell) => cell.getAttribute("tabindex") === "0");

    expect(stops).toHaveLength(1);
    expect(stops[0]).toHaveAttribute("aria-label", dayLabel("2025-03-01"));
  });

  it("moves the cursor a day at a time with the arrow keys", async () => {
    renderPicker();
    await openCalendar();

    day("2025-02-19").focus();
    await userEvent.keyboard("{ArrowRight}");

    expect(day("2025-02-20")).toHaveFocus();
  });

  it("moves a week at a time with the vertical arrows", async () => {
    renderPicker();
    await openCalendar();

    day("2025-02-19").focus();
    await userEvent.keyboard("{ArrowDown}");

    expect(day("2025-02-26")).toHaveFocus();
  });

  it("turns the page when the cursor leaves the month", async () => {
    renderPicker();
    await openCalendar();

    day("2025-02-19").focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");

    expect(screen.getByText("March 2025")).toBeInTheDocument();
    expect(day("2025-03-05")).toHaveFocus();
  });

  it("chooses the cursor's day on Enter", async () => {
    const { onValueChange } = renderPicker();
    await openCalendar();

    day("2025-02-19").focus();
    await userEvent.keyboard("{ArrowRight}{Enter}");

    expect(onValueChange).toHaveBeenCalledWith("2025-02-20");
  });

  /* Focus follows the cursor when the cursor MOVES, and at no other time. Paging away and back re-renders a
   * grid that contains the cursor's day again, and a focus call on that render takes the reader off the
   * button they just pressed. */
  it("leaves focus alone on a render the arrow keys did not cause", async () => {
    renderPicker();
    await openCalendar();

    day("2025-02-19").focus();
    await userEvent.keyboard("{ArrowRight}");
    const next = screen.getByRole("button", { name: "Next month" });
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    await userEvent.click(next);

    expect(next).toHaveFocus();
    expect(day("2025-02-20")).not.toHaveFocus();
  });

  it("draws the neighbouring months' days muted rather than dropping them", async () => {
    renderPicker();
    await openCalendar();

    expect([...day("2025-01-31").classList]).toContain("calendar__day--outside");
  });
});

describe("the calendar's stylesheet", () => {
  it("marks today with the emphasised rule in ink, never in amber", async () => {
    const css = await kitStylesheet("Calendar.css");
    const today = /\.calendar__day\[aria-current="date"\]\s*\{([^}]*)\}/.exec(css);

    expect(today?.[1]).toContain("border-bottom-color: var(--ink-deep)");
    expect(css).not.toContain("--signal-amber");
  });

  it("pairs the chosen day's fill with a border, so the choice survives forced colors", async () => {
    const css = await kitStylesheet("Calendar.css");
    const selected = /\.calendar__day\[aria-selected="true"\]\s*\{([^}]*)\}/.exec(css);

    expect(selected?.[1]).toContain("background: var(--ink-deep)");
    expect(selected?.[1]).toContain("border: var(--hairline) solid var(--ink-deep)");
  });

  it("carries the popover's lift from the shared overlay class", async () => {
    const { baseElement } = renderPicker();
    await openCalendar();

    expect(baseElement.querySelector(".date-picker__panel")?.classList).toContain("overlay");
  });
});
